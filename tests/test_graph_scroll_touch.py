"""A scrolled GraphAwareScrollView routes a tap to a graph only where that graph is drawn (#66)."""

import faulthandler

import pytest
from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.tests.common import UnitTestTouch
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from app.ui.raw_eeg_screen import GraphAwareScrollView, ScrollableGraphWidget


def _frames(n: int = 6) -> None:
    for _ in range(n):
        EventLoop.idle()


def _detail(scroll_y: float):
    """The session detail's shape: the notes field above, the graph at the bottom of a 1000 px content, in a 300 px
    viewport. Children keep content coordinates (the ScrollView translates the canvas)."""
    EventLoop.ensure_window()
    sv = GraphAwareScrollView(size_hint=(None, None), size=(400, 300), pos=(0, 0), do_scroll_x=False)
    content = BoxLayout(orientation="vertical", size_hint_y=None, height=1000)
    notes = TextInput(size_hint_y=None, height=100)
    graph = ScrollableGraphWidget(colors={"a": (1, 0, 0, 1)}, scales={"a": 100.0}, size_hint_y=None, height=300)
    for w in (Widget(size_hint_y=None, height=300), notes, Widget(size_hint_y=None, height=300), graph):
        content.add_widget(w)
    sv.add_widget(content)
    Window.add_widget(sv)
    _frames()
    sv.scroll_y = scroll_y
    _frames()
    return sv, graph, notes


@pytest.fixture
def scrolled_to_notes():
    sv, graph, notes = _detail(0.786)  # notes in view, the graph scrolled away below the window
    yield sv, graph, notes
    Window.remove_widget(sv)


@pytest.fixture
def scrolled_to_graph():
    sv, graph, notes = _detail(0.0)
    yield sv, graph, notes
    Window.remove_widget(sv)


def _window_center(w):
    return w.to_window(w.center_x, w.center_y)


def _tap(x, y):
    t = UnitTestTouch(x, y)
    t.touch_down()
    t.touch_up()


def _routed_to(sv, x, y):
    """The graph GraphAwareScrollView hands this tap to (the touch arrives in its parent's frame)."""
    t = UnitTestTouch(x, y)
    t.pos = sv.parent.to_widget(x, y)
    return sv._graph_under_touch(t)


def test_a_tap_on_the_notes_field_reaches_it_while_the_graph_is_scrolled_away(scrolled_to_notes):
    sv, graph, notes = scrolled_to_notes
    x, y = _window_center(notes)
    assert sv.y < y < sv.top  # the field is on screen
    assert graph.to_window(graph.x, graph.top)[1] < sv.y  # the graph is off-screen below
    assert _routed_to(sv, x, y) is None
    _tap(x, y)
    assert notes.focus


def test_a_tap_on_the_graph_still_reaches_the_graph(scrolled_to_graph):
    sv, graph, notes = scrolled_to_graph
    x, y = _window_center(graph)
    assert sv.y < y < sv.top
    assert _routed_to(sv, x, y) is graph
    _tap(x, y)
    assert not notes.focus


# --- the live session body in landscape: the graph fills the viewport, the stats and Start/Stop sit below it ------

def _body(scroll_y: float, points: int = 400):
    """Graph (300 px, the whole viewport) above 300 px of stats/controls, the view 100 px up the window."""
    EventLoop.ensure_window()
    sv = GraphAwareScrollView(size_hint=(None, None), size=(400, 300), pos=(0, 100), do_scroll_x=False)
    content = BoxLayout(orientation="vertical", size_hint_y=None, height=600)
    graph = ScrollableGraphWidget(colors={"a": (1, 0, 0, 1)}, scales={"a": 100.0}, size_hint_y=None, height=300)
    for i in range(points):  # more data than one screen, so a horizontal drag can pan
        graph.add_point({"a": float(i % 100)})
    content.add_widget(graph)
    content.add_widget(Widget(size_hint_y=None, height=300))
    sv.add_widget(content)
    Window.add_widget(sv)
    _frames()
    sv.scroll_y = scroll_y
    _frames()
    return sv, graph


@pytest.fixture
def body_at(request):
    sv, graph = _body(request.param)
    yield sv, graph
    Window.remove_widget(sv)


