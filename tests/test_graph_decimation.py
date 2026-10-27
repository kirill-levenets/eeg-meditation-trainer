"""A zoomed-out graph draws each run of samples' min and max, its runs spanning part of the stroke at fixed sample
positions, so a redraw costs the graph's width and line thickness, not its zoom or the session's length (#70)."""

import math
import random
import time

import pytest
from kivy.graphics import Line, Mesh

import app.ui.graph_runs as runs
import app.ui.raw_eeg_screen as rg
from app.ui.graph_runs import RunExtremes, extremes, run_indices
from app.ui.live_session import METRICS_COLORS, METRICS_SCALES
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.theme import C
from tests.test_graph_gradient import _graph, _shot


@pytest.fixture(autouse=True)
def _dark_theme():
    """The pixel comparison counts bright line pixels against a dark plot background: on a light one every column is
    bright and a broken fold would pass."""
    saved = C.theme_name
    C.set_theme("Dark Blue")
    yield
    C.set_theme(saved)


SIX = ["shamatha_score", "meditation_score", "distraction", "sinking", "subtle_distraction", "native_attention"]


def _metrics_graph(n: int, keys=SIX, width=1000, spiky=False) -> ScrollableGraphWidget:
    g = ScrollableGraphWidget(colors=METRICS_COLORS, scales=METRICS_SCALES, graph_id="live_metrics",
                              size_hint=(None, None), size=(width, 500))
    for k in METRICS_COLORS:
        g._visible[k] = k in keys
    g.set_gradient_series("shamatha_score")
    for j, k in enumerate(METRICS_COLORS):
        if spiky:
            vals = [95.0 if i % 997 == 0 else (5.0 if i % 1009 == 0 else 50.0) for i in range(n)]
        else:
            vals = [50 + 40 * math.sin(i / 37 + j) for i in range(n)]
        g.add_points_batch(k, vals)
    g._set_viewport(n)
    return g


def _drawn_points(g: ScrollableGraphWidget) -> int:
    """Line points plus gradient vertices (2 quads + 1 patch per point, 16 floats each, ~2 quads per point)."""
    pts = 0
    for instr in g._gfx.children:
        if isinstance(instr, Line) and len(instr.points) > 8:
            pts += len(instr.points) // 2
        elif isinstance(instr, Mesh):
            pts += len(instr.vertices) // 32
    return pts


def _stroke(g: ScrollableGraphWidget) -> float:
    return 2 * rg.dp(g._line_width)  # Kivy Line width is the half-thickness


def _run_px(g: ScrollableGraphWidget) -> float:
    """The widest a run gets on screen: RUN_STROKES of the stroke."""
    return _stroke(g) * runs.RUN_STROKES


def _points_cap(g: ScrollableGraphWidget) -> float:
    """The most points a folded series draws: runs at least half of _run_px wide, 2 points each, and its ends."""
    return 2 * g._plot_rect()[2] / (_run_px(g) / 2) + 8


def _noisy(n: int, seed: int) -> list[float]:
    """A drifting score with noise, like a session's: a dense band once zoomed out."""
    rnd = random.Random(seed)
    v, out = 50.0, []
    for _ in range(n):
        v = min(95.0, max(5.0, v + rnd.gauss(0, 1.5)))
        out.append(min(100.0, max(0.0, v + rnd.gauss(0, 6))))
    return out


# ---- the runs ----


def test_a_run_is_drawn_as_its_min_and_max_in_sample_order():
    values = [5, 9, 1, 7, 3, 3, 8, 2, 6, 4, 6, 5]
    assert extremes(values, 0, 4) == (1, 2)  # the max 9 comes before the min 1
    assert RunExtremes(4).runs(values, 0, 0, 3) == [1, 2, 6, 7, 8, 9]


def test_kept_runs_are_not_scanned_again(monkeypatch):
    values = _noisy(1000, 2)
    kept = RunExtremes(8)
    before = kept.runs(values, 0, 0, 100)
    scanned = []
    real = runs.extremes
    monkeypatch.setattr(runs, "extremes", lambda v, a, b: scanned.append(a) or real(v, a, b))
    assert kept.runs(values, 0, 0, 125)[:200] == before
    assert len(scanned) == 25



def test_panning_back_scans_only_the_runs_before_what_is_kept(monkeypatch):
    values = _noisy(1000, 5)
    kept = RunExtremes(8)
    shown = kept.runs(values, 0, 50, 100)
    scanned = []
    real = runs.extremes
    monkeypatch.setattr(runs, "extremes", lambda v, a, b: scanned.append(a) or real(v, a, b))
    assert kept.runs(values, 0, 40, 90)[20:] == shown[:80]
    assert len(scanned) == 10


def _never(*_args):
    raise AssertionError("asked although the series doesn't fold")


def test_run_indices_draws_every_sample_until_a_run_is_worth_folding():
    assert run_indices([3.0, 1.0], 100.0, 2.0, _never, _never) == range(2)  # too short to fold
    assert run_indices([float(i) for i in range(50)], 1.0, 2.0, _never, _never) == range(50)  # runs under MIN_RUN


