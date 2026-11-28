import ast
import math
import operator
from collections import deque
from collections.abc import Callable, Mapping

from app.logger import logger

# Allowed variable names the user can reference in formulas
ALLOWED_VARIABLES = {
    "alpha1", "alpha2", "beta1", "beta2", "gamma1", "gamma2",
    "theta", "delta",
    "alpha", "beta", "gamma",
    "alpha_norm", "beta_norm", "gamma_norm", "theta_norm", "delta_norm",
    "total_power",
    # sqrt-normalized relative bands: sqrt(band / sum_of_6_bands)
    "s_alpha1", "s_alpha2", "s_beta1", "s_beta2", "s_theta", "s_delta",
    "meditation_score", "shamatha_score", "distraction", "sinking",
    "subtle_distraction", "stability", "calmness",
    "native_attention", "native_meditation",
}

# Safe math functions the user can call
ALLOWED_FUNCTIONS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "pow": pow,
    "min": min,
    "max": max,
    "sin": math.sin,
    "cos": math.cos,
    "tanh": math.tanh,
}

# Functions that operate on windowed history — handled specially
_WINDOWED_FUNCTIONS = {"avg"}

_MAX_WINDOW = 600

# Safe binary/unary operators
_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_COMPARISONS = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}

_MAX_RESULT = 1e12
_MAX_FORMULA_LEN = 500


def _parse(formula: str) -> tuple[ast.Expression | None, str]:
    """The formula's tree, or None and why it can't run."""
    if len(formula) > _MAX_FORMULA_LEN:
        return None, f"Formula too long (max {_MAX_FORMULA_LEN} chars)"
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as e:
        return None, f"Syntax error: {e.msg}"
    why = _refusal(tree.body)
    return (None, why) if why else (tree, "")


def _refusal(node: ast.AST) -> str | None:
    """Why a formula can't have this node, or one under it; None when it can."""
    match node:
        case ast.Constant(value=value):
            return None if isinstance(value, (int, float)) else f"Unsupported constant type: {type(value).__name__}"
        case ast.Name(id=name):
            return None if name in ALLOWED_VARIABLES or name in ALLOWED_FUNCTIONS else f"Unknown variable: '{name}'"
        case ast.UnaryOp(op=op, operand=operand):
            return _operator_refusal(op) or _refusal(operand)
        case ast.BinOp(op=op, left=left, right=right):
            return _operator_refusal(op) or _first_refusal((left, right))
        case ast.Call():
            return _call_refusal(node)
        case ast.IfExp(test=test, body=body, orelse=orelse):
            return _first_refusal((test, body, orelse))
        case ast.Compare(left=left, ops=ops, comparators=comparators):
            return _first_refusal((left, *comparators)) or next(
                (f"Unsupported comparison: {type(op).__name__}" for op in ops if type(op) not in _COMPARISONS), None)
    return f"Unsupported expression: {type(node).__name__}"


def _first_refusal(nodes) -> str | None:
    return next((why for why in map(_refusal, nodes) if why), None)


def _operator_refusal(op: ast.AST) -> str | None:
    return None if type(op) in _OPERATORS else f"Unsupported operator: {type(op).__name__}"


def _call_refusal(node: ast.Call) -> str | None:
    """A call of an allowed function by its name, with positional arguments it allows."""
    if not isinstance(node.func, ast.Name):
        return "Only simple function calls allowed"
    name = node.func.id
    if name not in ALLOWED_FUNCTIONS and name not in _WINDOWED_FUNCTIONS:
        return f"Unknown function: '{name}'"
    if node.keywords:
        return "Keyword arguments not allowed"
    return _windowed_refusal(node) if name in _WINDOWED_FUNCTIONS else _first_refusal(node.args)


def _windowed_refusal(node: ast.Call) -> str | None:
    """avg(expr, N): an allowed expression over a window of 1 to _MAX_WINDOW ticks."""
    name = node.func.id
    if len(node.args) != 2:
        return f"{name}() requires exactly 2 arguments: {name}(expr, N)"
    expr, window = node.args
    why = _refusal(expr)
    if why:
        return f"In {name}() first argument: {why}"
    if not isinstance(window, ast.Constant) or not isinstance(window.value, (int, float)):
        return f"{name}() second argument must be a number"
    if not 1 <= window.value < _MAX_WINDOW + 1:  # int() of it in range; compared as written, any size of number
        return f"{name}() window size must be 1-{_MAX_WINDOW}"
    return None


def _avg_exprs(node: ast.AST) -> list[tuple[str, ast.AST]]:
    """(key, expression) of each distinct avg() argument in the tree: the values its history keeps."""
    exprs = {ast.dump(child.args[0]): child.args[0] for child in ast.walk(node)
             if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
             and child.func.id in _WINDOWED_FUNCTIONS and child.args}
    return list(exprs.items())