def _drag(x, y, dx, dy, steps=10):
    t = UnitTestTouch(x, y)
    t.touch_down()
    for i in range(1, steps + 1):
        t.touch_move(x + dx * i / steps, y + dy * i / steps)
        _frames(1)
    t.touch_up()
    _frames(3)
    return t


@pytest.mark.parametrize("body_at", [0.5], indirect=True)
@pytest.mark.parametrize("frac", [0.05, 0.5, 0.95])
def test_the_graph_takes_a_tap_anywhere_it_is_drawn(body_at, frac):
    sv, graph = body_at
    gx, gy = graph.to_window(graph.x, graph.y)
    top = min(gy + graph.height, sv.top)
    y = max(gy, sv.y) + (top - max(gy, sv.y)) * frac  # across the part of the graph inside the viewport
    taps = []
    graph.set_tap_callback(lambda: taps.append(1))
    t = UnitTestTouch(gx + graph.width / 2, y)
    t.touch_down()
    assert len(graph._grabbed_touches) == 1  # routed straight to the graph, not via the scroll view's hold
    t.touch_up()
    assert taps == [1]


@pytest.mark.parametrize("body_at", [1.0], indirect=True)
def test_a_vertical_swipe_over_the_graph_scrolls_the_page(body_at):
    sv, graph = body_at
    offset = graph._scroll_offset
    x, y = graph.to_window(graph.center_x, graph.center_y)
    _drag(x, y, 0, 150)  # finger moves up: the page scrolls down towards the controls
    assert sv.scroll_y < 0.9
    assert graph._scroll_offset == offset  # the graph did not pan


@pytest.mark.parametrize("body_at", [1.0], indirect=True)
def test_a_horizontal_drag_over_the_graph_pans_it_and_keeps_the_page(body_at):
    sv, graph = body_at
    offset = graph._scroll_offset
    x, y = graph.to_window(graph.center_x, graph.center_y)
    _drag(x, y, -150, 0)  # back in time from the live edge
    assert graph._scroll_offset != offset
    assert sv.scroll_y == 1


@pytest.mark.parametrize("body_at", [1.0], indirect=True)
def test_a_two_finger_pinch_zooms_the_graph_and_never_scrolls_the_page(body_at):
    sv, graph = body_at
    viewport = graph._viewport_points
    cx, cy = graph.to_window(graph.center_x, graph.center_y)
    a, b = UnitTestTouch(cx - 20, cy - 20), UnitTestTouch(cx + 20, cy + 20)
    a.touch_down()
    b.touch_down()
    for i in range(1, 11):  # fingers spread apart, mostly vertically
        a.touch_move(cx - 20 - 4 * i, cy - 20 - 8 * i)
        b.touch_move(cx + 20 + 4 * i, cy + 20 + 8 * i)
        _frames(1)
    a.touch_up()
    b.touch_up()
    _frames(3)
    assert graph._viewport_points != viewport
    assert sv.scroll_y == 1


# --- review round 2: the handoff only ever goes to the view that routed the touch, and only when it can scroll -----

def _held_by(touch):
    return [type(r()).__name__ for r in touch.grab_list if r() is not None]


def test_a_vertical_drag_on_a_graph_outside_any_scroll_view_stays_with_the_graph():
    from kivy.uix.floatlayout import FloatLayout
    EventLoop.ensure_window()
    overlay = FloatLayout(size_hint=(None, None), size=(400, 300), pos=(0, 0))  # the fullscreen graph overlay
    graph = ScrollableGraphWidget(colors={"a": (1, 0, 0, 1)}, scales={"a": 100.0}, size_hint=(1, 1))
    overlay.add_widget(graph)
    Window.add_widget(overlay)
    taps = []
    graph.set_tap_callback(lambda: taps.append(1))
    faulthandler.dump_traceback_later(20, exit=True)  # a hang here used to freeze the app
    try:
        _frames()
        x, y = graph.to_window(graph.center_x, graph.center_y)
        _drag(x, y, 0, 120)
    finally:
        faulthandler.cancel_dump_traceback_later()
        Window.remove_widget(overlay)
    assert taps == []  # a drag is not a tap


