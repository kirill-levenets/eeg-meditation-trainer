"""History draws only the session rows on screen (#42): the list is a RecycleView over the shown sessions' data."""

import datetime
from unittest.mock import MagicMock

import pytest
from kivy.base import EventLoop
from kivy.metrics import dp
from kivy.tests.common import UnitTestTouch

import app.ui.app_manager as app_manager
from app.ui.app_manager import EEGMeditationApp
from app.ui.history_screen import HistoryScreen, _checkbox_glyph, _SessionRow


def _sessions(n: int) -> list[dict]:
    # Two sessions per day, newest first, like get_all_sessions returns them.
    day0 = datetime.date(2026, 9, 28)
    return [
        {"id": i, "date_time": f"{day0 - datetime.timedelta(days=i // 2)}T{10 + i % 2}:00:00", "duration": 3600,
         "avg_shamatha": 40 + i % 50, "session_name": f"Session {i}"}
        for i in range(n)
    ]


def _frames(n: int = 10) -> None:
    for _ in range(n):
        EventLoop.idle()


@pytest.fixture
def history():
    from kivy.core.window import Window
    EventLoop.ensure_window()
    h = HistoryScreen()
    Window.add_widget(h)
    _frames()
    yield h
    Window.remove_widget(h)


def _views(h: HistoryScreen) -> dict:
    """sid -> the row widget showing it, for the rows currently laid out."""
    return {v.sid: v for v in h._rv.layout_manager.children if isinstance(v, _SessionRow)}


def _scroll(h: HistoryScreen, scroll_y: float) -> None:
    # Through the effect, as the app does: an assigned scroll_y is overwritten by the effect's next update.
    h._rv.effect_y.reset(h._rv.effect_y.max * scroll_y)
    _frames(4)


def _tap(widget, dx: float = 0.0) -> None:
    x, y = widget.to_window(widget.center_x + dx, widget.center_y)
    touch = UnitTestTouch(x, y)
    touch.touch_down()
    _frames(1)
    touch.touch_up()
    _frames(3)


def _offset_from_top(h: HistoryScreen) -> float:
    rv = h._rv
    return (1 - rv.scroll_y) * (rv.layout_manager.height - rv.height)


# ---- only the rows on screen exist ----


def test_only_the_rows_on_screen_are_widgets(history):
    history.load_sessions(_sessions(1000))
    _frames()
    fit = history._rv.height / dp(56) + 2
    assert len(history._rv.data) == 1000
    assert 0 < len(_views(history)) <= fit
    assert history._date_label.text == "All sessions (1000 sessions)"


@pytest.fixture
def created(monkeypatch):
    """How many row widgets have been built."""
    count = [0]
    init = _SessionRow.__init__

    def counting_init(self, **kwargs):
        count[0] += 1
        init(self, **kwargs)

    monkeypatch.setattr(_SessionRow, "__init__", counting_init)
    return count


def test_scrolling_reuses_the_same_row_widgets(history, created):
    history.load_sessions(_sessions(300))
    _frames()
    for y in (1, 0.8, 0.5, 0.2, 0, 0.6, 1):
        _scroll(history, y)
    # A jump fetches the new rows before it releases the old ones, so up to two screenfuls exist.
    assert created[0] <= 2 * (history._rv.height / dp(56) + 2)


def test_select_mode_and_cancel_create_no_row_widgets(history, created):
    history.load_sessions(_sessions(300))
    _frames()
    built = created[0]
    history.set_select_mode(True)
    _frames()
    rows = list(_views(history).values())
    assert rows and all(v._checkbox.parent is not None and v._actions.parent is None for v in rows)
    history.set_select_mode(False)
    _frames()
    rows = list(_views(history).values())
    assert rows and all(v._checkbox.parent is None and v._actions.parent is not None for v in rows)
    assert created[0] == built


# ---- a reused row shows its own session ----


def _assert_rows_show_their_selection(h: HistoryScreen) -> None:
    for sid, view in _views(h).items():
        assert view._checkbox.text == _checkbox_glyph(sid in h.selected_ids), sid


def test_a_selection_never_shows_on_another_sessions_row(history):
    history.load_sessions(_sessions(300))
    _frames()
    history.set_select_mode(True)
    _frames()
    top = max(_views(history), key=lambda sid: _views(history)[sid].y)
    history.toggle_session_selection(top)
    _frames()
    for y in (1, 0.5, 0, 0.3, 1):
        _scroll(history, y)
        _assert_rows_show_their_selection(history)
    assert history.selected_ids == {top}


