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


def test_confirm_delete_label_shows_name_visibly(monkeypatch):
    # Regression (caught on-device): the name was invisible on the always-dark
    # Kivy popup because the label used C.TEXT, which is dark in light themes
    # (dark-on-dark). Body text must be light, and it must wrap without a height
    # cap (a capped text_size drops the lines that don't fit).
    from kivy.uix.label import Label
    from kivy.uix.popup import Popup

    import app.ui.theme as theme_mod
    from app.ui.history_screen import HistoryScreen

    monkeypatch.setattr(Popup, "open", lambda self, *a, **k: None)
    opened = []
    real = theme_mod.make_message_popup

    def _capture(*a, **k):
        popup = real(*a, **k)
        opened.append(popup)
        return popup

    monkeypatch.setattr(theme_mod, "make_message_popup", _capture)  # the one confirm builds its popup with it

    screen = HistoryScreen()
    screen.load_sessions([{"id": 7, "date_time": "2026-09-26T14:32:00", "duration": 600,
                           "session_name": "14:32 - MindWave Mobile (very long session name)"}])
    name = "2026-09-26 14:32 - MindWave Mobile (very long session name)"  # the row's title
    screen._confirm_delete([7])

    msg = next(w for w in opened[0].content.walk() if isinstance(w, Label) and name in w.text)

    # Light enough to read on the dark popup chrome (the original C.TEXT in a
    # light theme had luminance ~0.15 and was invisible).
    assert sum(msg.color[:3]) / 3 > 0.7

    msg.width = 300  # binding fires synchronously on width change
    assert list(msg.text_size) == [300, None]