@pytest.mark.parametrize("body_at", [0.5], indirect=True)
def test_a_second_finger_swiping_on_the_graph_does_not_steal_the_page_scroll(body_at):
    sv, graph = body_at
    taps = []
    graph.set_tap_callback(lambda: taps.append(1))
    gx, gy = graph.to_window(graph.x, graph.y)
    ay = max(gy, sv.y) - 40  # finger A on the stats area below the graph
    assert sv.y < ay < sv.top
    a = UnitTestTouch(gx + 50, ay)
    a.touch_down()
    for _i in range(5):
        a.touch_move(a.x, a.y + 8)
        _frames(1)
    assert sv._touch is a  # A is scrolling the page
    bx = graph.to_window(graph.center_x, graph.y)[0]
    b = UnitTestTouch(bx, sv.top - 90)  # finger B on the graph, far enough inside to cross the swipe threshold
    b.touch_down()
    for _i in range(7):
        b.touch_move(b.x, b.y + 10)
        _frames(1)
    assert sv._touch is a  # B did not take A's scroll
    b.touch_up()
    a.touch_up()
    _frames(3)
    assert taps == []


@pytest.mark.parametrize("body_at", [1.0], indirect=True)
def test_after_a_pinch_the_remaining_finger_stays_with_the_graph(body_at):
    sv, graph = body_at
    cx, cy = graph.to_window(graph.center_x, graph.center_y)
    a, b = UnitTestTouch(cx, cy - 60), UnitTestTouch(cx, cy + 60)
    a.touch_down()
    b.touch_down()
    for i in range(1, 6):  # a vertical pinch
        a.touch_move(cx, cy - 60 - 6 * i)
        b.touch_move(cx, cy + 60 + 6 * i)
        _frames(1)
    b.touch_up()
    a.touch_move(cx, a.y + 3)  # the remaining finger nudges
    _frames(2)
    assert _held_by(a) == ["ScrollableGraphWidget"]
    a.touch_up()
    assert sv.scroll_y == 1


@pytest.mark.parametrize("body_at", [0.5], indirect=True)
def test_a_swipe_leaving_the_viewport_before_the_threshold_stays_with_the_graph(body_at):
    sv, graph = body_at
    x = graph.to_window(graph.center_x, graph.center_y)[0]
    t = UnitTestTouch(x, sv.top - 5)  # starts at the viewport's top edge, over the graph
    t.touch_down()
    for i in range(1, 8):
        t.touch_move(x, sv.top - 5 + 6 * i)  # leaves the viewport upwards
        _frames(1)
    assert _held_by(t) == ["ScrollableGraphWidget"]  # still owned by someone: the graph
    t.touch_up()


def test_a_vertical_swipe_on_a_page_that_cannot_scroll_stays_with_the_graph():
    EventLoop.ensure_window()
    sv = GraphAwareScrollView(size_hint=(None, None), size=(400, 300), pos=(0, 100), do_scroll_x=False)
    content = BoxLayout(orientation="vertical", size_hint_y=None, height=300)  # fits: nothing to scroll
    graph = ScrollableGraphWidget(colors={"a": (1, 0, 0, 1)}, scales={"a": 100.0}, size_hint_y=None, height=300)
    content.add_widget(graph)
    sv.add_widget(content)
    Window.add_widget(sv)
    try:
        _frames()
        x, y = graph.to_window(graph.center_x, graph.center_y)
        t = UnitTestTouch(x, y)
        t.touch_down()
        for i in range(1, 8):
            t.touch_move(x, y + 10 * i)
            _frames(1)
        assert _held_by(t) == ["ScrollableGraphWidget"]
        t.touch_up()
    finally:
        Window.remove_widget(sv)


@pytest.mark.parametrize("body_at", [1.0], indirect=True)
def test_a_handed_off_swipe_keeps_scrolling_after_a_pause(body_at):
    import time
    sv, graph = body_at
    x, y = graph.to_window(graph.center_x, graph.center_y)
    t = UnitTestTouch(x, y)
    t.touch_down()
    for i in range(1, 5):
        t.touch_move(x, y + 10 * i)
        _frames(1)
    assert _held_by(t) == ["GraphAwareScrollView"]  # handed to the page
    time.sleep(0.35)  # longer than ScrollView.scroll_timeout
    _frames(5)
    before = sv.scroll_y
    for i in range(5, 10):
        t.touch_move(x, y + 10 * i)
        _frames(1)
    assert sv.scroll_y < before  # still the page scrolling
    assert _held_by(t) == ["GraphAwareScrollView"]
    t.touch_up()
