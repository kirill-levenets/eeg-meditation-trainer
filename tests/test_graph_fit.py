"""Fit the whole session (#43): a session detail graph shows all of its session at once and goes back to the window it
had; the shared zoom (the live graphs, the saved zoom) is left alone. Time labels read as hours past an hour."""

from types import SimpleNamespace

from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.tests.common import UnitTestTouch

from app.ui.app_manager import EEGMeditationApp
from app.ui.diary_screen import DiaryScreen
from app.ui.raw_eeg_screen import ScrollableGraphWidget, _elapsed_label

HOUR = 7200  # ticks at 2 a second


def _graph(n: int = HOUR, viewport_s: int = 60) -> ScrollableGraphWidget:
    g = ScrollableGraphWidget(colors={"a": (1, 1, 1, 1)}, scales={"a": 100}, viewport_seconds=viewport_s,
                              max_points=3 * HOUR, size=(dp(900), dp(400)), pos=(0, 0))
    g.load_static_data({"a": [50.0] * n})
    return g


def _frames(n: int = 3) -> None:
    for _ in range(n):
        EventLoop.idle()


# ---- time labels ----


def test_elapsed_labels_read_as_minutes_then_hours():
    assert [_elapsed_label(s) for s in (0, 70, 3599, 3600, 4500, 3 * 3600 + 5)] == [
        "0:00", "1:10", "59:59", "1:00:00", "1:15:00", "3:00:05"]


def test_a_fitted_long_session_labels_its_hours(monkeypatch):
    rendered = []
    real = ScrollableGraphWidget._make_text_texture
    monkeypatch.setattr(ScrollableGraphWidget, "_make_text_texture",
                        lambda self, text, **kw: rendered.append(text) or real(self, text, **kw))
    g = _graph(2 * HOUR)
    g.set_fitted(True)
    rendered.clear()
    g._draw()
    assert {"1:00:00", "1:30:00"} <= set(rendered), rendered


# ---- fitting ----


def test_fit_shows_the_whole_session_and_goes_back_to_the_window_it_had():
    g = _graph()
    g.set_scroll_offset(500)
    g.set_fitted(True)
    assert g.fitted and g.viewport_points == HOUR and g._scroll_offset == 0
    g.set_fitted(False)
    assert not g.fitted and g.viewport_points == 120 and g._scroll_offset == 500  # where it was, not the end


def test_fit_leaves_the_linked_graphs_and_the_shared_zoom_alone():
    g, live = _graph(), _graph()
    ScrollableGraphWidget.link_zoom(g, live)
    g.set_fitted(True)
    assert live.viewport_points == 120 and not live.fitted


def test_fit_never_zooms_in_past_the_default_window():
    # A session shorter than the default window is already all shown; a live session started fitted grows from it.
    g = _graph(n=30)  # 15 s in a 60 s window
    g.set_zoom_seconds(10)
    g.set_fitted(True)
    assert g.viewport_points == 120  # 60 s, the default window, not 15 s stretched