def test_run_indices_without_a_whole_run_in_the_window_draws_every_sample():
    values = [float(i) for i in range(10)]  # runs of 8 start at 8 and 16: samples 3..12 hold none whole
    assert run_indices(values, 6.0, 2.0, lambda: 3, _never) == range(10)


def test_run_indices_folds_each_whole_run_to_its_min_and_max_and_keeps_both_ends():
    values = [5.0, 1.0, 9.0, 4.0, 2.0, 8.0, 3.0, 7.0, 6.0, 0.0]
    asked = []
    out = run_indices(values, 4.0, 2.0, lambda: 0, lambda size: asked.append(size) or RunExtremes(size))
    assert asked == [4]  # runs of 4 samples: 0-3 and 4-7, then the part run 8-9
    assert out == [0, 1, 2, 4, 5, 8, 9]


def test_a_series_keeps_the_runs_of_one_size():
    g = ScrollableGraphWidget(colors={"a": (1, 1, 1, 1)}, scales={"a": 100.0}, size_hint=(None, None), size=(1000, 300))
    g._drawing_enabled = False
    values = _noisy(20000, 6)
    g.add_points_batch("a", values)
    for per_px in (6.0, 12.0, 24.0):  # three zooms, three run sizes
        g._drawn_indices("a", values, 0, per_px)
    assert list(g._run_extremes) == ["a"]
    assert g._run_extremes["a"].size == 1 << int(math.log2(24.0 * _run_px(g)))

