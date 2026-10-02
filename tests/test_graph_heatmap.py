"""The heatmap line is one Mesh coloured by value: constant instruction count, full stroke width, clipped like any drawing."""

import glob

import pytest
from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.graphics import Line, Mesh
from kivy.uix.scrollview import ScrollView
from PIL import Image

import app.ui.raw_eeg_screen as rg
from app.ui.live_session import METRICS_COLORS, METRICS_SCALES
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.theme import C

RAMP = [120.0 * i / 299 for i in range(300)]
JAGGED = [60 + 55 * ((-1) ** i) * ((i % 7) / 6) for i in range(300)]


def _graph(values, heatmap=True, size=(600, 360)) -> ScrollableGraphWidget:
    g = ScrollableGraphWidget(colors=METRICS_COLORS, scales=METRICS_SCALES, graph_id="live_metrics",
                              show_value_labels=False, show_timestamps=False, size_hint=(None, None), size=size)
    for k in METRICS_COLORS:
        g._visible[k] = k == "shamatha_score"
    if heatmap:
        g.set_heatmap_color("shamatha_score")
    g._set_viewport(len(values))
    for k in METRICS_COLORS:
        g._data[k].extend(values if k == "shamatha_score" else [0.0] * len(values))
    g._total_points = len(values)
    return g


@pytest.fixture(autouse=True)
def _dark_theme():
    """Pixel checks count bright line pixels against a dark plot background; pin a dark palette."""
    saved = C.theme_name
    C.set_theme("Dark Blue")
    yield
    C.set_theme(saved)


def _pump(n=6):
    for _ in range(n):
        EventLoop.idle()


def _shot(root, tmp_path, name):
    EventLoop.ensure_window()
    Window.add_widget(root)
    try:
        _pump()
        for g in root.walk():
            if isinstance(g, ScrollableGraphWidget):
                g._redraw()
        _pump(3)
        Window.screenshot(name=str(tmp_path / f"{name}.png"))
    finally:
        Window.remove_widget(root)
        _pump(2)
    return Image.open(sorted(glob.glob(str(tmp_path / f"{name}*.png")))[-1]).convert("RGB")


def _bright(img, rows=None):
    px = img.load()
    w, h = img.size
    return sum(1 for x in range(8, w - 8) for y in (rows or range(h)) if max(px[x, y]) > 120)


def test_heatmap_is_one_mesh_whatever_the_point_count():
    for values in (RAMP, RAMP * 8):
        g = _graph(values)
        g.size = (600, 360)
        g._draw()
        kinds = [type(c) for c in g._gfx.children]
        assert kinds.count(Mesh) == 1, len(values)


def test_long_heatmap_splits_into_meshes_of_at_most_max_quads(monkeypatch):
    monkeypatch.setattr(rg, "_MESH_MAX_QUADS", 100)
    g = _graph(RAMP)
    g._draw()
    meshes = [c for c in g._gfx.children if isinstance(c, Mesh)]
    assert len(meshes) == -(-(2 * len(RAMP) - 1) // 100)
    assert all(len(m.vertices) <= 100 * 16 for m in meshes)


def test_a_long_heatmap_line_splits_within_the_gles2_index_limit():
    # A ~50-minute line built one Mesh of ~12000 quads = 72000 indices; Kivy raises past 65535 indices (GLES2) and the
    # app crashed mid-session. Folding (#70) keeps a zoomed-out graph far below that, but a wide fullscreen graph
    # draws up to 4 points per pixel column, so the split must still hold.
    g = _graph(RAMP)
    points = [c for i in range(6000) for c in (i * 0.1, 50 + (i % 100))]
    g._gfx.clear()
    g._add_heatmap_line(points, graph_y=0.0, graph_h=360.0, draw_scale=100.0)
    meshes = [c for c in g._gfx.children if isinstance(c, Mesh)]
    assert len(meshes) >= 2
    assert all(len(m.indices) <= 65535 for m in meshes)
    assert sum(len(m.vertices) for m in meshes) == (2 * 6000 - 1) * 16  # every quad drawn


def test_heatmap_stroke_matches_a_plain_line_and_is_coloured_by_value(tmp_path):
    for name, values in (("ramp", RAMP), ("jagged", JAGGED)):
        heat = _shot(_graph(values, heatmap=True), tmp_path, f"{name}_heat")
        flat = _shot(_graph(values, heatmap=False), tmp_path, f"{name}_flat")
        ratio = _bright(heat) / _bright(flat)
        assert 0.97 <= ratio <= 1.08, f"{name}: heatmap stroke covers {ratio:.0%} of a plain line"
    img = _shot(_graph(RAMP), tmp_path, "colours")
    px = img.load()
    h = img.size[1]
    low = next(px[30, y] for y in range(h - 1, -1, -1) if max(px[30, y]) > 120)
    high = next(px[580, y] for y in range(h) if max(px[580, y]) > 120)
    assert low[2] > 200 and low[0] < 80, f"value ~0 should be blue, got {low}"
    assert high[0] > 200 and high[2] < 80, f"value >100 should be red, got {high}"


def test_heatmap_inside_a_scrollview_stays_inside_its_viewport(tmp_path):
    sv = ScrollView(size_hint=(None, None), size=(600, 180), pos=(0, 100), do_scroll_x=False)
    sv.add_widget(_graph(JAGGED, size=(600, 360)))
    sv.scroll_y = 0.5
    img = _shot(sv, tmp_path, "nested")
    h = img.size[1]
    top_of_view, bottom_of_view = h - 100 - 180, h - 100
    outside = list(range(0, top_of_view - 2)) + list(range(bottom_of_view + 2, h))
    assert _bright(img, range(top_of_view + 2, bottom_of_view - 2)) > 0
    assert _bright(img, outside) == 0


def test_flat_line_still_draws_as_line_instructions():
    g = _graph(RAMP, heatmap=False)
    g._draw()
    assert any(isinstance(c, Line) for c in g._gfx.children)
    assert not any(isinstance(c, Mesh) for c in g._gfx.children)
