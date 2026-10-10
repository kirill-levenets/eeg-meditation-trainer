"""A count reads with its noun, singular for one: "1 session", never "1 sessions"."""

import ast
import re
from pathlib import Path

from kivy.base import EventLoop

from app.ui.history_screen import HistoryScreen
from app.ui.theme import format_count
from app.ui.widgets.user_picker import UserPickerForm


def _session(sid: int, day: str) -> dict:
    return {"id": sid, "date_time": f"{day}T07:30:00", "duration": 600, "avg_shamatha": 60, "session_name": "Mock",
            "notes": ""}


def test_a_count_takes_the_singular_for_one():
    assert [format_count(n, "session") for n in (0, 1, 2)] == ["0 sessions", "1 session", "2 sessions"]


def test_historys_heading_counts_one_session_as_one():
    history = HistoryScreen()
    history.load_sessions([_session(1, "2026-10-03"), _session(2, "2026-10-04")])
    EventLoop.idle()
    assert history._date_label.text == "All sessions (2 sessions)"
    history._on_day_tap("2026-10-03")
    EventLoop.idle()
    assert history._date_label.text.endswith("(1 session)")


def test_a_profile_with_one_session_says_so():
    form = UserPickerForm(on_create=lambda _name: None, on_pick_existing=lambda _uid: None, on_count=lambda _uid: 1)
    form.populate_users([{"id": 1, "name": "Mock"}])
    assert "Mock (1 session)" in [getattr(w, "text", "") for w in form._existing_list.walk()]


APP_UI = Path(__file__).resolve().parents[1] / "app" / "ui"
HEDGED = re.compile(r"[A-Za-z]\(s\)")
PLURAL_AFTER_COUNT = re.compile(r"\s+(sessions|profiles|devices|segments|formulas|files|markers|headsets)\b")


def _hand_made_plurals(tree: ast.AST) -> list[int]:
    """Lines of a text with 'noun(s)', or of an f-string putting a plural noun right after a value."""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and HEDGED.search(node.value):
            lines.append(node.lineno)
        elif isinstance(node, ast.JoinedStr):
            lines += [text.lineno for value, text in zip(node.values, node.values[1:])
                      if isinstance(value, ast.FormattedValue) and isinstance(text, ast.Constant)
                      and PLURAL_AFTER_COUNT.match(text.value)]
    return lines


def test_no_ui_text_counts_with_a_hand_made_plural():
    """'1 session(s)' and '1 sessions' both misread one: a count's noun goes through format_count."""
    found = [f"{path.name}:{line}" for path in sorted(APP_UI.rglob("*.py"))
             for line in _hand_made_plurals(ast.parse(path.read_text()))]
    assert APP_UI.is_dir() and found == []