def test_a_row_shows_its_sessions_name_after_reuse(history):
    history.load_sessions(_sessions(300))
    _frames()
    for y in (1, 0.4, 0):
        _scroll(history, y)
        for sid, view in _views(history).items():
            assert view._name_label.text.endswith(f" - Session {sid}")


def test_select_all_selects_every_session_in_the_filter_including_rows_never_shown(history):
    history.load_sessions(_sessions(300))
    _frames()
    history.set_select_mode(True)
    history.select_all_shown()
    assert history.selected_ids == set(range(300))
    history.set_select_mode(False)
    history._on_day_tap("2026-09-27")  # sessions 2 and 3
    _frames()
    history.set_select_mode(True)
    history.select_all_shown()
    assert history.selected_ids == {2, 3}


def test_another_profiles_list_drops_the_selection_and_the_same_list_keeps_it(history):
    history.load_sessions(_sessions(10))
    history.set_select_mode(True)
    history.toggle_session_selection(3)
    history.load_sessions(_sessions(10))  # the same profile, reloaded (a notes save marked it dirty)
    assert history.selected_ids == {3}
    other = [dict(s, id=s["id"] + 100) for s in _sessions(4)]
    history.load_sessions(other, keep_filter=False)  # another profile: its sessions only
    assert history.selected_ids == set()
    assert history._btn_export.text == "Export 0" and history._btn_export.disabled


# ---- taps ----


def test_a_tap_on_a_row_opens_its_session(history):
    opened = []
    history._on_session_select = opened.append
    history.load_sessions(_sessions(20))
    _frames()
    sid, view = next(iter(sorted(_views(history).items())))
    _tap(view, dx=-view.width / 4)
    assert opened == [sid]


def test_the_action_strip_renames_and_deletes_its_row(history):
    asked = []
    history._confirm_delete = lambda sid, name: asked.append((sid, name))
    history.load_sessions(_sessions(20))
    _frames()
    sid, view = next(iter(sorted(_views(history).items())))
    _tap(view, dx=view.width / 2 - dp(20))  # the right half of the 80 dp strip: delete
    assert asked == [(sid, view._name_label.text)] and view._name_label.text.endswith(f" - Session {sid}")
    _tap(view, dx=view.width / 2 - dp(60))  # the left half: rename
    _frames()
    assert history._renaming_sid == sid
    assert history._rename_row.parent is _views(history)[sid]


def test_a_tap_in_select_mode_toggles_its_row(history):
    history.load_sessions(_sessions(20))
    _frames()
    history.set_select_mode(True)
    _frames()
    sid, view = next(iter(sorted(_views(history).items())))
    _tap(view)
    assert history.selected_ids == {sid}
    assert view._checkbox.text == _checkbox_glyph(True)
    _tap(view)
    assert history.selected_ids == set()


# ---- rename ----


def test_the_rename_editor_follows_its_session_while_scrolling(history):
    renamed = []
    history._on_rename_session = lambda sid, name: renamed.append((sid, name))
    history.load_sessions(_sessions(300))
    _frames()
    history._toggle_rename(0)
    _frames()
    assert history._rename_row.parent is _views(history)[0]
    assert history._rename_input.focus  # opening it relaid out every row: the keyboard stays
    history._rename_input.text = "Evening sit"
    _scroll(history, 0)
    assert 0 not in _views(history)
    assert history._rename_row.parent is None  # not on another session's row
    assert not history._rename_input.focus  # no keyboard typing into a row that isn't on screen
    _scroll(history, 1)
    assert history._rename_row.parent is _views(history)[0]
    assert history._rename_input.text == "Evening sit"
    history._rename_input.dispatch("on_text_validate")
    _frames()
    assert renamed == [(0, "Evening sit")]
    assert history._sessions[0]["session_name"] == "Evening sit"
    assert _views(history)[0]._name_label.text == "2026-09-28 10:00 - Evening sit"
    assert history._rename_row.parent is None and history._renaming_sid is None
    assert _views(history)[0].height == dp(56)


