from kivy.metrics import dp

from app.ui.live_session import LiveSessionScreen, _compute_graph_height_adaptive
from app.ui.theme import S


def _reflowed(viewport_h: float) -> LiveSessionScreen:
    """The Session screen laid out again for a scroll viewport this tall."""
    screen = LiveSessionScreen()
    screen._scroll.height = viewport_h
    screen._reflow()
    return screen


def test_reflow_assigns_graph_height_from_scroll():
    screen = _reflowed(900.0)
    leftover = 900.0 - screen._stats_card.height - screen._bottom_bar.height - S.GAP_SM * 2
    assert leftover >= dp(400) and screen._graph_area.height == leftover  # tall enough: the graph takes what is left


def test_reflow_respects_floor_on_small_scroll():
    assert _reflowed(100.0)._graph_area.height == dp(240)


# ── Adaptive helper tests ──


def test_adaptive_returns_fixed_when_viewport_tall_enough():
    # viewport=800, stats=56, bottom=44, spacing=16 → leftover=684 ≥ min_fixed=400 → fixed
    result = _compute_graph_height_adaptive(
        viewport_h=800, stats_h=56, bottom_h=44, spacing=16,
        min_fixed_graph=400, min_graph_floor=240,
    )
    assert result == 684


def test_adaptive_falls_back_to_scroll_when_leftover_too_small():
    # viewport=400, stats=56, bottom=44, spacing=16 → leftover=284 < min_fixed=400 → scroll mode
    result = _compute_graph_height_adaptive(
        viewport_h=400, stats_h=56, bottom_h=44, spacing=16,
        min_fixed_graph=400, min_graph_floor=240,
    )
    # scroll mode: graph = viewport = 400
    assert result == 400


def test_adaptive_respects_floor_on_tiny_viewport():
    result = _compute_graph_height_adaptive(
        viewport_h=100, stats_h=56, bottom_h=44, spacing=16,
        min_fixed_graph=400, min_graph_floor=240,
    )
    # scroll mode, but viewport<floor → returns floor
    assert result == 240


def test_adaptive_boundary_case_exactly_at_threshold():
    # viewport=516, stats=56, bottom=44, spacing=16 → leftover=400 == min_fixed=400 → fixed
    result = _compute_graph_height_adaptive(
        viewport_h=516, stats_h=56, bottom_h=44, spacing=16,
        min_fixed_graph=400, min_graph_floor=240,
    )
    assert result == 400


