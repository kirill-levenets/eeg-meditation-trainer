"""Deleting or renaming a session updates History in place: no rebuild, no spinner, the user's place is kept (#56)."""

from unittest.mock import MagicMock

import pytest

from app.ui.app_manager import EEGMeditationApp
from app.ui.history_screen import HistoryScreen


def _sessions(n: int) -> list[dict]:
    # Two sessions per day, newest first, like get_all_sessions returns them.
    return [
        {"id": i, "date_time": f"2026-09-{28 - i // 2:02d}T{10 + i % 2}:00:00", "duration": 3600,
         "avg_shamatha": 40 + i, "session_name": f"Session {i}"}
        for i in range(n)
    ]


def _listed(h: HistoryScreen) -> dict:
    """sid -> its item in the list's data."""
    return {d["sid"]: d for d in h._rv.data}


def _loaded(n: int) -> HistoryScreen:
    h = HistoryScreen()
    h.load_sessions(_sessions(n))
    return h


def test_removing_a_session_drops_only_its_item():
    h = _loaded(12)
    before = _listed(h)
    h.remove_sessions([5])
    after = _listed(h)
    assert set(after) == set(before) - {5}
    assert all(after[sid] == before[sid] for sid in after)  # every other session's item is unchanged
    assert h._date_label.text == "All sessions (11 sessions)"
    assert 5 not in [s["id"] for s in h._sessions]


def test_removing_a_session_updates_the_calendar_and_bars():
    h = _loaded(6)  # days 28, 27, 26 with two sessions each
    h.remove_sessions([4, 5])  # both sessions of 2026-09-26
    assert "2026-09-26" not in h._heatmap._day_values
    assert "2026-09-26" not in h._bars._day_values
    assert h._heatmap._day_values["2026-09-28"] == (40 + 41) / 2


def test_removing_inside_a_day_filter_keeps_the_filter():
    h = _loaded(6)
    h._on_day_tap("2026-09-27")  # sessions 2 and 3
    h.remove_sessions([2])
    assert h._filtered_date == "2026-09-27"
    assert set(_listed(h)) == {3}
    assert h._date_label.text.endswith("(1 sessions)")
    h.remove_sessions([3])
    assert h._filtered_date == "2026-09-27"
    assert _listed(h) == {}
    assert h._date_label.text.endswith("(0 sessions)")


def test_removing_a_selected_session_drops_it_from_the_selection():
    h = _loaded(4)
    h.set_select_mode(True)
    h.toggle_session_selection(1)
    h.toggle_session_selection(2)
    h.remove_sessions([1])
    assert h.selected_ids == {2}


def _frames(n: int = 10) -> None:
    from kivy.base import EventLoop
    for _ in range(n):
        EventLoop.idle()


@pytest.mark.parametrize("start", ["flung past the bottom", "drifting after a scroll"])
def test_a_full_rebuild_starts_at_the_top(start):
    from kivy.base import EventLoop
    from kivy.core.window import Window
    EventLoop.ensure_window()
    h = HistoryScreen()
    Window.add_widget(h)
    try:
        h.load_sessions(_sessions(40))
        _frames(20)
        sv = h._rv
        if start == "flung past the bottom":
            sv.effect_y.value = sv.effect_y.min + 300  # overscrolled and still moving
            sv.effect_y.velocity = -900.0
        else:
            sv.effect_y.value = (sv.effect_y.min + sv.effect_y.max) / 2 + 0.4  # mid-list, a slow tail of momentum
            sv.effect_y.velocity = -20.0
        _frames(2)
        h.load_sessions(_sessions(39))
        _frames(20)
        assert sv.scroll_y == 1 and abs(sv.effect_y.velocity) < 1 and sv.effect_y.overscroll == 0
    finally:
        Window.remove_widget(h)


def _bare_scroll(content_height: float):
    from kivy.uix.widget import Widget

    from app.ui.history_screen import _StableScrollView
    sv = _StableScrollView(size=(300, 400))
    content = Widget(size_hint_y=None, height=content_height)
    sv.add_widget(content)
    sv._update_effect_y_bounds()
    return sv, content


def test_an_overscroll_is_not_rescaled_when_the_list_grows():
    sv, content = _bare_scroll(1000)
    sv.scroll_y = -0.5  # an overscroll fraction, as a fling past the bottom leaves it
    content.height = 20000  # rows keep arriving
    sv._update_effect_y_bounds()
    lo, hi = sorted((sv.effect_y.min, sv.effect_y.max))
    assert 0 <= sv.scroll_y <= 1
    assert lo <= sv.effect_y.value <= hi


def test_rows_arriving_keep_the_view_where_it_is():
    sv, content = _bare_scroll(1000)  # 600 px of travel
    sv.scroll_y = 0.5
    sv._update_effect_y_bounds()
    assert sv.effect_y.value - sv.effect_y.max == 300  # 300 px below the top
    content.height = 2000
    sv._update_effect_y_bounds()
    assert sv.effect_y.value - sv.effect_y.max == 300  # still the same rows on screen


def test_an_edge_bounce_survives_a_touch_when_the_list_does_not_change():
    sv, _content = _bare_scroll(1000)
    sv.scroll_y = 1.128  # pulled past the top, springing back
    sv._update_effect_y_bounds()  # what every touch-down and release does
    assert sv.scroll_y == 1.128


