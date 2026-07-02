"""Guardrail: block NEW silent failures at review time (issue #29 invariant R2).

Two static AST rules scanned over app/ on every test run:
  1. A user-gate early-return (`if not self._current_user_id: return/pass`) with
     no call to a user-feedback surface — the exact "Save does nothing" class.
  2. A bool-returning DatabaseManager mutator (returns False on failure) whose
     result is discarded — a write that can fail silently.

A legitimately-silent site is grandfathered with a marker that carries a reason:
`# silent-ok: <why>` (standalone, not a ruff noqa code). New violations must add
a feedback call or a justified marker; they cannot land silently.
"""
import ast
import pathlib
import re

APP = pathlib.Path(__file__).resolve().parent.parent / "app"

FEEDBACK_FNS = {
    "report_soft_error", "_android_toast", "_info_popup", "_require_user",
    "set_formula_slot_status", "_confirm_program_action", "focus_device_section",
    "update_state", "show_alert", "notify_user", "show_backup_status",
}
MARKER = re.compile(r"#\s*silent-ok:\s*\S")


def _returns_boolish(fn: ast.FunctionDef) -> bool:
    """True for `-> bool`, `-> bool | None`, and `-> Optional[bool]` annotations —
    all shapes a failure-signalling write can take."""
    if fn.returns is None:
        return False
    src = ast.unparse(fn.returns).replace(" ", "")
    return src in ("bool", "bool|None", "None|bool", "Optional[bool]")


def _bool_db_methods() -> set[str]:
    """DatabaseManager methods with a boolish return (failure-signalling writes)."""
    tree = ast.parse((APP / "storage" / "database.py").read_text())
    return {
        n.name for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and _returns_boolish(n)
        and not n.name.startswith("_")  # public mutators only, not private predicates
    }


def _marked(lines: list[str], node: ast.AST) -> bool:
    end = getattr(node, "end_lineno", node.lineno)
    return any(MARKER.search(lines[i]) for i in range(node.lineno - 1, min(end, len(lines))))


def _aliases_of_current_user(fn: ast.AST) -> set[str]:
    """Locals assigned directly from self._current_user_id inside fn — so an
    aliased gate check (`uid = self._current_user_id; if not uid: return`) is
    caught, not just the literal attribute."""
    aliases = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and ast.unparse(node.value).strip() == "self._current_user_id":
            aliases.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return aliases


def _is_absence_check(test_src: str, aliases: set[str] = frozenset()) -> bool:
    if ("not self._current_user_id" in test_src
            or "self._current_user_id is None" in test_src
            or "self._current_user_id == None" in test_src):
        return True
    return any(f"not {a}" in test_src or f"{a} is None" in test_src
               or f"{a} == None" in test_src for a in aliases)


def find_silent_gate_returns(src: str, filename: str = "<t>") -> list[tuple]:
    tree = ast.parse(src)
    lines = src.splitlines()
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        aliases = _aliases_of_current_user(fn)
        for node in ast.walk(fn):
            if not (isinstance(node, ast.If) and _is_absence_check(ast.unparse(node.test), aliases)):
                continue
            body_src = " ".join(ast.unparse(s) for s in node.body)
            silent = any(isinstance(s, (ast.Return, ast.Pass)) for s in node.body)
            has_feedback = any(f in body_src for f in FEEDBACK_FNS)
            if silent and not has_feedback and not _marked(lines, node):
                out.append((filename, node.lineno, fn.name))
    return out


def find_ignored_bool_db_calls(src: str, filename: str = "<t>", methods=None) -> list[tuple]:
    methods = methods or _bool_db_methods()
    tree = ast.parse(src)
    lines = src.splitlines()
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            f = node.value.func
            if (isinstance(f, ast.Attribute) and f.attr in methods
                    and not MARKER.search(lines[node.lineno - 1])):
                out.append((filename, node.lineno, f.attr))
    return out


def _scan_app(finder) -> list[tuple]:
    out = []
    for f in sorted(APP.rglob("*.py")):
        out += finder(f.read_text(), str(f.relative_to(APP.parent)))
    return out


def _fmt(v) -> str:
    return "\n".join(f"  {f}:{ln}  {name}" for f, ln, name in v)


# ---- scanner unit tests (lock the matcher so the guardrail can't silently rot) ----

def test_flags_silent_gate_return():
    src = "class A:\n    def h(self):\n        if not self._current_user_id:\n            return\n"
    assert find_silent_gate_returns(src)


def test_passes_gate_return_with_feedback():
    src = ("class A:\n    def h(self):\n        if not self._current_user_id:\n"
           "            self._info_popup('x', 'y')\n            return\n")
    assert not find_silent_gate_returns(src)


def test_respects_silent_ok_marker():
    src = ("class A:\n    def h(self):\n        if not self._current_user_id:\n"
           "            return  # silent-ok: batch save, nothing to persist\n")
    assert not find_silent_gate_returns(src)


def test_flags_aliased_gate_return():
    # #4: `uid = self._current_user_id; if not uid: return` must be caught too.
    src = ("class A:\n    def h(self):\n        uid = self._current_user_id\n"
           "        if not uid:\n            return\n")
    assert find_silent_gate_returns(src)


def test_ignores_positive_user_check():
    # _require_user's `if self._current_user_id: return uid` is not a failure path.
    src = "class A:\n    def h(self):\n        if self._current_user_id:\n            return self._current_user_id\n"
    assert not find_silent_gate_returns(src)


def test_flags_ignored_bool_db_call():
    src = "class A:\n    def h(self):\n        self._db.add_saved_program(1, 'n', [])\n"
    assert find_ignored_bool_db_calls(src, methods={"add_saved_program"})


def test_boolish_annotations_are_matched():
    # #11: `-> bool | None` / `-> Optional[bool]` are failure-signalling too.
    src = ("class D:\n"
           "    def add_x(self) -> bool | None: ...\n"
           "    def add_y(self) -> 'Optional[bool]': ...\n"
           "    def add_z(self) -> bool: ...\n"
           "    def get_rows(self) -> list[bool]: ...\n")
    fns = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)]
    matched = {f.name for f in fns if _returns_boolish(f)}
    assert "add_x" in matched and "add_z" in matched
    assert "get_rows" not in matched  # list[bool] is data, not a failure signal


def test_passes_checked_bool_db_call():
    src = "class A:\n    def h(self):\n        if not self._db.add_saved_program(1, 'n', []):\n            self._info_popup('x', 'y')\n"
    assert not find_ignored_bool_db_calls(src, methods={"add_saved_program"})


# ---- the rules, enforced across app/ ----

def test_no_unmarked_silent_user_gate_returns():
    v = _scan_app(find_silent_gate_returns)
    assert not v, "Silent user-gate returns (add a feedback call or `# silent-ok: reason`):\n" + _fmt(v)


def test_no_ignored_bool_returning_db_writes():
    methods = _bool_db_methods()
    v = _scan_app(lambda s, f: find_ignored_bool_db_calls(s, f, methods))
    assert not v, "Discarded failure-returns from bool DB writes:\n" + _fmt(v)
