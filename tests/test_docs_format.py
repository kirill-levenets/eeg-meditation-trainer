"""Tracked Markdown is one sentence per line: a paragraph on one line makes every edit a whole-paragraph diff."""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAX_LINE = 400  # a sentence or clause; tables and fenced code can't wrap and are exempt
CLAUDE_MD_MAX = 30_000  # loaded into every Claude Code session, with ~/.claude/CLAUDE.md, under a combined cap
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def _markdown_files() -> list[pathlib.Path]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout: the tracked files can't be listed")
    run = subprocess.run(["git", "ls-files", "-z", "--", "*.md"], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return [p for p in (ROOT / name for name in run.stdout.split("\0") if name) if p.is_file()]


def _long_lines(text: str, name: str) -> list[str]:
    """`name:line (length)` for each prose line over MAX_LINE, and an unclosed code fence."""
    long, fence, opened_at = [], None, 0
    for n, line in enumerate(text.split("\n"), 1):
        m = FENCE.match(line)
        if fence is None and m:
            fence, opened_at = m.group(1), n
        elif fence is not None:
            # A fence closes only on its own character, at least as long, with nothing after it.
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
                fence = None
        elif not line.lstrip().startswith("|") and len(line) > MAX_LINE:
            long.append(f"{name}:{n} ({len(line)} characters)")
    if fence is not None:
        long.append(f"{name}:{opened_at} (code fence never closed)")
    return long


@pytest.mark.parametrize("text, found", [
    ("x" * MAX_LINE, False),
    ("x" * (MAX_LINE + 1), True),
    ("| " + "x" * MAX_LINE + " |", False),
    ("```\n" + "x" * (MAX_LINE + 1) + "\n```", False),
    ("```\n" + "x" * (MAX_LINE + 1), True),  # unclosed: the rest of the file isn't checked, so it fails
    ("```\n~~~\n```\n" + "x" * (MAX_LINE + 1), True),  # ~~~ doesn't close a ``` fence
    ("```\n```python\n```\n" + "x" * (MAX_LINE + 1), True),  # an info string opens, it doesn't close
    ("````\n```\n" + "x" * (MAX_LINE + 1) + "\n```\n````", False),  # a longer fence holds a shorter one
], ids=["at-cap", "over-cap", "table", "fenced", "unclosed-fence", "other-fence-char", "info-string", "nested"])
def test_the_line_check_reads_markdown_structure(text, found):
    assert bool(_long_lines(text, "t.md")) is found


def test_no_tracked_markdown_prose_line_over_the_cap():
    files = _markdown_files()
    assert ROOT / "CLAUDE.md" in files  # the listing found the repo's docs
    long = [hit for p in files for hit in _long_lines(p.read_text(encoding="utf-8"), str(p.relative_to(ROOT)))]
    assert not long, "one sentence per line, a long one broken at its clauses (; : —):\n" + "\n".join(long)


def test_claude_md_stays_under_its_cap():
    size = len((ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
    assert size <= CLAUDE_MD_MAX, f"CLAUDE.md is {size} characters: move explanations to docs/architecture/"
