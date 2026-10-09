"""Paging the History chart back in time (#44): the arrows and a sideways swipe move one period that both views share;
a tap still picks a day, now on the lift, so a swipe that starts on a day picks nothing."""

import datetime

import pytest
from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.tests.common import UnitTestTouch

import app.ui.history_screen as history_screen
from app.ui.history_screen import (
    CalendarHeatmap,
    HistoryScreen,
    Last14DaysBars,
    period_text,
)

TODAY = datetime.date(2026, 10, 9)  # a Friday
DAY = datetime.timedelta(days=1)


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(history_screen, "_today", lambda: TODAY)


def _sessions(*days: str) -> list[dict]:
    return [{"id": i, "date_time": f"{day}T10:00:00", "duration": 600, "avg_shamatha": 50, "session_name": f"S{i}"}
            for i, day in enumerate(days)]


def _screen(*days: str, mode: str = "bars") -> HistoryScreen:
    h = HistoryScreen()
    h.set_view_mode(mode)
    h.load_sessions(_sessions(*days))
    return h


# ---- the windows ----


def test_the_bars_show_fourteen_days_ending_at_the_period_end():
    assert Last14DaysBars.window(TODAY) == (datetime.date(2026, 9, 26), TODAY)


def test_the_calendar_shows_eighteen_weeks_up_to_today_and_a_past_pages_last_week_whole():
    assert CalendarHeatmap.window(TODAY) == (datetime.date(2026, 6, 8), TODAY)
    assert CalendarHeatmap.window(datetime.date(2026, 6, 5)) == (datetime.date(2026, 2, 2), datetime.date(2026, 6, 7))


@pytest.mark.parametrize("mode, chart", [("bars", Last14DaysBars), ("calendar", CalendarHeatmap)])
def test_consecutive_pages_meet_without_a_gap_or_an_overlap(mode, chart):
    h = _screen("2024-01-05", mode=mode)
    start, _ = chart.window(h.period_end)
    for _ in range(5):
        h.shift_period(-1)
        earlier_start, earlier_last = chart.window(h.period_end)
        assert earlier_last + DAY == start
        start = earlier_start


def test_each_chart_draws_its_window():
    h = _screen("2025-01-05", mode="bars")
    h.shift_period(-1)
    assert sorted(h._bars._cell_positions) == [(datetime.date(2026, 9, 12) + i * DAY).isoformat() for i in range(14)]
    h.set_view_mode("calendar")
    days = sorted(h._heatmap._cell_positions)
    assert (days[0], days[-1]) == ("2026-05-25", "2026-09-27")  # 18 whole weeks ending on Sep 25's Sunday


# ---- paging ----


def test_paging_steps_by_the_shown_views_window():
    h = _screen("2024-01-05", mode="bars")
    h.shift_period(-1)
    assert h.period_end == TODAY - 14 * DAY
    h.set_view_mode("calendar")
    h.shift_period(-1)
    assert h.period_end == TODAY - 14 * DAY - 18 * 7 * DAY
    h.shift_period(1)
    assert h.period_end == TODAY - 14 * DAY


def test_paging_forward_stops_at_today():
    h = _screen("2024-01-05")
    assert h._btn_next.disabled
    h.shift_period(-1)
    assert not h._btn_next.disabled
    h.shift_period(1)
    assert h.period_end == TODAY and h._btn_next.disabled
    h.shift_period(1)
    assert h.period_end == TODAY


def test_a_forward_page_past_today_lands_on_today():
    h = _screen("2024-01-05", mode="calendar")
    h.shift_period(-1)
    h.set_view_mode("bars")
    h.shift_period(1)  # 14 days on from 18 weeks back: still in the past
    h.set_view_mode("calendar")
    h.shift_period(1)  # 18 weeks on from there would be past today
    assert h.period_end == TODAY


