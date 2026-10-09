"""A graph draws at most 4 points per pixel column (M4), so its redraw cost follows its width, not its zoom (#70)."""

import math
import random
import time

import pytest
from kivy.graphics import Line, Mesh

import app.ui.raw_eeg_screen as rg
from app.ui.live_session import METRICS_COLORS, METRICS_SCALES
from app.ui.raw_eeg_screen import ScrollableGraphWidget, _column_bounds, _fold_columns
from app.ui.theme import C
from tests.test_graph_heatmap import _graph, _shot


@pytest.fixture(autouse=True)
def _dark_theme():
    """The pixel comparison counts bright line pixels against a dark plot background: on a light one every column is
    bright and a broken fold would pass."""
    saved = C.theme_name
    C.set_theme("Dark Blue")
    yield
    C.set_theme(saved)


def _fold(values, offset, per_px):
    return _fold_columns(values, _column_bounds(len(values), offset, per_px))


SIX = ["shamatha_score", "meditation_score", "distraction", "sinking", "subtle_distraction", "native_attention"]


def _metrics_graph(n: int, keys=SIX, width=1000, spiky=False) -> ScrollableGraphWidget:
    g = ScrollableGraphWidget(colors=METRICS_COLORS, scales=METRICS_SCALES, graph_id="live_metrics",
                              size_hint=(None, None), size=(width, 500))
    for k in METRICS_COLORS:
        g._visible[k] = k in keys
    g.set_heatmap_color("shamatha_score")
    for j, k in enumerate(METRICS_COLORS):
        if spiky:
            vals = [95.0 if i % 997 == 0 else (5.0 if i % 1009 == 0 else 50.0) for i in range(n)]
        else:
            vals = [50 + 40 * math.sin(i / 37 + j) for i in range(n)]
        g.add_points_batch(k, vals)
    g._set_viewport(n)
    return g


def _drawn_points(g: ScrollableGraphWidget) -> int:
    """Line points plus heatmap vertices (2 quads + 1 patch per point, 16 floats each, ~2 quads per point)."""
    pts = 0
    for instr in g._gfx.children:
        if isinstance(instr, Line) and len(instr.points) > 8:
            pts += len(instr.points) // 2
        elif isinstance(instr, Mesh):
            pts += len(instr.vertices) // 32
    return pts


# ---- the fold ----


def test_fold_keeps_each_columns_first_min_max_and_last_in_sample_order():
    values = [5, 9, 1, 7, 3, 3, 8, 2, 6, 4, 6, 5]
    idx = _fold(values, offset=0, per_px=4)  # columns [5 9 1 7] [3 3 8 2] [6 4 6 5]
    assert [values[i] for i in idx] == [5, 9, 1, 7, 3, 8, 2, 6, 4, 5]
    assert idx == sorted(idx)


