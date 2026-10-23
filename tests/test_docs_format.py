"""Markdown is one sentence per line: a paragraph on one line makes every edit a whole-paragraph diff."""
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAX_LINE = 400  # a sentence or clause; tables and fenced code can't wrap and are exempt
CLAUDE_MD_MAX = 30_000  # loaded into every Claude Code session, with ~/.claude/CLAUDE.md, under a combined cap
FENCE = re.compile(r"^\s*(```|~~~)")


def _markdown_files() -> list[pathlib.Path]:
    out = subprocess.run(["git", "ls-files", "-z", "--", "*.md"], cwd=ROOT, capture_output=True, check=True).stdout
    return [ROOT / name for name in out.decode().split("\0") if name]


def _long_lines(path: pathlib.Path) -> list[str]:
    long, fence = [], False
    for n, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if FENCE.match(line):
            fence = not fence
        elif not fence and not line.lstrip().startswith("|") and len(line) > MAX_LINE:
            long.append(f"{path.relative_to(ROOT)}:{n} ({len(line)} characters)")
    return long


def test_markdown_lines_are_a_sentence_or_clause_each():
    files = _markdown_files()
    assert any(p.name == "CLAUDE.md" for p in files)  # the listing found the repo's docs
    long = [hit for p in files for hit in _long_lines(p)]
    assert not long, f"one sentence per line, a long one broken at its clauses (; : —): {long}"


def test_claude_md_stays_under_its_cap():
    size = len((ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
    assert size <= CLAUDE_MD_MAX, f"CLAUDE.md is {size} characters: move explanations to docs/architecture/"
