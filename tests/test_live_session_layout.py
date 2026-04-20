from unittest.mock import MagicMock

from kivy.metrics import dp

from app.ui.live_session import _compute_graph_height, _compute_graph_height_adaptive


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
    screen._stats_card = MagicMock(height=56.0)
    screen._bottom_bar = MagicMock(height=44.0)

    screen._reflow()

    # viewport=900, stats=56, bottom=44, spacing=S.GAP_SM*2 (≈16 for default theme)
    # fixed_graph = 900 - 56 - 44 - spacing; >= dp(400) → fixed mode
    assert screen._graph_area.height > 0


def test_reflow_respects_floor_on_small_scroll():
    from app.ui.live_session import LiveSessionScreen

    screen = LiveSessionScreen.__new__(LiveSessionScreen)
    screen._scroll = MagicMock(height=100.0)
    screen._graph_area = MagicMock()
    screen._stats_card = MagicMock(height=56.0)
    screen._bottom_bar = MagicMock(height=44.0)

    screen._reflow()

    assert screen._graph_area.height == dp(240)


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


# ── _duration_picker_label tests ──


def test_duration_picker_label_narrow_returns_empty():
    from app.ui.live_session import _duration_picker_label
    assert _duration_picker_label(window_w=300, timer_enabled=False, timer_minutes=0, narrow_threshold=480) == ""
    assert _duration_picker_label(window_w=300, timer_enabled=True, timer_minutes=15, narrow_threshold=480) == ""


def test_duration_picker_label_wide_free_returns_infinity():
    from app.ui.live_session import _duration_picker_label
    assert _duration_picker_label(window_w=800, timer_enabled=False, timer_minutes=0, narrow_threshold=480) == "\u221e"


def test_duration_picker_label_wide_numeric_minutes():
    from app.ui.live_session import _duration_picker_label
    assert _duration_picker_label(window_w=800, timer_enabled=True, timer_minutes=5, narrow_threshold=480) == "5m"
    assert _duration_picker_label(window_w=800, timer_enabled=True, timer_minutes=45, narrow_threshold=480) == "45m"


def test_duration_picker_label_wide_whole_hours():
    from app.ui.live_session import _duration_picker_label
    assert _duration_picker_label(window_w=800, timer_enabled=True, timer_minutes=60, narrow_threshold=480) == "1h"
    assert _duration_picker_label(window_w=800, timer_enabled=True, timer_minutes=120, narrow_threshold=480) == "2h"


def test_duration_picker_label_boundary():
    from app.ui.live_session import _duration_picker_label
    # At exactly 480 → not narrow (use strict less-than)
    assert _duration_picker_label(window_w=480, timer_enabled=False, timer_minutes=0, narrow_threshold=480) == "\u221e"
    # Just below → narrow
    assert _duration_picker_label(window_w=479, timer_enabled=False, timer_minutes=0, narrow_threshold=480) == ""


# ── _duration_picker_width tests ──


def test_duration_picker_width_narrow_is_chevron_sized():
    from app.ui.live_session import _duration_picker_width
    assert _duration_picker_width(window_w=300, narrow_threshold=480) == dp(36)


def test_duration_picker_width_wide_is_compact_label():
    from app.ui.live_session import _duration_picker_width
    assert _duration_picker_width(window_w=800, narrow_threshold=480) == dp(56)


def test_duration_picker_width_boundary_uses_wide():
    from app.ui.live_session import _duration_picker_width
    # At exactly threshold → wide (strict less-than)
    assert _duration_picker_width(window_w=480, narrow_threshold=480) == dp(56)
