"""Graph labels: X marks stay readable and bounded at any zoom, and each label text is rendered once, not per redraw."""

import math

from kivy.metrics import dp

import app.ui.raw_eeg_screen as rg
from app.ui.live_session import METRICS_COLORS, METRICS_SCALES
from app.ui.raw_eeg_screen import ScrollableGraphWidget, _x_grid_step


def test_default_zooms_keep_the_10_second_grid():
    assert _x_grid_step(dp(900), 60) == 10
    assert _x_grid_step(dp(900), 10) == 10


def test_wide_zoom_spaces_marks_at_least_the_minimum_gap_apart():
    for seconds in (150, 600, 1592, 3600, 3 * 3600):
        step = _x_grid_step(dp(900), seconds)
        assert step * dp(900) / seconds >= dp(rg._MIN_X_LABEL_GAP_DP) or step == rg._X_GRID_STEPS_S[-1]
        smaller = [s for s in rg._X_GRID_STEPS_S if s < step]
        assert not smaller or smaller[-1] * dp(900) / seconds < dp(rg._MIN_X_LABEL_GAP_DP)


def _live_graph(viewport_s: int, n_points: int) -> ScrollableGraphWidget:
    g = ScrollableGraphWidget(colors=METRICS_COLORS, scales=METRICS_SCALES, graph_id="live_metrics")
    g.size = (dp(900), dp(500))
    for k in METRICS_COLORS:
        g._visible[k] = k == "shamatha_score"
    g.set_threshold(95)
    g._set_viewport(int(viewport_s * g._sample_rate))
    for k in METRICS_COLORS:
        g._data[k].extend(50 + 40 * math.sin(i / 17) for i in range(n_points))
    g._total_points = n_points
    return g


def test_wide_zoom_draws_a_bounded_number_of_time_labels(monkeypatch):
    rendered = []
    real = ScrollableGraphWidget._make_text_texture
    monkeypatch.setattr(ScrollableGraphWidget, "_make_text_texture",
                        lambda self, text, **kw: rendered.append(text) or real(self, text, **kw))
    g = _live_graph(1592, 2400)  # 20 min of data in a ~26.5 min window
    rendered.clear()
    g._draw()
    time_labels = [t for t in rendered if ":" in t]
    assert len(time_labels) <= g.width / dp(rg._MIN_X_LABEL_GAP_DP) + 1, len(time_labels)


def test_redraw_reuses_label_textures(monkeypatch):
    created = []
    real_core = rg.CoreLabel

    def counting_core(**kw):
        created.append(kw["text"])
        return real_core(**kw)

    monkeypatch.setattr(rg, "_LABEL_CACHE", rg.OrderedDict())
    monkeypatch.setattr(rg, "CoreLabel", counting_core)
    g = _live_graph(150, 300)
    g._draw()
    first = len(created)
    assert first > 0
    g._draw()
    assert len(created) == first, "a second identical redraw rendered labels again"


def test_label_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(rg, "_LABEL_CACHE", rg.OrderedDict())
    monkeypatch.setattr(rg, "_LABEL_CACHE_MAX", 5)
    g = _live_graph(60, 10)
    for i in range(12):
        g._make_text_texture(str(i))
    assert len(rg._LABEL_CACHE) == 5
    assert [k[0] for k in rg._LABEL_CACHE] == ["7", "8", "9", "10", "11"]
