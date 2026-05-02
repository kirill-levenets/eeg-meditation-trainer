import datetime

from app.ui.history_screen import Last14DaysBars


def test_last14_days_bars_instantiates():
    bars = Last14DaysBars()
    assert bars.height > 0


def test_last14_days_bars_set_data_no_exception():
    bars = Last14DaysBars()
    today = datetime.date.today()
    data = {
        (today - datetime.timedelta(days=0)).isoformat(): 80.0,
        (today - datetime.timedelta(days=3)).isoformat(): 50.0,
        (today - datetime.timedelta(days=7)).isoformat(): 30.0,
    }
    bars.set_data(data)  # must not raise


def test_last14_days_bars_callback_invoked_on_known_position():
    bars = Last14DaysBars()
    bars.size = (280, 132)
    bars.pos = (0, 0)
    today = datetime.date.today()
    data = {today.isoformat(): 90.0}
    bars.set_data(data)
    bars._redraw()  # populate _cell_positions

    received = []
    bars.set_day_tap_callback(lambda d: received.append(d))

    today_iso = today.isoformat()
    if today_iso in bars._cell_positions:
        rx, ry, rw, rh = bars._cell_positions[today_iso]

        class _Touch:
            def __init__(self, x, y):
                self.x = x
                self.y = y
                self.pos = (x, y)
        bars.on_touch_down(_Touch(rx + rw / 2, ry + rh / 2))
        assert received == [today_iso]


def test_history_screen_set_view_mode_swaps_active_widget():
    from app.ui.history_screen import HistoryScreen
    screen = HistoryScreen()

    screen.set_view_mode("calendar")
    # Only heatmap is parented in graph_wrap
    assert screen._heatmap.parent is screen._graph_wrap
    assert screen._bars.parent is None

    screen.set_view_mode("bars")
    # Now only bars is parented
    assert screen._heatmap.parent is None
    assert screen._bars.parent is screen._graph_wrap


def test_history_screen_view_mode_callback_fires_on_toggle():
    from app.ui.history_screen import HistoryScreen
    screen = HistoryScreen()
    received = []
    screen.set_view_mode_callback(lambda mode: received.append(mode))

    screen._on_toggle_pressed("bars")
    assert received == ["bars"]
    screen._on_toggle_pressed("calendar")
    assert received == ["bars", "calendar"]