def test_paging_back_stops_once_the_first_session_is_shown():
    h = _screen("2026-09-01")
    h.shift_period(-1)  # Sep 12 - Sep 25: the first session is still earlier
    assert not h._btn_prev.disabled
    h.shift_period(-1)  # Aug 29 - Sep 11 holds it
    assert h.period_end == datetime.date(2026, 9, 11) and h._btn_prev.disabled
    h.shift_period(-1)
    assert h.period_end == datetime.date(2026, 9, 11)


def test_a_first_session_on_a_pages_first_day_ends_the_paging_there():
    h = _screen("2026-09-12")
    h.shift_period(-1)  # Sep 12 - Sep 25
    assert h._btn_prev.disabled


def test_with_no_sessions_there_is_nothing_to_page_to():
    h = _screen()
    assert h._btn_prev.disabled and h._btn_next.disabled
    h.shift_period(-1)
    assert h.period_end == TODAY


def test_switching_views_keeps_the_period():
    h = _screen("2024-01-05", mode="bars")
    h.shift_period(-1)
    h.set_view_mode("calendar")
    assert h.period_end == TODAY - 14 * DAY
    assert CalendarHeatmap.window(h.period_end)[1] == datetime.date(2026, 9, 27)
    assert max(h._heatmap._cell_positions) == "2026-09-27"


def test_another_profile_starts_at_today_and_a_reload_keeps_the_page():
    h = _screen("2024-01-05")
    h.shift_period(-1)
    h.load_sessions(_sessions("2024-01-05", "2026-10-01"))  # the same view reloaded (a delete, a new session)
    assert h.period_end == TODAY - 14 * DAY
    h.load_sessions(_sessions("2025-03-01"), keep_filter=False)
    assert h.period_end == TODAY and h._btn_next.disabled


def test_the_shown_period_follows_the_day(monkeypatch):
    h = _screen("2024-01-05")
    monkeypatch.setattr(history_screen, "_today", lambda: TODAY + DAY)
    h.dispatch("on_pre_enter")
    assert h.period_end == TODAY + DAY
    assert max(h._bars._cell_positions) == (TODAY + DAY).isoformat()


def test_a_paged_chart_stays_as_many_pages_back_when_the_day_moves_on(monkeypatch):
    h = _screen("2024-01-05", mode="bars")
    h.shift_period(-1)  # Sep 12 - Sep 25
    monkeypatch.setattr(history_screen, "_today", lambda: TODAY + DAY)
    h.dispatch("on_pre_enter")
    assert Last14DaysBars.window(h.period_end)[1] + DAY == Last14DaysBars.window(TODAY + DAY)[0]
    h.shift_period(1)
    assert h.period_end == TODAY + DAY and h._btn_next.disabled


def test_pages_turned_after_midnight_still_meet_todays_later(monkeypatch):
    h = _screen("2024-01-05", mode="bars")  # loaded today
    monkeypatch.setattr(history_screen, "_today", lambda: TODAY + DAY)  # History stays open past midnight
    h.shift_period(-1)
    monkeypatch.setattr(history_screen, "_today", lambda: TODAY + 3 * DAY)
    h.dispatch("on_pre_enter")
    assert Last14DaysBars.window(h.period_end)[1] + DAY == Last14DaysBars.window(TODAY + 3 * DAY)[0]


def test_only_the_shown_chart_draws(monkeypatch):
    h = _screen("2024-01-05", mode="bars")
    drawn = []
    monkeypatch.setattr(h._heatmap, "_draw", lambda: drawn.append("calendar"))
    h.shift_period(-1)
    h._on_day_tap("2026-09-20")
    assert drawn == []
    h.set_view_mode("calendar")
    assert drawn  # shown again, it draws