def test_another_session_loaded_while_fitted_is_shown_whole_and_back_still_restores():
    g = _graph()
    g.set_scroll_offset(500)
    g.set_fitted(True)
    g.load_static_data({"a": [50.0] * (HOUR // 2)})
    assert g.fitted and g.viewport_points == HOUR // 2
    g.set_fitted(False)
    assert g.viewport_points == 120 and g._scroll_offset == 0  # the window's width, at the new session's end


def test_zooming_a_fitted_graph_ends_the_fit_from_the_fitted_span():
    g, sibling = _graph(), _graph()
    ScrollableGraphWidget.link_zoom(g, sibling)
    g.set_fitted(True)
    g.zoom_in()
    assert not g.fitted and g.viewport_points == int(HOUR / g._zoom_factor)
    assert sibling.viewport_points == g.viewport_points  # an ordinary zoom: the link follows it


def test_a_zoom_from_a_linked_graph_ends_the_fit():
    g, live = _graph(), _graph()
    ScrollableGraphWidget.link_zoom(g, live)
    g.set_fitted(True)
    live.zoom_out()
    assert not g.fitted and g.viewport_points == live.viewport_points


# ---- the glyph ----


def test_the_glyphs_sit_in_the_plots_corners_fit_bottom_right():
    g = _graph()
    assert g._fit_icon_rect() is None  # hidden until wired
    for wire in (g.set_fit_callback, g.set_expand_callback, g.set_series_picker_callback):
        wire(lambda _g: None)
    g._draw()
    px, py, pw, ph = g._plot_rect()
    series, expand, fit = g._series_icon_rect(), g._expand_icon_rect(), g._fit_icon_rect()
    margin = dp(2)
    assert (series[0], series[1] + series[3]) == (px + margin, py + ph - margin)  # top-left
    assert (expand[0] + expand[2], expand[1] + expand[3]) == (px + pw - margin, py + ph - margin)  # top-right
    assert (fit[0] + fit[2], fit[1]) == (px + pw - margin, py + margin)  # bottom-right


def test_the_fit_glyph_hides_on_a_plot_too_short_for_it_under_expand():
    g = _graph()
    g.set_fit_callback(lambda _g: None)
    g.set_expand_callback(lambda _g: None)
    g.size = (dp(400), dp(100))
    g._draw()
    assert g._fit_icon_rect() is None and g._expand_icon_rect() is not None


# ---- the plot's margins ----


def test_the_plot_reaches_closer_to_the_edges_as_far_as_its_labels_allow():
    g = _graph()  # a 0-100 axis
    g._draw()
    left, right, _bottom, _top = g._pads
    assert left < dp(30) and right < dp(30)  # were 48 and 60
    wide = ScrollableGraphWidget(colors={"a": (1, 1, 1, 1)}, scales={"a": 200000}, size=(dp(900), dp(400)))
    wide.load_static_data({"a": [150000.0] * 100})
    wide._draw()
    assert wide._pads[0] > left and wide._pads[1] > right  # six-digit labels get the room they need


def test_a_live_value_gaining_a_digit_does_not_move_the_plot():
    g = _graph(n=0)
    g.add_point({"a": 9.0})
    g._draw()
    before = g._plot_rect()
    g.add_point({"a": 99.0})
    g._draw()
    assert g._plot_rect() == before


def test_a_tap_on_the_fit_glyph_fits():
    g = _graph()
    taps = []
    g.set_fit_callback(taps.append)
    Window.add_widget(g)
    try:
        _frames()
        x, y, w, h = g._fit_icon_rect()
        touch = UnitTestTouch(*g.to_window(x + w / 2, y + h / 2))
        touch.touch_down()
        touch.touch_up()
        assert taps == [g]
    finally:
        Window.remove_widget(g)


def _vertical_bars(g) -> list[float]:
    """The x of every vertical stroke drawn inside the fit glyph's rect."""
    x, y, w, h = g._fit_icon_rect()
    bars = []
    for ins in g._gfx.children:
        pts = list(getattr(ins, "points", []) or [])
        if len(pts) == 4 and pts[0] == pts[2] and pts[1] != pts[3] and x <= pts[0] <= x + w and y <= pts[1] <= y + h:
            bars.append(pts[0])
    return sorted(bars)


def test_the_glyph_draws_what_a_tap_will_do():
    g = _graph()
    g.set_fit_callback(lambda _g: None)
    g._draw()
    x, _y, w, _h = g._fit_icon_rect()
    assert len(_vertical_bars(g)) == 2  # |<->|: a bar at each side
    g.set_fitted(True)
    g._draw()
    assert _vertical_bars(g) == [x + w / 2]  # ->|<-: one bar in the middle


# ---- the session detail ----


def test_a_live_graph_fitted_follows_its_session_as_it_grows():
    g = _graph()
    g.set_scroll_offset(500)  # scrolled back in the last session
    g.set_fitted(True)
    for _ in range(300):
        g.add_point({"a": 60.0})
    assert g.viewport_points == HOUR + 300 and g._scroll_offset == 0
    g.clear_data()  # the next session
    assert g.fitted
    g.add_point({"a": 60.0})
    assert g.viewport_points == 120  # the default window, not a stretched second
    for _ in range(299):
        g.add_point({"a": 60.0})
    g.set_fitted(False)
    assert g.viewport_points == 120 and g._scroll_offset == 0  # the window's width, at this session's end


def test_the_zoom_saved_is_the_window_from_before_the_fit():
    g = _graph()
    g.set_fitted(True)
    assert g.viewport_points == HOUR and g.zoom_points == 120
    a = EEGMeditationApp.__new__(EEGMeditationApp)
    a._live_screen = SimpleNamespace(graph=g)
    assert a._saved_zoom_seconds() == 60.0


def test_a_hidden_tabs_graph_does_not_draw_until_it_is_shown(monkeypatch):
    d = DiaryScreen()
    for graph in (d._metrics_graph, d._freq_graph):
        graph.load_static_data({k: [1.0] * HOUR for k in graph._data})
    d._ready.update({"metrics", "raw", "freq"})
    d._switch_graph_tab("metrics")
    drawn = []
    monkeypatch.setattr(ScrollableGraphWidget, "_draw", lambda self: drawn.append(self))
    for graph in (d._metrics_graph, d._freq_graph):
        graph.set_fitted(True)
    assert d._metrics_graph in drawn and d._freq_graph not in drawn  # fitted, but not drawn off screen
    drawn.clear()
    d._switch_graph_tab("freq")
    assert drawn == [d._freq_graph] and d._freq_graph.fitted


# ---- the app's zoom links ----


def test_the_detail_zooms_apart_from_the_live_graphs_and_the_saved_zoom():
    live = [_graph() for _ in range(3)]
    detail = [_graph() for _ in range(3)]
    a = EEGMeditationApp.__new__(EEGMeditationApp)
    a._live_screen = SimpleNamespace(graph=live[0], raw_graph=live[1], band_graph=live[2])
    a._diary_screen = SimpleNamespace(_metrics_graph=detail[0], _raw_eeg_graph=detail[1], _freq_graph=detail[2])
    a._link_graph_zoom()
    a._wire_graph_affordances()
    assert all(g._fit_callback is not None for g in live + detail)  # every graph
    live[1]._fit_callback(live[1])  # a tap on the live raw graph's glyph fits the live graphs, together
    assert all(g.fitted for g in live) and not any(g.fitted for g in detail)
    live[0]._fit_callback(live[0])
    assert not any(g.fitted for g in live)
    detail[0].set_fitted(True)
    detail[0].zoom_in()  # a fitted session, hours wide, zoomed from there
    assert detail[2].viewport_points == detail[0].viewport_points  # the detail's tabs keep one window
    assert all(g.viewport_points == 120 for g in live)  # the live graphs (and the zoom saved from them) don't move
    live[0].zoom_out()
    assert live[1].viewport_points == live[0].viewport_points and detail[0].viewport_points != live[0].viewport_points


# ---- the review's fixes ----


def test_linked_graphs_take_the_first_ones_window_when_linked():
    metrics, raw = _graph(viewport_s=60), _graph(viewport_s=10)
    ScrollableGraphWidget.link_zoom(metrics, raw)
    assert raw.viewport_points == 120  # 60 s, not its own 10 s


def test_a_drag_that_starts_on_a_glyph_pans_and_fires_nothing():
    g = _graph()
    g.set_scroll_offset(1000)
    taps, marks = [], []
    g.set_fit_callback(taps.append)
    g.set_tap_callback(lambda: marks.append(1))
    Window.add_widget(g)
    try:
        _frames()
        x, y, w, h = g._fit_icon_rect()
        cx, cy = g.to_window(x + w / 2, y + h / 2)
        touch = UnitTestTouch(cx, cy)
        touch.touch_down()
        touch.touch_move(cx - dp(80), cy)
        touch.touch_up()
        assert taps == [] and marks == [] and g._scroll_offset != 1000  # it panned
        touch = UnitTestTouch(cx, cy)
        touch.touch_down()
        touch.touch_up()
        assert taps == [g] and marks == []  # a tap on the glyph is the glyph's, not a marker
    finally:
        Window.remove_widget(g)


def test_the_plot_keeps_its_margins_as_an_auto_scaled_peak_crosses_a_digit():
    g = ScrollableGraphWidget(colors={"a": (1, 1, 1, 1)}, scales={"a": 1.0}, auto_scale=True,
                              size=(dp(900), dp(400)), pos=(0, 0))
    g.load_static_data({"a": [80000.0] * 50})
    g._draw()
    g.add_point({"a": 120000.0})
    g._draw()
    wide = g._plot_rect()  # six digits
    for _ in range(200):  # the peak scrolls out of the window: the axis is back to five digits
        g.add_point({"a": 80000.0})
    g._draw()
    assert g._plot_rect() == wide  # grown for six digits, not shrunk back
    g.clear_data()  # the next session starts from its own labels
    g.add_point({"a": 5.0})
    g._draw()
    assert g._plot_rect()[2] > wide[2]


def test_a_line_end_wider_than_the_axis_grows_the_margin_once():
    g = _graph(n=0)
    g.add_point({"a": -1234.0})
    g._draw()
    once = g._plot_rect()
    g.add_point({"a": 50.0})
    g._draw()
    assert g._plot_rect() == once


def test_the_zoom_is_saved_and_restored_in_seconds():
    g = _graph()
    g.set_zoom_seconds(300)
    assert g.zoom_seconds == 300 and not g.fitted
    g.set_fitted(True)
    assert g.zoom_seconds == 300


def _diagonals_in(g, rect) -> int:
    x, y, w, h = rect
    n = 0
    for ins in g._gfx.children:
        pts = list(getattr(ins, "points", []) or [])
        if len(pts) == 4 and pts[0] != pts[2] and pts[1] != pts[3] and x <= pts[0] <= x + w and y <= pts[1] <= y + h:
            n += 1
    return n


def test_in_fullscreen_the_corner_glyph_draws_the_close_cross():
    g = _graph()
    g.set_expand_callback(lambda _g: None)
    g._draw()
    assert _diagonals_in(g, g._expand_icon_rect()) == 0  # expand: corner brackets
    g.set_expand_callback(lambda _g: None, closes=True)
    g._draw()
    assert _diagonals_in(g, g._expand_icon_rect()) == 2  # the cross


# ---- the second review's fixes ----


def test_a_graph_off_screen_ignores_the_mouse_wheel():
    # Every graph hears the window's wheel; one on a hidden screen keeps its old place under the pointer.
    hidden, shown = _graph(), _graph()
    Window.add_widget(shown)
    try:
        _frames()
        x, y = shown.to_window(*shown.center)
        for g in (hidden, shown):
            g._on_window_mouse_down(Window, x, y, "scrolldown", [])
        assert hidden.viewport_points == 120 and shown.viewport_points != 120
    finally:
        Window.remove_widget(shown)


def test_stacked_end_labels_stay_inside_the_graph():
    g = ScrollableGraphWidget(colors={"a": (1, 0, 0, 1), "b": (0, 1, 0, 1), "c": (0, 0, 1, 1)},
                              scales={"a": 100, "b": 100, "c": 100}, size=(dp(400), dp(300)), pos=(0, 0))
    for _ in range(2):  # a line needs two points
        g.add_point({"a": 100.0, "b": 100.0, "c": 99.0})  # all at the top of the axis
    g._draw()
    px, _py, pw, _ph = g._plot_rect()
    labels = [ins for ins in g._gfx.children
              if ins.__class__.__name__ == "Rectangle" and ins.texture is not None and ins.pos[0] > px + pw]
    assert len(labels) == 3
    assert all(g.y <= r.pos[1] and r.pos[1] + r.size[1] <= g.top for r in labels), [r.pos for r in labels]


def test_the_threshold_label_fits_in_the_right_margin():
    g = _graph()
    g.set_threshold(12345.0)  # far past the 0-100 axis: the label is wider than any axis label
    g._draw()
    px, _py, pw, _ph = g._plot_rect()
    labels = [ins for ins in g._gfx.children
              if ins.__class__.__name__ == "Rectangle" and ins.texture is not None and ins.pos[0] > px + pw]
    assert labels and all(r.pos[0] + r.size[0] <= g.right for r in labels)


def test_fit_toggles_the_graphs_linked_with_it():
    a, b, c = _graph(), _graph(), _graph()
    ScrollableGraphWidget.link_zoom(a, b)
    b.toggle_fit()
    assert a.fitted and b.fitted and not c.fitted
    a.toggle_fit()
    assert not a.fitted and not b.fitted


def test_a_glyph_is_a_button_drift_inside_it_still_taps_and_it_shows_its_press():
    g = _graph()
    g.set_scroll_offset(1000)
    taps = []
    g.set_expand_callback(taps.append, closes=True)  # fullscreen's close cross
    Window.add_widget(g)
    try:
        _frames()
        x, y, w, h = g._expand_icon_rect()
        cx, cy = g.to_window(x + w / 2, y + h / 2)
        touch = UnitTestTouch(cx, cy)
        touch.touch_down()
        assert g._pressed_glyph is not None  # drawn pressed
        touch.touch_move(cx - dp(15), cy - dp(5))  # a fingertip drifting, still on the cross
        touch.touch_up()
        assert taps == [g] and g._scroll_offset == 1000 and g._pressed_glyph is None
    finally:
        Window.remove_widget(g)


# ---- the third review's fixes ----


def _rects_right_of_plot(g):
    px, _py, pw, _ph = g._plot_rect()
    return [ins for ins in g._gfx.children
            if ins.__class__.__name__ == "Rectangle" and ins.texture is not None and ins.pos[0] > px + pw]


def test_lifting_one_finger_of_a_pinch_clears_only_its_own_glyph_press():
    g = _graph()
    g.set_fit_callback(lambda _g: None)
    Window.add_widget(g)
    try:
        _frames()
        x, y, w, h = g._fit_icon_rect()
        on_glyph = UnitTestTouch(*g.to_window(x + w / 2, y + h / 2))
        on_plot = UnitTestTouch(*g.to_window(g.center_x, g.center_y))
        on_glyph.touch_down()
        on_plot.touch_down()
        on_plot.touch_up()  # the other finger lifts: the glyph is still held
        assert g._pressed_glyph is not None
        on_glyph.touch_up()
        assert g._pressed_glyph is None
    finally:
        Window.remove_widget(g)


def test_a_drag_from_a_glyph_pans_once_it_passes_a_fingertips_drift():
    g = _graph()
    g.set_scroll_offset(1000)
    g.set_fit_callback(lambda _g: None)
    Window.add_widget(g)
    try:
        _frames()
        x, y, w, h = g._fit_icon_rect()
        cx, cy = g.to_window(x + w * 0.75, y + h / 2)
        touch = UnitTestTouch(cx, cy)
        touch.touch_down()
        touch.touch_move(cx - dp(28), cy)  # still over the 44 dp glyph, but past a drift
        assert g._scroll_offset != 1000 and g._pressed_glyph is None
        touch.touch_up()
    finally:
        Window.remove_widget(g)


def test_the_saved_zoom_starts_both_groups_and_the_detail_never_saves():
    live, detail = [_graph() for _ in range(3)], [_graph() for _ in range(3)]
    a = EEGMeditationApp.__new__(EEGMeditationApp)
    a._live_screen = SimpleNamespace(graph=live[0], raw_graph=live[1], band_graph=live[2])
    a._diary_screen = SimpleNamespace(_metrics_graph=detail[0], _raw_eeg_graph=detail[1], _freq_graph=detail[2])
    a._link_graph_zoom()
    a._apply_saved_zoom(300.0)
    assert all(g.zoom_seconds == 300.0 for g in live + detail)
    detail[0].zoom_out()
    assert a._saved_zoom_seconds() == 300.0


def test_without_value_labels_the_last_time_label_stays_inside():
    g = ScrollableGraphWidget(colors={"a": (1, 1, 1, 1)}, scales={"a": 100}, show_value_labels=False,
                              size=(dp(400), dp(200)), pos=(0, 0))
    g.load_static_data({"a": [50.0] * 7201})  # an hour and half a second: a mark at 1:00:00 on the right edge
    g.set_fitted(True)
    g._draw()
    labels = [ins for ins in g._gfx.children if ins.__class__.__name__ == "Rectangle" and ins.texture is not None]
    assert labels and all(g.x <= r.pos[0] and r.pos[0] + r.size[0] <= g.right for r in labels)


def test_a_step_at_the_top_of_the_scale_keeps_its_label_inside():
    g = _graph()
    g.set_threshold_steps([(0, 100.0)])  # the 0-100 axis's ceiling
    g._draw()
    labels = [ins for ins in g._gfx.children if ins.__class__.__name__ == "Rectangle" and ins.texture is not None]
    assert all(r.pos[1] + r.size[1] <= g.top for r in labels)


def test_end_labels_near_zero_stay_above_the_time_rows():
    keys = "abcdef"
    g = ScrollableGraphWidget(colors=dict.fromkeys(keys, (1, 0, 0, 1)), scales=dict.fromkeys(keys, 100),
                              size=(dp(400), dp(80)), pos=(0, 0))  # a short plot: no room above for all six
    g.set_start_wall_time(1_759_648_500.0)  # two time rows under the plot
    for _ in range(2):
        g.add_point(dict.fromkeys(keys, 0.0))
    g._draw()
    _px, py, _pw, _ph = g._plot_rect()
    labels = _rects_right_of_plot(g)
    assert len(labels) == 6 and all(r.pos[1] + r.size[1] / 2 >= py for r in labels)


# ---- the fifth review's fixes ----


def _raw_and_band():
    raw = ScrollableGraphWidget(colors={"eeg": (1, 1, 1, 1)}, scales={"eeg": 500}, sample_rate=512, max_points=512 * 60,
                                viewport_seconds=10, size=(dp(900), dp(400)), pos=(0, 0))
    raw.load_static_data({"eeg": [1.0] * (512 * 60)})  # its last minute
    band = _graph()  # an hour
    ScrollableGraphWidget.link_zoom(band, raw)
    band.toggle_fit()
    return raw, band


def test_zooming_the_raw_graph_from_a_fit_zooms_from_the_sessions_span():
    raw, band = _raw_and_band()
    raw.zoom_out()  # raw is capped at its minute: the group still zooms out from the hour
    assert band.viewport_points >= HOUR and not band.fitted
    raw, band = _raw_and_band()
    raw.zoom_in()
    assert abs(band.viewport_points - HOUR / raw._zoom_factor) <= 1  # the hour, zoomed in a step


def test_a_reload_of_the_same_session_keeps_the_fit_and_the_margins():
    g = _graph()
    g.set_scroll_offset(500)
    g.set_fitted(True)
    g._draw()
    pads = g._pads
    g.load_static_data({"a": [50.0] * (HOUR + 100)}, new_session=False)  # back from a screen lock
    assert g.fitted and g.viewport_points == HOUR + 100 and g._pads_floor == pads
    g.set_fitted(False)
    assert g._scroll_offset == 500


def test_a_two_finger_tap_fires_neither_a_glyph_nor_a_marker():
    g = _graph()
    fired, marks = [], []
    g.set_fit_callback(fired.append)
    g.set_tap_callback(lambda: marks.append(1))
    Window.add_widget(g)
    try:
        _frames()
        x, y, w, h = g._fit_icon_rect()
        on_glyph = UnitTestTouch(*g.to_window(x + w / 2, y + h / 2))
        on_plot = UnitTestTouch(*g.to_window(g.center_x, g.center_y))
        on_glyph.touch_down()
        on_plot.touch_down()
        on_plot.touch_up()
        on_glyph.touch_up()
        assert fired == [] and marks == []
    finally:
        Window.remove_widget(g)