def _reference(values: list[float], v0: int, size: int) -> list[int]:
    """Every run's min and max, runs cut at absolute multiples of size (part runs at the ends too), and both ends."""
    n = len(values)
    cuts = sorted({0, n} | {r * size - v0 for r in range(v0 // size + 1, (v0 + n) // size + 1) if r * size - v0 < n})
    want = {0, n - 1}
    for a, b in zip(cuts, cuts[1:]):
        run = values[a:b]
        want |= {a + run.index(min(run)), a + run.index(max(run))}
    return sorted(want)


def test_drawn_points_are_each_runs_min_and_max_through_appends_eviction_scrolling_and_reload():
    rnd = random.Random(3)
    g = ScrollableGraphWidget(colors={"a": (1, 1, 1, 1)}, scales={"a": 100.0}, max_points=3000,
                              size_hint=(None, None), size=(400, 300))
    g._drawing_enabled = False
    checked = 0
    for step in range(4000):
        g.add_point({"a": rnd.uniform(0, 100) if rnd.random() < 0.9 else rnd.choice([0.0, 100.0])})
        if step == 2500:
            g.load_static_data({"a": [rnd.uniform(0, 100) for _ in range(5000)]}, new_session=False)
        buf = list(g._data["a"])
        if step % 13 or len(buf) < 3:
            continue
        n = rnd.randint(3, len(buf))
        for start, per_px in ((rnd.randint(0, len(buf) - n), rnd.uniform(1, 30)), (len(buf) - n, n / 400)):
            values = buf[start:start + n]
            got = g._drawn_indices("a", values, start, per_px)
            longest = per_px * _run_px(g)
            if longest < runs.MIN_RUN:
                assert got == range(n)
                continue
            size = 1 << int(math.log2(longest))
            v0 = g._appended["a"] - len(buf) + start
            if isinstance(got, range):  # no whole run in the window
                assert (v0 + n) // size <= -(-v0 // size)
                continue
            assert got == _reference(values, v0, size), (step, start, n, size)
            checked += 1
    assert checked > 300


def test_a_growing_series_keeps_the_points_it_drew():
    # Fitted, each new tick moves every pixel column; runs at fixed sample positions don't, so the line doesn't shimmer.
    g = ScrollableGraphWidget(colors={"a": (1, 1, 1, 1)}, scales={"a": 100.0}, size_hint=(None, None), size=(1000, 300))
    g._drawing_enabled = False
    values = _noisy(7201, 4)
    g.add_points_batch("a", values[:7200])
    first = g._drawn_indices("a", values[:7200], 0, 7199 / 1000)
    g.add_point({"a": values[7200]})
    second = g._drawn_indices("a", values, 0, 7200 / 1000)
    size = 1 << int(math.log2(7199 / 1000 * _run_px(g)))
    whole = (7200 // size) * size  # where the first draw's last whole run ended
    assert [i for i in first if i < whole] == [i for i in second if i < whole]


def test_a_thicker_line_draws_fewer_points():
    def drawn(width):
        g = _metrics_graph(21600, keys=["distraction"])
        g.set_line_width(width)
        g._draw()
        return _drawn_points(g)

    assert drawn(3.0) < drawn(1.2) < drawn(0.5)


# ---- the graph ----


@pytest.mark.parametrize("n", [8000, 21600])
def test_a_zoomed_out_graph_draws_a_bounded_number_of_points(n):
    g = _metrics_graph(n)
    g._draw()
    assert _drawn_points(g) <= len(SIX) * _points_cap(g), (_drawn_points(g), _points_cap(g))


def test_zoomed_in_draws_every_point():
    g = _metrics_graph(300)
    g._draw()
    assert _drawn_points(g) >= len(SIX) * 299


def test_the_raw_eeg_graph_folds_by_its_zoom_and_draws_every_sample_zoomed_in():
    def raw(seconds):
        g = ScrollableGraphWidget(colors={"eeg": (0.3, 0.8, 0.8, 1)}, scales={"eeg": 100.0}, viewport_seconds=seconds,
                                  sample_rate=512, bipolar=True, max_points=512 * 60, size_hint=(None, None),
                                  size=(1000, 300), show_value_labels=False, show_timestamps=False)
        g.add_points_batch("eeg", [80 * math.sin(i / 3.0) for i in range(512 * 60)])
        g._draw()
        return _drawn_points(g), _points_cap(g)

    for seconds in (60, 10):  # 31 and 5 samples per pixel
        drawn, cap = raw(seconds)
        assert drawn <= cap, (seconds, drawn, cap)
    assert raw(2)[0] >= 512 * 2 - 1  # about one sample per pixel


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


def _centre_line_columns(values, drawn, graph_w, graph_h) -> dict[int, tuple[float, float]]:
    """Per pixel column, the height range the line's centre covers between consecutive drawn points."""
    span = len(values) - 1
    pts = [(i / span * graph_w, values[i] / 200 * graph_h) for i in drawn]
    cols: dict[int, tuple[float, float]] = {}
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        for c in range(math.floor(x1), math.floor(x2) + 1):
            a, b = max(x1, c), min(x2, c + 1)
            if b < a:
                continue
            ya, yb = (y1 + (y2 - y1) * (x - x1) / (x2 - x1) if x2 > x1 else y1 for x in (a, b))
            lo, hi = cols.get(c, (math.inf, -math.inf))
            cols[c] = (min(lo, ya, yb), max(hi, ya, yb))
    return cols


@pytest.mark.parametrize("n", [7200, 21600])  # 1 h and 3 h fitted
def test_the_folded_line_reaches_every_height_the_full_line_does_within_the_strokes_width(n):
    # A run's min and max are drawn at their own samples, so the folded line reaches each extreme of the full one less
    # than the stroke's width to the side (a run spans part of it), and passes every height between them on the way.
    g = ScrollableGraphWidget(colors={"a": (1, 1, 1, 1)}, scales={"a": 100.0}, size_hint=(None, None), size=(1000, 500))
    g._drawing_enabled = False
    values = _noisy(n, 7)
    g.add_points_batch("a", values)
    graph_w, graph_h = g._plot_rect()[2:]
    drawn = g._drawn_indices("a", values, 0, (n - 1) / graph_w)
    assert len(drawn) < n / 3  # folded: 2 points per run of 8 or more
    full = _centre_line_columns(values, range(n), graph_w, graph_h)
    folded = _centre_line_columns(values, drawn, graph_w, graph_h)
    tol = math.ceil(_stroke(g))
    missed = []
    for c, (lo, hi) in full.items():
        near = [folded[j] for j in range(c - tol, c + tol + 1) if j in folded]
        if min(e[0] for e in near) > lo + 1e-6 or max(e[1] for e in near) < hi - 1e-6:
            missed.append(c)
    assert not missed


def test_a_folded_graph_looks_like_the_unfolded_one(tmp_path, monkeypatch):
    # The same pixels within the stroke's width to the side and 1 px up or down, spikes and dips included, both kinds.
    def columns(img):
        px = img.load()
        w, h = img.size
        out = []
        for x in range(60, w - 70):
            ys = [y for y in range(10, h - 30) if max(px[x, y]) > 120]
            out.append((min(ys), max(ys)) if ys else None)
        return out

    graph = _metrics_graph(21600, keys=["shamatha_score", "distraction"], spiky=True, width=800)
    tol = math.ceil(_stroke(graph))
    folded = columns(_shot(graph, tmp_path, "folded"))
    monkeypatch.setattr(runs, "MIN_RUN", math.inf)
    plain = columns(_shot(_metrics_graph(21600, keys=["shamatha_score", "distraction"], spiky=True,
                                         width=800), tmp_path, "plain"))

    def outside(a, b):
        """Columns whose extent in a reaches beyond b's extents within tol columns, by more than a pixel."""
        bad = []
        for x, ext in enumerate(a):
            if ext is None:
                continue
            near = [b[j] for j in range(x - tol, x + tol + 1) if 0 <= j < len(b) and b[j]]
            if not near or ext[0] < min(e[0] for e in near) - 1 or ext[1] > max(e[1] for e in near) + 1:
                bad.append((x, ext, near))
        return bad

    assert len(folded) == len(plain)
    assert not outside(plain, folded), "a peak or dip of the full series is missing"
    assert not outside(folded, plain), "the folded line draws something the full series doesn't"


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


def test_gradient_graph_still_one_mesh_for_a_short_series():
    g = _graph([10.0 * (i % 11) for i in range(300)])
    g.size = (600, 360)
    g._draw()
    assert sum(isinstance(c, Mesh) for c in g._gfx.children) == 1