def test_a_chart_shown_again_draws_the_period_that_moved_while_it_was_hidden():
    """Upright on a narrow phone the calendar keeps its smallest cells, as tall as the bars: a chart shown again lands
    where it was, and no change of size or place redraws it."""
    h = _screen("2024-01-05", mode="bars")
    h._root.width = dp(360)
    h._place_totals()
    h._cascade_layout()
    h.shift_period(-1)
    h.set_view_mode("calendar")
    assert h._heatmap.height == h._bars.height
    h.shift_period(-1)  # the bars are off screen
    h.set_view_mode("bars")
    first, last = Last14DaysBars.window(h.period_end)
    assert (min(h._bars._cell_positions), max(h._bars._cell_positions)) == (first.isoformat(), last.isoformat())


def test_the_bars_keep_their_labels_inside_off_the_arrow_row_above():
    h = _screen("2026-10-08", mode="bars")
    h._sessions[0]["avg_shamatha"] = 100  # a bar to the top: its score label sits over it
    h._set_day_data()
    labels = [w for w in h._bars.children if w.text]
    assert any(w.text == "100" for w in labels)
    assert all(w.top <= h._bars.top + 0.5 for w in labels)


# ---- the label ----


def test_the_label_names_the_shown_days():
    h = _screen("2024-01-05", mode="bars")
    assert h._period_label.text == "26 Sep – 9 Oct"  # day first, as the totals' week row under it
    h.set_view_mode("calendar")
    assert h._period_label.text == "8 Jun – 9 Oct"
    h.set_view_mode("bars")
    for _ in range(26):  # 364 days back
        h.shift_period(-1)
    assert h._period_label.text == "27 Sep – 10 Oct 2025"


def test_a_period_across_new_year_names_both_years():
    assert period_text(datetime.date(2025, 12, 27), datetime.date(2026, 1, 9)) == "27 Dec 2025 – 9 Jan 2026"
    assert period_text(datetime.date(2026, 10, 5), datetime.date(2026, 10, 11)) == "5 – 11 Oct"


def test_the_label_goes_back_to_today():
    h = _screen("2024-01-05")
    h.shift_period(-1)
    h.shift_period(-1)
    h._period_label.dispatch("on_release")
    assert h.period_end == TODAY and h._btn_next.disabled


# ---- touches, in a real window ----


def _frames(n: int = 4) -> None:
    for _ in range(n):
        EventLoop.idle()


@pytest.fixture
def window_history():
    EventLoop.ensure_window()
    h = HistoryScreen()
    Window.add_widget(h)
    _frames(10)
    yield h
    Window.remove_widget(h)


def _cell_center(chart, day: str) -> tuple[float, float]:
    x, y, w, h = chart._cell_positions[day]
    return chart.to_window(x + w / 2, y + h / 2)


def _gesture(start: tuple[float, float], dx: float = 0.0, dy: float = 0.0) -> None:
    touch = UnitTestTouch(*start)
    touch.touch_down()
    _frames(1)
    if dx or dy:
        for step in (0.5, 1.0):
            touch.touch_move(start[0] + dx * step, start[1] + dy * step)
            _frames(1)
    touch.touch_up()
    _frames(2)


def _tap(widget) -> None:
    _gesture(widget.to_window(widget.center_x, widget.center_y))


@pytest.fixture
def paged_bars(window_history):
    h = window_history
    h.set_view_mode("bars")
    h.load_sessions(_sessions("2024-01-05", "2026-09-20", "2026-10-05"))
    _frames()
    return h


def test_a_new_screen_names_todays_period():
    assert HistoryScreen()._period_label.text == "8 Jun – 9 Oct"


@pytest.mark.parametrize("mode", ["calendar", "bars"])
def test_upright_the_arrow_row_sits_over_the_chart(window_history, mode):
    h = window_history
    h.set_view_mode(mode)
    h._root.width = dp(360)
    h._place_totals()
    h._cascade_layout()
    chart = h._active_chart()
    assert h._period_row.parent is h._graph_wrap and h._totals.parent is h._chart_area
    assert h._graph_row.height == pytest.approx(chart.height + h._PERIOD_H)
    assert h._period_row.y == pytest.approx(chart.top)