def test_a_day_tap_highlights_the_day_in_both_views_and_reset_clears_both():
    h = _loaded(6)
    h._on_day_tap("2026-09-27")
    assert h._heatmap._selected_date == h._bars._selected_date == "2026-09-27"
    assert h._btn_show_all.opacity == 1 and not h._btn_show_all.disabled
    h._reset_filter()
    assert h._heatmap._selected_date is None and h._bars._selected_date is None
    assert h._btn_show_all.opacity == 0 and h._btn_show_all.disabled


def test_a_reload_for_another_view_clears_the_day_filter():
    h = _loaded(6)
    h._on_day_tap("2026-09-27")
    h.load_sessions(_sessions(4), keep_filter=False)  # another profile, or the All-Users view
    assert h._filtered_date is None and h._heatmap._selected_date is None and h._bars._selected_date is None
    assert h._date_label.text == "All sessions (4 sessions)"
    assert h._btn_show_all.disabled


def test_history_keeps_the_day_filter_only_for_the_same_profile_and_view():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = MagicMock()
    app._history_screen = MagicMock()
    app.show_loading = MagicMock()
    app.hide_loading = MagicMock()
    app._view_all_users = False
    keeps = []
    for uid in (1, 1, 2, 2):
        app._current_user_id = uid
        app._refresh_history(force=True)
        keeps.append(app._history_screen.load_sessions.call_args.kwargs["keep_filter"])
    assert keeps == [False, True, False, True]



def test_renaming_updates_the_row_and_the_model_in_place():
    h = _loaded(3)
    renamed = []
    h._on_rename_session = lambda sid, name: renamed.append((sid, name))
    h._toggle_rename(1)
    h._rename_input.text = "Evening sit"
    h._rename_input.dispatch("on_text_validate")
    assert renamed == [(1, "Evening sit")]
    assert next(s for s in h._sessions if s["id"] == 1)["session_name"] == "Evening sit"
    assert _listed(h)[1]["name"] == "2026-09-28 11:00 - Evening sit"


# --- the app: one delete path, no rebuild of History or the hidden diary list -------------------------------

def _app() -> EEGMeditationApp:
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = MagicMock()
    app._history_screen = MagicMock()
    for name in ("_refresh_history", "show_loading"):
        setattr(app, name, MagicMock())
    return app


def test_deleting_sessions_removes_their_rows_and_rebuilds_nothing():
    app = _app()
    app._delete_sessions([7, 9])
    assert [c.args[0] for c in app._db.delete_session.call_args_list] == [7, 9]
    app._history_screen.remove_sessions.assert_called_once_with([7, 9])
    app._refresh_history.assert_not_called()
    app.show_loading.assert_not_called()


def test_renaming_a_session_rebuilds_nothing():
    app = _app()
    app._on_rename_session(7, "Evening sit")
    app._db.rename_session.assert_called_once_with(7, "Evening sit")
    app._refresh_history.assert_not_called()



# --- review round: the model always matches the list on screen; reloads keep the user's view ------------------

def test_an_empty_list_does_not_keep_the_previous_sessions_behind_it():
    h = _loaded(5)
    h.load_sessions([])  # e.g. a profile with no sessions
    assert h._shown == []
    h.set_select_mode(True)
    assert _listed(h) == {}
    h.select_all_shown()
    assert h.selected_ids == set()


def test_removing_from_an_empty_day_keeps_its_zero_count():
    h = _loaded(6)
    h._on_day_tap("2026-08-01")  # a calendar day with no sessions
    h.remove_sessions([3])
    assert h._date_label.text.endswith("(0 sessions)")


def test_removing_selected_sessions_updates_the_export_button():
    h = _loaded(4)
    h.set_select_mode(True)
    h.toggle_session_selection(1)
    h.toggle_session_selection(2)
    h.remove_sessions([1, 2])
    assert h._btn_export.text == "Export 0" and h._btn_export.disabled


def test_a_new_build_cancels_the_previous_builds_settled_log():
    h = _loaded(4)
    settled = h._settled_log_ev
    assert settled is not None and settled.is_triggered
    h.load_sessions(_sessions(4))
    assert not settled.is_triggered


def test_a_reload_keeps_the_active_day_filter():
    h = _loaded(6)
    h._on_day_tap("2026-09-27")
    h.load_sessions(_sessions(6))  # e.g. History marked dirty by a notes save, rebuilt on return
    assert h._filtered_date == "2026-09-27"
    assert set(_listed(h)) == {2, 3}
    assert h._date_label.text.startswith("September 27, 2026")


def test_picking_a_profile_marks_history_for_a_rebuild():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = MagicMock()
    app._load_user_settings = MagicMock()
    app._history_dirty = False
    app._activate_user(2)
    assert app._history_dirty is True


def test_deleting_another_profile_marks_history_for_a_rebuild():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = MagicMock()
    app._db.get_all_users.return_value = [{"id": 1}]
    app._current_user_id = 1
    app._refresh_profile = MagicMock()
    app._history_dirty = False
    app._on_user_delete(2)
    app._db.delete_user.assert_called_once_with(2)
    assert app._history_dirty is True