def test_fold_keeps_the_first_and_last_sample_and_every_extreme():
    values = [50.0] * 5000
    values[1234], values[4321] = 99.0, 1.0
    idx = _fold(values, offset=0, per_px=20)
    drawn = {values[i] for i in idx}
    assert idx[0] == 0 and idx[-1] == len(values) - 1
    assert {99.0, 1.0} <= drawn
    assert len(idx) <= 4 * (len(values) // 20 + 2)


def _naive_m4(values, offset, per_px):
    """The reference: put every sample in its pixel column, keep each column's first, min, max and last."""
    groups: dict[int, list[int]] = {}
    for i in range(len(values)):
        groups.setdefault(math.floor((offset + i) / per_px), []).append(i)
    out = []
    for col in groups.values():
        vals = [values[i] for i in col]
        out.extend(sorted({col[0], col[vals.index(min(vals))], col[vals.index(max(vals))], col[-1]}))
    return out


def test_fold_columns_are_exactly_the_viewports_pixel_columns():
    rnd = random.Random(7)
    for offset, per_px, n in ((0, 4.0, 400), (10, 4.0, 30), (137, 6.73, 5000), (3, 23.4, 21600), (0, 4.5, 4)):
        values = [rnd.uniform(0, 100) for _ in range(n)]
        assert _fold(values, offset, per_px) == _naive_m4(values, offset, per_px), (offset, per_px, n)


def test_a_graph_folds_only_where_folding_is_cheaper():
    # A heatmap point costs several times a line point, so a line folds from 8 samples per pixel, a heatmap from 4.
    def drawn(keys, n):
        g = _metrics_graph(n, keys=keys, width=1000)
        g._draw()
        return _drawn_points(g)
    probe = _metrics_graph(2, keys=["shamatha_score"], width=1000)
    probe._draw()
    graph_w = probe._plot_rect()[2]  # the plot's width, short of what the labels need
    n = int(5 * graph_w)  # 5 samples per pixel
    assert drawn(["shamatha_score"], n) <= 4 * graph_w + 8
    assert drawn(["distraction"], n) >= n - 1


# ---- the graph ----


@pytest.mark.parametrize("n", [8000, 21600])  # 9 and 24 samples per pixel: every kind of line folds
def test_a_zoomed_out_graph_draws_at_most_four_points_per_pixel_column(n):
    g = _metrics_graph(n)
    g._draw()
    graph_w = g._plot_rect()[2]
    assert _drawn_points(g) <= len(SIX) * (4 * graph_w + 8), (_drawn_points(g), graph_w)


def test_zoomed_in_draws_every_point():
    g = _metrics_graph(300)
    g._draw()
    assert _drawn_points(g) >= len(SIX) * 299


def test_the_raw_eeg_graph_folds_when_zoomed_out_and_draws_every_sample_at_its_default_zoom():
    def raw(seconds):
        g = ScrollableGraphWidget(colors={"eeg": (0.3, 0.8, 0.8, 1)}, scales={"eeg": 100.0}, viewport_seconds=seconds,
                                  sample_rate=512, bipolar=True, max_points=512 * 60, size_hint=(None, None),
                                  size=(1000, 300), show_value_labels=False, show_timestamps=False)
        g.add_points_batch("eeg", [80 * math.sin(i / 3.0) for i in range(512 * 60)])
        g._draw()
        return _drawn_points(g)

    graph_w = 1000 - 2 * rg.dp(10)
    assert raw(60) <= 4 * graph_w + 8  # 31 samples per pixel
    assert raw(10) >= 512 * 10 - 1  # 5 per pixel: every sample is cheaper than folding a plain line


def test_redraw_cost_follows_the_width_not_the_zoom():
    def cost(n):
        g = _metrics_graph(n)
        ts = []
        for _ in range(7):
            t = time.perf_counter()
            g._draw()
            ts.append(time.perf_counter() - t)
        return min(ts)  # the least disturbed run: wall-clock timing on a shared machine

    assert cost(21600) < 5 * cost(2400)  # unfolded it is ~12x: every visible point went through Python


def test_a_folded_graph_looks_like_the_unfolded_one(tmp_path, monkeypatch):
    # The same pixels within 1 px (a thick stroke's half-width), spikes and dips included, heatmap and plain lines.
    def columns(img):
        px = img.load()
        w, h = img.size
        out = []
        for x in range(60, w - 70):
            ys = [y for y in range(10, h - 30) if max(px[x, y]) > 120]
            out.append((min(ys), max(ys)) if ys else None)
        return out

    folded = columns(_shot(_metrics_graph(21600, keys=["shamatha_score", "distraction"], spiky=True,
                                          width=800), tmp_path, "folded"))
    monkeypatch.setattr(rg, "_FOLD_MIN_PER_PX_HEATMAP", float("inf"))
    monkeypatch.setattr(rg, "_FOLD_MIN_PER_PX_LINE", float("inf"))
    plain = columns(_shot(_metrics_graph(21600, keys=["shamatha_score", "distraction"], spiky=True,
                                         width=800), tmp_path, "plain"))
    def within_a_pixel(a, b):
        """Every column's extent in a lies inside b's extents one pixel either side (the stroke's half-width)."""
        bad = []
        for x, ext in enumerate(a):
            if ext is None:
                continue
            near = [b[j] for j in (x - 1, x, x + 1) if 0 <= j < len(b) and b[j]]
            if not near or ext[0] < min(e[0] for e in near) - 1 or ext[1] > max(e[1] for e in near) + 1:
                bad.append((x, ext, near))
        return bad

    assert len(folded) == len(plain)
    assert not within_a_pixel(plain, folded), "a peak or dip of the full series is missing"
    assert not within_a_pixel(folded, plain), "the folded line draws something the full series doesn't"


def test_markers_keep_their_real_positions():
    g = _metrics_graph(21600, keys=["shamatha_score"])
    g.add_marker(12345)
    g._draw()
    graph_x, _y, graph_w, _h = g._plot_rect()
    vp = max(g._viewport_points, g._total_points)
    want = graph_x + (vp - g._total_points + 12345) / (vp - 1) * graph_w
    marker_xs = [i.points[0] for i in g._gfx.children if isinstance(i, Line) and len(i.points) == 4
                 and i.points[0] == i.points[2]]
    assert any(abs(x - want) < 0.01 for x in marker_xs)


def test_heatmap_graph_still_one_mesh_for_a_short_series():
    g = _graph([10.0 * (i % 11) for i in range(300)])
    g.size = (600, 360)
    g._draw()
    assert sum(isinstance(c, Mesh) for c in g._gfx.children) == 1
