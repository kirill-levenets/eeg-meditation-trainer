"""Objects under test are built by their real constructors: an app or a flow made with `__new__` has only the parts
a test gave it, so it passes or fails on the test's own wiring instead of the app's."""
import re
from pathlib import Path

BYPASS = re.compile(r"\b__new__\(")


def test_no_test_builds_an_object_with_new():
    here = Path(__file__)
    found = [f"{path.name}:{number}" for path in sorted(here.parent.glob("*.py")) if path != here
             for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if BYPASS.search(line)]
    assert found == [], f"built with __new__ (use fresh_app, build_app or the flow's constructor): {found}"
