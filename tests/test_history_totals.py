"""History's totals table: Day, Week and Month rows around the tapped day (today when none is) and an All time row, with
each period's total time, time on target and best streak; under the chart on a phone held upright, beside it held
sideways."""

import datetime
from types import SimpleNamespace

import pytest
from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.tests.common import UnitTestTouch

from app.session.manager import SessionManager
from app.settings.registry import BOOL, Setting, SettingsStore
from app.storage.database import DatabaseManager
from app.ui import history_screen, theme
from app.ui.app_manager import EEGMeditationApp
from app.ui.history_screen import HistoryScreen
from app.ui.theme import Icons

TODAY = datetime.date(2026, 10, 7)  # a Wednesday


def _s(sid: int, when: str, duration: int, on_target: int, streak: int) -> dict:
    return {"id": sid, "date_time": when, "duration": duration, "time_above_threshold": on_target,
            "longest_streak": streak, "avg_shamatha": 60, "session_name": f"Session {sid}"}


SESSIONS = [  # newest first, as get_all_sessions returns them
    _s(2, "2026-10-07T20:00:00", 600, 100, 50),
    _s(1, "2026-10-07T06:00:00", 1200, 300, 120),
    _s(3, "2026-10-05T06:00:00", 1800, 900, 400),   # Monday, the same week
    _s(4, "2026-10-01T06:00:00", 2400, 600, 200),   # the week before, the same month
    _s(5, "2026-09-28T06:00:00", 3600, 1200, 600),  # the week before, the month before
]


@pytest.fixture
def history(monkeypatch):
    monkeypatch.setattr(history_screen, "_today", lambda: TODAY)
    EventLoop.ensure_window()
    h = HistoryScreen()
    Window.add_widget(h)
    for _ in range(4):
        EventLoop.idle()
    h.load_sessions([dict(s) for s in SESSIONS])
    yield h
    Window.remove_widget(h)


def _table(h: HistoryScreen) -> list[list[str]]:
    return [[cell.text for cell in row] for row in h._totals_rows]


def test_the_header_names_the_columns(history):
    assert [cell.text for cell in history._totals_header] == ["", "Total", "On target", "Best streak"]


def test_with_no_day_tapped_the_rows_are_todays(history):
    assert _table(history) == [
        ["Wed 7 Oct", "30m 00s", "6m 40s", "2m 00s"],
        ["5 – 11 Oct", "1h 00m", "21m 40s", "6m 40s"],
        ["October", "1h 40m", "31m 40s", "6m 40s"],
        ["All time", "2h 40m", "51m 40s", "10m 00s"],
    ]


def test_a_tapped_day_moves_the_rows_and_tapping_it_again_goes_back_to_today(history):
    history._on_day_tap("2026-10-01")
    assert _table(history) == [
        ["Thu 1 Oct", "40m 00s", "10m 00s", "3m 20s"],
        ["28 Sep – 4 Oct", "1h 40m", "30m 00s", "10m 00s"],
        ["October", "1h 40m", "31m 40s", "6m 40s"],
        ["All time", "2h 40m", "51m 40s", "10m 00s"],  # the same whichever day is tapped
    ]
    history._on_day_tap("2026-10-01")  # the same day again clears the filter
    assert _table(history)[0][0] == "Wed 7 Oct"


def test_show_all_goes_back_to_today(history):
    history._on_day_tap("2026-10-01")
    history._reset_filter()
    assert _table(history)[0][0] == "Wed 7 Oct"


def test_a_period_without_sessions_shows_dashes(history):
    history._on_day_tap("2026-10-06")
    assert _table(history)[0] == ["Tue 6 Oct", "–", "–", "–"]


def test_deleting_a_session_updates_the_totals(history):
    history.remove_sessions([2])
    assert _table(history)[0] == ["Wed 7 Oct", "20m 00s", "5m 00s", "2m 00s"]
    assert _table(history)[3] == ["All time", "2h 30m", "50m 00s", "10m 00s"]


def test_no_sessions_at_all_shows_dashes_for_all_time(history):
    history.load_sessions([])
    assert _table(history)[3] == ["All time", "–", "–", "–"]


def test_a_reload_updates_the_totals_and_keeps_the_tapped_day(history):
    history._on_day_tap("2026-10-01")
    history.load_sessions([dict(s) for s in SESSIONS if s["id"] != 4], keep_filter=True)
    assert _table(history)[0] == ["Thu 1 Oct", "–", "–", "–"]


def test_upright_the_table_is_under_the_chart_and_sideways_beside_it(history):
    h = history
    h._root.width = dp(360)
    h._place_totals()
    order = list(reversed(h._chart_area.children))
    assert h._totals.parent is h._chart_area and order == [h._graph_row, h._totals]
    h._root.width = dp(640)  # a narrower phone held sideways: the heatmap wouldn't fit beside the table
    h._place_totals()
    assert h._totals.parent is h._chart_area
    h._root.width = dp(732)
    h._place_totals()
    assert h._totals.parent is h._graph_row
    assert list(reversed(h._graph_row.children)) == [h._graph_wrap, h._totals, h._toggle_col]
    h._root.width = dp(360)
    h._place_totals()
    assert h._totals.parent is h._chart_area


