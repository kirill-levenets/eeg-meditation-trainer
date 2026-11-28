from kivy.metrics import dp

from app.ui.live_session import LiveSessionScreen, _graph_height
from app.ui.theme import S


def _reflowed(viewport_h: float) -> LiveSessionScreen:
    """The Session screen laid out again for a scroll viewport this tall."""
    screen = LiveSessionScreen()
    screen._scroll.height = viewport_h
    screen._reflow()
    return screen


def test_reflow_assigns_graph_height_from_scroll():
    screen = _reflowed(900.0)
    leftover = 900.0 - screen.stats.height - screen.controls.height - S.GAP_SM * 2
    assert leftover >= dp(400) and screen.graphs.area.height == leftover  # tall enough: the graph takes what is left


def test_reflow_respects_floor_on_small_scroll():
    assert _reflowed(100.0).graphs.area.height == dp(240)


# ── The height on its own: what the page leaves, the viewport, or the floor ──

GAPS = 2 * S.GAP_SM  # the body's two gaps, between the graph, the stats and the controls


def test_a_tall_viewport_gives_the_graph_what_the_page_leaves():
    assert _graph_height(dp(800), dp(56), dp(44)) == dp(800) - dp(56) - dp(44) - GAPS


def test_a_short_one_gives_it_the_viewport_and_the_page_scrolls():
    viewport = dp(400) + dp(56) + dp(44) + GAPS - 1  # a pixel short of leaving 400
    assert _graph_height(viewport, dp(56), dp(44)) == viewport


def test_never_under_the_floor():
    assert _graph_height(dp(100), dp(56), dp(44)) == dp(240)


def test_leaving_exactly_400_is_tall_enough():
    assert _graph_height(dp(400) + dp(56) + dp(44) + GAPS, dp(56), dp(44)) == dp(400)