class CustomFormulaEvaluator:
    """Safe evaluator for user-defined EEG metric formulas.

    Parses a Python-style math expression using AST and evaluates it
    against EEG band powers and computed metrics. Only allows whitelisted
    variables, functions, and operators. Handles division by zero,
    overflow, and malformed expressions gracefully.
    """

    def __init__(self) -> None:
        self._formula: str = ""
        self._ast_tree: ast.Expression | None = None
        self._last_error: str = ""
        self._history: dict[str, deque[float]] = {}
        self._avg_exprs: list[tuple[str, ast.AST]] = []

    @property
    def formula(self) -> str:
        return self._formula

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def is_valid(self) -> bool:
        return self._ast_tree is not None and self._formula != ""

    def set_formula(self, formula: str) -> tuple[bool, str]:
        """Parse and validate a formula string.

        Returns (success, error_message).
        """
        formula = formula.strip()
        if formula == self._formula and self.is_valid:
            return True, ""  # the formula it runs: its avg() windows go on (a profile's reload, a rename)
        if not formula:
            self._formula = ""
            self._ast_tree = None
            self._last_error = ""
            return True, ""

        tree, err = _parse(formula)
        if tree is None:
            self._last_error = err
            return False, err

        self._formula = formula
        self._ast_tree = tree
        self._last_error = ""
        self._history.clear()
        self._avg_exprs = _avg_exprs(tree.body)
        return True, ""

    def push_variables(self, variables: dict[str, float]) -> None:
        """Record current tick's variable values into the history buffer.

        Call this once per tick BEFORE evaluate(). Evaluates each avg()
        expression subtree and stores the result.
        """
        for key, expr_node in self._avg_exprs:
            if key not in self._history:
                self._history[key] = deque(maxlen=_MAX_WINDOW)
            self._history[key].append(self._value(expr_node, variables))

    def evaluate(self, variables: dict[str, float]) -> float:
        """The formula's value on this tick's variables, clamped to +-_MAX_RESULT; 0 without a formula."""
        if not self._ast_tree:
            return 0.0
        return max(-_MAX_RESULT, min(self._value(self._ast_tree.body, variables), _MAX_RESULT))

    def _value(self, node: ast.AST, variables: dict[str, float]) -> float:
        """The node's value, or 0 where it has none (a division by zero, a domain error, overflow, a complex result)."""
        try:
            value = self._eval_node(node, variables)
            return value if math.isfinite(value) else 0.0
        except (ZeroDivisionError, ValueError, OverflowError, TypeError, KeyError):
            return 0.0
        except Exception as e:  # noqa: BLE001 - a user's formula never stops the tick: it reads 0
            logger.debug(f"Custom formula eval error: {e}")
            return 0.0

    def _eval_node(self, node: ast.AST, variables: dict[str, float]) -> float:
        """The value of a node the checks allowed."""
        match node:
            case ast.Constant(value=value):
                return float(value)
            case ast.Name(id=name):
                return 0.0 if name in ALLOWED_FUNCTIONS else float(variables.get(name, 0.0))
            case ast.UnaryOp(op=op, operand=operand):
                return _OPERATORS[type(op)](self._eval_node(operand, variables))
            case ast.BinOp():
                return self._eval_binary(node, variables)
            case ast.Call():
                return self._eval_call(node, variables)
            case ast.Compare():
                return self._eval_compare(node, variables)
            case ast.IfExp(test=test, body=body, orelse=orelse):
                return self._eval_node(body if self._eval_node(test, variables) else orelse, variables)
        return 0.0

    def _eval_binary(self, node: ast.BinOp, variables: dict[str, float]) -> float:
        """The operator on both sides' values; a power with an exponent over 100 reads 0."""
        left, right = self._eval_node(node.left, variables), self._eval_node(node.right, variables)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            return 0.0
        return _OPERATORS[type(node.op)](left, right)

    def _eval_call(self, node: ast.Call, variables: dict[str, float]) -> float:
        name = node.func.id
        if name in _WINDOWED_FUNCTIONS:
            return self._eval_windowed(node, variables)
        return float(ALLOWED_FUNCTIONS[name](*(self._eval_node(arg, variables) for arg in node.args)))

    def _eval_compare(self, node: ast.Compare, variables: dict[str, float]) -> float:
        """1 when every link of the chain holds, else 0; the operands after a failed link are not evaluated."""
        left = self._eval_node(node.left, variables)
        for op, comparator in zip(node.ops, node.comparators):
            right = self._eval_node(comparator, variables)
            if not _COMPARISONS[type(op)](left, right):
                return 0.0
            left = right
        return 1.0

    def _eval_windowed(self, node: ast.Call, variables: dict[str, float]) -> float:
        """Evaluate avg(expression, N) using the history buffer."""
        key = ast.dump(node.args[0])
        n = int(node.args[1].value)
        buf = self._history.get(key)
        if not buf:
            return self._eval_node(node.args[0], variables)
        values = list(buf)[-n:]
        if not values:
            return 0.0
        return sum(values) / len(values)


def compile_formula(formula: str) -> tuple[CustomFormulaEvaluator | None, str]:
    """A ready evaluator, or None and why the formula can't run (an empty one can't)."""
    ev = CustomFormulaEvaluator()
    ok, err = ev.set_formula(formula)
    return (ev, "") if ok and ev.is_valid else (None, err or "Empty formula")


def evaluate_series(evaluators: Mapping[str, CustomFormulaEvaluator], metrics: dict,
                    variables: Callable[[], dict[str, float]]) -> None:
    """Write each valid evaluator's value for this tick into `metrics` under its series key; the variables are built
    only when one is valid."""
    valid = [(key, ev) for key, ev in evaluators.items() if ev.is_valid]
    if not valid:
        return
    fvars = variables()
    for key, ev in valid:
        ev.push_variables(fvars)
        metrics[key] = ev.evaluate(fvars)