def test_the_rename_editor_stays_with_its_session_when_a_row_above_is_deleted(history):
    history.load_sessions(_sessions(20))
    _frames()
    history._toggle_rename(3)
    history._rename_input.text = "Evening sit"
    _frames()
    history.remove_sessions([1])  # every row below shifts up one
    _frames()
    views = _views(history)
    assert history._rename_row.parent is views[3]
    assert history._rename_input.text == "Evening sit"
    assert [sid for sid, v in views.items() if v.height > dp(56)] == [3]


def test_a_new_list_closes_the_rename_editor_and_its_keyboard(history):
    history.load_sessions(_sessions(20))
    _frames()
    history._toggle_rename(2)
    _frames()
    assert history._rename_input.focus
    history.load_sessions(_sessions(10))  # e.g. History marked dirty and reloaded
    _frames()
    assert history._renaming_sid is None and history._rename_row.parent is None
    assert not history._rename_input.focus


def test_the_rename_editor_fits_inside_its_row(history):
    # A Save button taller than the editor reached over the row's rename/delete strip, which took those taps.
    history.load_sessions(_sessions(5))
    _frames()
    history._toggle_rename(1)
    _frames()
    row = history._rename_row
    for w in row.walk(restrict=True):
        assert row.y - 0.5 <= w.y and w.top <= row.top + 0.5, (type(w).__name__, w.y, w.top, row.y, row.top)


def test_the_rename_save_label_is_one_line(history):
    from kivy.core.text import Label as CoreLabel

    from app.ui.theme import StyledButton
    history.load_sessions(_sessions(5))
    _frames()
    history._toggle_rename(1)
    _frames()
    save = next(w for w in history._rename_row.children if isinstance(w, StyledButton))
    label = save._label
    one_line = CoreLabel(text=label.text, font_size=label.font_size, bold=label.bold)
    one_line.refresh()
    # The label's texture is its text_size box, so the test is whether the text fits that width on one line.
    assert one_line.texture.size[0] <= label.width, f"'Save' needs {one_line.texture.size[0]} px, has {label.width}"


def test_a_tap_on_the_pencil_opens_the_editor_with_the_keyboard(history):
    history.load_sessions(_sessions(5))
    _frames()
    sid, view = next(iter(sorted(_views(history).items())))
    _tap(view, dx=view.width / 2 - dp(60))
    _frames()
    assert history._rename_row.parent is _views(history)[sid]
    assert history._rename_input.focus


def test_the_row_being_renamed_is_taller_and_the_others_are_not(history):
    history.load_sessions(_sessions(20))
    _frames()
    history._toggle_rename(1)
    _frames()
    heights = {sid: v.height for sid, v in _views(history).items()}
    assert heights[1] > dp(56)
    assert all(h == dp(56) for sid, h in heights.items() if sid != 1)
    history._toggle_rename(1)  # the pencil again closes it
    _frames()
    assert history._renaming_sid is None and _views(history)[1].height == dp(56)


# ---- delete keeps the user's place ----


def test_removing_a_session_below_keeps_the_rows_on_screen_where_they_are(history):
    history.load_sessions(_sessions(300))
    _frames()
    _scroll(history, 0.5)
    offset, shown = _offset_from_top(history), set(_views(history))
    history.remove_sessions([299])
    _frames()
    assert len(history._rv.data) == 299 and 299 not in {d["sid"] for d in history._rv.data}
    assert abs(_offset_from_top(history) - offset) < 1
    assert set(_views(history)) == shown


def test_an_empty_list_shows_the_message_and_no_rows(history):
    history.load_sessions(_sessions(5))
    _frames()
    history.load_sessions([])
    _frames()
    assert history._rv.data == [] and _views(history) == {}
    assert history._empty_label.parent is not None
    history.load_sessions(_sessions(3))
    _frames()
    assert history._empty_label.parent is None and len(_views(history)) == 3


# ---- the app ----


def test_history_loads_without_the_full_screen_spinner(monkeypatch):
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = MagicMock()
    app._history_screen = MagicMock()
    app._current_user_id = 1
    app._view_all_users = False
    app.show_loading = MagicMock()
    monkeypatch.setattr(app_manager, "sessions_for_view", lambda db, uid, show_all: _sessions(3))
    app._refresh_history(force=True)
    app.show_loading.assert_not_called()
    app._history_screen.load_sessions.assert_called_once()
