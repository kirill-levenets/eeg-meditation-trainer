from unittest.mock import MagicMock

from kivy.metrics import dp

from app.ui.live_session import _compute_graph_height


def test_graph_fills_viewport_when_tall():
    assert _compute_graph_height(viewport_h=800.0, floor_dp=240.0) == 800.0


def test_graph_respects_floor_on_tiny_viewport():
    assert _compute_graph_height(viewport_h=100.0, floor_dp=240.0) == 240.0


def test_graph_at_exact_floor():
    assert _compute_graph_height(viewport_h=240.0, floor_dp=240.0) == 240.0


def test_reflow_assigns_graph_height_from_scroll():
    from app.ui.live_session import LiveSessionScreen

    screen = LiveSessionScreen.__new__(LiveSessionScreen)
    screen._scroll = MagicMock(height=900.0)
    screen._graph_area = MagicMock()

    screen._reflow()

    assert screen._graph_area.height == max(900.0, dp(240))


def test_reflow_respects_floor_on_small_scroll():
    from app.ui.live_session import LiveSessionScreen

    screen = LiveSessionScreen.__new__(LiveSessionScreen)
    screen._scroll = MagicMock(height=100.0)
    screen._graph_area = MagicMock()

    screen._reflow()

    assert screen._graph_area.height == dp(240)
