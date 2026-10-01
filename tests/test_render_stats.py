"""Render stats must attribute redraw time per graph and report the longest real frame gap once per window."""

from app.ui import render_stats
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.render_stats import SUSPEND_GAP_S, WINDOW_S, RenderStats


def test_summary_attributes_redraws_per_graph_sorted_by_total():
    s = RenderStats()
    s.record_redraw("live_metrics", 0.002)
    s.record_redraw("live_metrics", 0.004)
    s.record_redraw("live_raw", 0.050)
    s.on_frame(0.48, now=s._window_start + 1)
    assert s.summary() == ("Render: frame gap max 480 ms | live_raw 1x avg 50.0 max 50.0 ms"
                           " | live_metrics 2x avg 3.0 max 4.0 ms")


def test_window_logs_once_then_resets(monkeypatch):
    lines = []
    monkeypatch.setattr(render_stats.logger, "info", lines.append)
    s = RenderStats()
    t0 = s._window_start
    s.record_redraw("live_band", 0.010)
    s.on_frame(0.02, now=t0 + WINDOW_S - 1)
    assert lines == []
    s.on_frame(0.02, now=t0 + WINDOW_S)
    assert len(lines) == 1 and lines[0].startswith("Render: frame gap max 20 ms | live_band 1x")
    s.on_frame(0.02, now=t0 + 2 * WINDOW_S)
    assert len(lines) == 1, "a window with no redraws must stay silent"


def test_suspended_loop_is_not_a_stall():
    s = RenderStats()
    s.record_redraw("live_metrics", 0.001)
    s.on_frame(SUSPEND_GAP_S + 120, now=s._window_start + 1)
    s.on_frame(0.016, now=s._window_start + 2)
    assert s.summary().startswith("Render: frame gap max 16 ms")


def test_graph_redraw_is_recorded_under_its_graph_id(monkeypatch):
    s = RenderStats()
    monkeypatch.setattr(render_stats, "STATS", s)
    graph = ScrollableGraphWidget(colors={"alpha": (1, 0, 0, 1)}, scales={"alpha": 100.0}, graph_id="diary_freq")
    graph.size = (400, 300)
    graph._redraw()
    assert "diary_freq" in s._redraws
    assert s._redraws["diary_freq"][0] >= 1


def test_hidden_live_view_graphs_do_not_draw_until_shown_again(monkeypatch):
    # The Metrics/Raw toggle detaches the hidden view, but a detached graph keeps its size; after one visit to Raw
    # the hidden raw graph kept redrawing ~5000 points every tick (~130 ms each on the phone).
    from app.ui.live_session import LiveSessionScreen

    s = RenderStats()
    monkeypatch.setattr(render_stats, "STATS", s)
    screen = LiveSessionScreen()
    raw, band, metrics = screen._raw_graph, screen._band_graph, screen._graph
    for g in (raw, band, metrics):
        g.size = (400, 300)
    screen._set_view("raw")
    screen._set_view("metrics")
    s._redraws.clear()
    raw.add_points_batch(next(iter(raw._data)), [1.0] * 50)
    band.add_point(dict.fromkeys(band._data, 1.0))
    metrics.add_point(dict.fromkeys(metrics._data, 50.0))
    assert "live_raw" not in s._redraws and "live_band" not in s._redraws
    assert "live_metrics" in s._redraws
    screen._set_view("raw")
    assert "live_raw" in s._redraws and "live_band" in s._redraws, "shown again: drawn with what accrued while hidden"