@pytest.mark.parametrize("mode", ["calendar", "bars"])
def test_sideways_the_arrow_row_takes_the_room_over_the_table_beside_the_chart(window_history, mode):
    h = window_history
    h.set_view_mode(mode)
    h._root.width = dp(732)
    h._place_totals()
    h._cascade_layout()
    chart = h._active_chart()
    assert list(reversed(h._side_col.children)) == [h._period_row, h._totals]
    assert h._graph_row.height == pytest.approx(chart.height)  # the list loses nothing to the arrows
    assert h._period_row.top == pytest.approx(h._graph_row.top)  # at the top, level with the chart
    assert h._totals.y >= h._graph_row.y - 0.5  # the row and the table fit beside the chart
    h._root.width = dp(360)  # and back upright
    h._place_totals()
    assert h._period_row.parent is h._graph_wrap and h._side_col.parent is None


def test_a_tap_on_a_day_after_paging_picks_that_day(paged_bars):
    h = paged_bars
    h.shift_period(-1)  # Sep 12 - Sep 25
    _frames()
    _gesture(_cell_center(h._bars, "2026-09-20"))
    assert h._filtered_date == "2026-09-20"


def test_a_swipe_right_pages_back_and_picks_no_day(paged_bars):
    h = paged_bars
    _gesture(_cell_center(h._bars, "2026-10-05"), dx=dp(80))
    assert h.period_end == TODAY - 14 * DAY
    assert h._filtered_date is None


def test_a_swipe_left_pages_forward(paged_bars):
    h = paged_bars
    h.shift_period(-1)
    _frames()
    _gesture(h._bars.to_window(h._bars.center_x, h._bars.center_y), dx=-dp(80))
    assert h.period_end == TODAY


def test_a_short_or_mostly_vertical_drag_neither_pages_nor_picks(paged_bars):
    h = paged_bars
    start = _cell_center(h._bars, "2026-10-05")
    _gesture(start, dx=dp(30))  # past a tap's slop, short of a swipe
    assert h.period_end == TODAY and h._filtered_date is None
    _gesture(start, dx=dp(50), dy=dp(80))
    assert h.period_end == TODAY and h._filtered_date is None


def test_a_fingertip_drift_is_still_a_tap(paged_bars):
    h = paged_bars
    _gesture(_cell_center(h._bars, "2026-10-05"), dx=dp(6), dy=dp(4))
    assert h._filtered_date == "2026-10-05"


def test_the_calendar_takes_the_same_gestures(window_history):
    h = window_history
    h.set_view_mode("calendar")
    h.load_sessions(_sessions("2024-01-05", "2026-02-10"))
    _frames()
    _gesture(h._heatmap.to_window(h._heatmap.center_x, h._heatmap.center_y), dx=dp(80))
    assert h.period_end == TODAY - 18 * 7 * DAY
    _frames()
    _gesture(_cell_center(h._heatmap, "2026-02-10"))
    assert h._filtered_date == "2026-02-10"


def test_the_mouse_wheel_over_a_day_picks_nothing(paged_bars):
    h = paged_bars
    touch = UnitTestTouch(*_cell_center(h._bars, "2026-10-05"))
    touch.profile.append("button")
    touch.button = "scrolldown"
    touch.touch_down()
    touch.touch_up()
    _frames()
    assert h._filtered_date is None


def test_the_arrows_page_and_stop_at_their_ends(paged_bars):
    h = paged_bars
    _tap(h._btn_next)  # disabled at today: nothing
    assert h.period_end == TODAY
    _tap(h._btn_prev)
    assert h.period_end == TODAY - 14 * DAY
    _tap(h._btn_next)
    assert h.period_end == TODAY


def test_a_tap_on_the_label_goes_back_to_today(paged_bars):
    h = paged_bars
    h.shift_period(-1)
    h.shift_period(-1)
    _frames()
    _tap(h._period_label)
    assert h.period_end == TODAY
