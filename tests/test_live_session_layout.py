from app.ui.live_session import _compute_graph_height


def test_graph_fills_viewport_when_tall():
    assert _compute_graph_height(viewport_h=800.0, floor_dp=240.0) == 800.0


def test_graph_respects_floor_on_tiny_viewport():
    assert _compute_graph_height(viewport_h=100.0, floor_dp=240.0) == 240.0


def test_graph_at_exact_floor():
    assert _compute_graph_height(viewport_h=240.0, floor_dp=240.0) == 240.0
