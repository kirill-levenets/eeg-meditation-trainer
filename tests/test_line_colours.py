"""The scored line's colours (#94): its own colour, or a gradient by value from 0 to 200 that stays readable on every
theme's graph background; the Session screen colours the series being trained, History the one a session was scored
on; each profile keeps its choice and a change reaches every graph at once."""

import pytest
from kivy.graphics import Line, Mesh

from app.settings.registry import SettingsStore
from app.storage.database import DatabaseManager
from app.ui.app_manager import line_colours_setting
from app.ui.diary_screen import DiaryScreen
from app.ui.hooks import wire
from app.ui.line_colours import (
    DEFAULT,
    GRADIENT_TOP,
    LINE_COLOURS,
    MONO,
    OPTIONS,
    gradient_colour,
    gradient_rgb,
    gradient_texture,
)
from app.ui.live_session import METRICS_COLORS, METRICS_SCALES, LiveSessionScreen
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.settings_screen import SettingsScreen
from app.ui.theme import THEMES, C, _contrast

GRADIENTS = [name for name, _label in OPTIONS if name != MONO]
RAMP = [240.0 * i / 299 for i in range(300)]


@pytest.fixture(autouse=True)
def default_colours():
    saved = C.theme_name
    yield
    LINE_COLOURS.set(DEFAULT)
    C.set_theme(saved)


@pytest.fixture
def db(tmp_path):
    database = DatabaseManager(db_path=str(tmp_path / "t.db"))
    yield database
    database.close()


def _graph(values=RAMP) -> ScrollableGraphWidget:
    g = ScrollableGraphWidget(colors=METRICS_COLORS, scales=METRICS_SCALES, graph_id="live_metrics",
                              show_value_labels=False, show_timestamps=False, size_hint=(None, None), size=(600, 360))
    for k in METRICS_COLORS:
        g._visible[k] = k == "shamatha_score"
    g.set_gradient_series("shamatha_score")
    g._set_viewport(len(values))
    for k in METRICS_COLORS:
        g._data[k].extend(values if k == "shamatha_score" else [0.0] * len(values))
    g._total_points = len(values)
    return g


def _meshes(g: ScrollableGraphWidget) -> list:
    g._draw()
    return [c for c in g._gfx.children if isinstance(c, Mesh)]


def test_mono_and_five_gradients_with_todays_blue_to_red_as_the_default():
    assert [name for name, _label in OPTIONS] == ["mono", "blue_red", "viridis", "plasma", "turbo", "red_green"]
    assert DEFAULT == "blue_red" and LINE_COLOURS.name == DEFAULT


def test_blue_to_red_runs_from_blue_to_red():
    low, high = gradient_rgb("blue_red", 0.0), gradient_rgb("blue_red", 1.0)
    assert low[2] > 0.9 and low[0] < 0.2 and high[0] > 0.9 and high[2] < 0.2


def test_every_gradient_colour_reads_at_least_3_to_1_on_every_theme():
    for name in GRADIENTS:
        for theme in THEMES:
            bg = THEMES[theme]["GRAPH_BG"][:3]
            worst = min(_contrast(gradient_colour(name, i / 63, bg), bg) for i in range(64))
            assert worst >= 2.99, (name, theme, worst)


def test_a_colour_already_readable_is_left_as_published():
    bg = THEMES["Dark Blue"]["GRAPH_BG"][:3]
    assert gradient_colour("viridis", 0.5, bg) == pytest.approx(gradient_rgb("viridis", 0.5))


def test_the_gradient_spans_0_to_200():
    g = _graph()
    g.size = (600, 360)
    verts = _meshes(g)[0].vertices
    # (x, y, u, v) per vertex; v is where on the gradient a vertex samples: value / 200.
    assert GRADIENT_TOP == 200.0
    _x, graph_y, _w, graph_h = g._plot_rect()
    for i in range(0, len(verts), 4):
        value = (verts[i + 1] - graph_y) / graph_h * 200.0  # the metrics graph's axis is 0 to 200
        assert verts[i + 3] == pytest.approx(value / GRADIENT_TOP, abs=1e-6)


def test_mono_draws_the_scored_line_in_its_own_colour():
    g = _graph()
    LINE_COLOURS.set(MONO)
    assert _meshes(g) == []
    assert any(isinstance(c, Line) for c in g._gfx.children)


def test_a_change_reaches_a_graph_already_drawn():
    g = _graph()
    g.size = (600, 360)
    assert _meshes(g)[0].texture is gradient_texture("blue_red", tuple(C.GRAPH_BG))
    LINE_COLOURS.set("viridis")
    assert [c for c in g._gfx.children if isinstance(c, Mesh)][0].texture is gradient_texture("viridis",
                                                                                               tuple(C.GRAPH_BG))


def test_a_theme_switch_makes_the_gradient_readable_on_the_new_background():
    g = _graph()
    g.size = (600, 360)
    C.set_theme("Light Cream")
    assert _meshes(g)[0].texture is gradient_texture(DEFAULT, tuple(C.GRAPH_BG))


def test_the_session_screen_colours_the_series_being_trained():
    screen = LiveSessionScreen()
    assert screen.graph._gradient_key == "shamatha_score"  # before a session: today's line
    screen.set_training_series("custom_formula")
    assert screen.graph._gradient_key == "custom_formula"
    screen.set_training_series(None)  # the marker clears between sessions; the line keeps its colours
    assert screen.graph._gradient_key == "custom_formula"


def test_history_colours_the_metric_a_session_was_scored_on():
    detail = DiaryScreen()
    detail.show_session_detail({"id": 1, "date_time": "2026-10-10T07:30:00", "duration": 600,
                                "score_metric_key": "custom_formula", "score_metric_name": "Calm"})
    assert detail._metrics_graph._gradient_key == "custom_formula"
    detail.show_session_detail({"id": 2, "date_time": "2026-10-10T08:30:00", "duration": 600,
                                "score_metric_key": "program", "score_metric_name": "Deep"})
    assert detail._metrics_graph._gradient_key is None  # a program is scored per segment: no one line


def test_picking_line_colours_applies_them_at_once():
    screen = SettingsScreen()
    picked = []
    wire(screen.display, on_line_colours=picked.append)
    plasma = next(btn for row in screen.display._line_colour_rows for btn in row.children if btn._preset_value == "plasma")
    plasma.dispatch("on_release")
    assert picked == ["plasma"] and LINE_COLOURS.name == "plasma"
    selected = [btn._preset_value for row in screen.display._line_colour_rows for btn in row.children if btn.bold]
    assert selected == ["plasma"]  # one choice across both rows


def test_the_line_colours_are_saved_per_profile(db):
    me, other = db.create_user("me"), db.create_user("other")
    store = SettingsStore(db, [line_colours_setting()])
    LINE_COLOURS.set("turbo")
    store.save(me)
    store.load(other)
    assert LINE_COLOURS.name == DEFAULT  # the other profile's own, applied as it loads
    store.load(me)
    assert LINE_COLOURS.name == "turbo"


def test_a_strip_shows_its_gradient_low_to_high_from_left_to_right():
    screen = SettingsScreen()
    viridis = next(row.buttons()["viridis"] for row in screen.display._line_colour_rows if "viridis" in row.buttons())
    coords = viridis._gradient_strip._rect.tex_coords  # (u, v) at bottom-left, bottom-right, top-right, top-left
    assert coords[1::2] == (0.0, 1.0, 1.0, 0.0)
    C.set_theme("Light Cream")  # a theme switch repaints it
    assert viridis._gradient_strip._rect.tex_coords[1::2] == (0.0, 1.0, 1.0, 0.0)