def test_opening_history_on_another_day_moves_today_on(history, monkeypatch):
    # The list was loaded before midnight and the app stayed open: entering History shows the new day.
    monkeypatch.setattr(history_screen, "_today", lambda: datetime.date(2026, 10, 12))  # the next Monday
    history.on_pre_enter()
    assert _table(history)[0][0] == "Mon 12 Oct"
    assert "2026-10-12" in history._heatmap._cell_positions  # the calendar reaches the new day's week too


def test_opening_history_on_the_same_day_redraws_nothing(history, monkeypatch):
    calls = []
    monkeypatch.setattr(history._heatmap, "set_data", lambda data: calls.append(data))
    history.on_pre_enter()
    assert calls == []


# ---- folding the chart and the totals away ----


def _tap(widget) -> None:
    x, y = widget.to_window(widget.center_x, widget.center_y)
    touch = UnitTestTouch(x, y)
    touch.touch_down()
    touch.touch_up()
    for _ in range(3):
        EventLoop.idle()


def test_the_chart_folds_away_and_the_list_gets_its_room(history):
    h = history
    for _ in range(5):
        EventLoop.idle()
    list_h = h._rv.height
    h.set_chart_collapsed(True)
    for _ in range(5):
        EventLoop.idle()
    assert h.chart_collapsed and h._chart_area.parent is None  # detached: nothing hidden in place can take taps
    assert h._rv.height > list_h + h._graph_row.height * 0.9
    assert h._btn_collapse._icon_label.text == Icons.CHEVRON_RIGHT
    h.set_chart_collapsed(False)
    order = list(reversed(h._root.children))
    assert order.index(h._chart_area) == order.index(h._title_row) + 1
    assert h._btn_collapse._icon_label.text == Icons.CHEVRON_DOWN


def test_tapping_the_chevron_folds_and_unfolds_and_reports_it(history):
    states = []
    history.set_chart_collapse_callback(states.append)
    _tap(history._btn_collapse)
    assert history.chart_collapsed and states == [True]
    _tap(history._btn_collapse)
    assert not history.chart_collapsed and states == [True, False]


def test_folding_keeps_the_tapped_day(history):
    history._on_day_tap("2026-10-01")
    history.set_chart_collapsed(True)
    assert history._filtered_date == "2026-10-01" and len(history._shown) == 1
    history.set_chart_collapsed(False)
    assert _table(history)[0][0] == "Thu 1 Oct"


def test_folded_sideways_and_turned_upright_the_table_stays_with_the_chart(history):
    h = history
    h._root.width = dp(732)
    h._place_totals()
    h.set_chart_collapsed(True)
    h._root.width = dp(360)
    h._place_totals()
    assert h._totals.parent is h._chart_area and h._chart_area.parent is None
    h.set_chart_collapsed(False)
    assert h._chart_area.parent is h._root


def test_the_folded_chart_is_saved_per_profile(history, tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    try:
        me, other = db.create_user("me"), db.create_user("other")
        a = EEGMeditationApp.__new__(EEGMeditationApp)
        a._db, a._current_user_id, a._loading_settings = db, me, False
        a._history_screen = history
        # As _build_settings_store declares it, and as build() wires the chevron.
        a._settings_store = SettingsStore(db, [Setting("history_chart_collapsed", False, BOOL[0], BOOL[1],
                                                       lambda: history.chart_collapsed, history.set_chart_collapsed)])
        history.set_chart_collapse_callback(lambda _c: a._persist_user_setting("history_chart_collapsed"))
        history._toggle_chart()  # "me" folds it
        assert db.get_user_setting(me, "history_chart_collapsed") == "True"
        a._settings_store.load(other)
        assert not history.chart_collapsed  # the other profile's own state
        a._settings_store.load(me)
        assert history.chart_collapsed
    finally:
        db.close()


def test_without_the_icon_font_the_chevron_says_hide_and_show(monkeypatch):
    monkeypatch.setattr(history_screen, "ICONS_AVAILABLE", False)
    monkeypatch.setattr(theme, "ICONS_AVAILABLE", False)
    h = HistoryScreen()
    assert h._btn_collapse.text == "Hide"
    h.set_chart_collapsed(True)
    assert h._btn_collapse.text == "Show"


def test_resuming_onto_history_moves_today_on(history, monkeypatch):
    a = EEGMeditationApp.__new__(EEGMeditationApp)
    a._sm = SimpleNamespace(current="history")
    a._history_screen = history
    a._session_manager = SessionManager()
    monkeypatch.setattr(history_screen, "_today", lambda: datetime.date(2026, 10, 12))
    a._refresh_ui_after_resume()
    assert _table(history)[0][0] == "Mon 12 Oct"
