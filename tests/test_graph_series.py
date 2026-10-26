import os
import tempfile
import types
import unittest
from unittest import mock
from unittest.mock import MagicMock

from app.metrics.formula_slots import FormulaSlots
from app.session.session_program import PROGRAM_FORMULA_KEYS
from app.storage.database import DatabaseManager
from app.ui import graph_series
from app.ui.app_manager import EEGMeditationApp
from app.ui.hooks import wire
from app.ui.live_session import (
    METRICS_COLORS,
    METRICS_SCALES,
    SERIES_NAMES,
)
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.theme import StyledButton
from app.ui.widgets.band_totals import BAND_COLORS, BAND_SCALES
from tests._formula_settings import make_formula_settings
from tests._graph_series import make_graph_series
from tests._program_settings import make_programs


def _g(colors, scales, graph_id, names=None):
    return ScrollableGraphWidget(colors=colors, scales=scales, graph_id=graph_id, names=names)


class _FakeLive:
    def __init__(self):
        self.graph = _g(METRICS_COLORS, METRICS_SCALES, "live_metrics", SERIES_NAMES)
        self.raw_graph = _g({"eeg": (1, 1, 1, 1)}, {"eeg": 500.0}, "live_raw")
        self.band_graph = _g(BAND_COLORS, dict.fromkeys(BAND_COLORS, 1.0), "live_band")


class _FakeDiary:
    def __init__(self):
        self._metrics_graph = _g(METRICS_COLORS, METRICS_SCALES, "diary_metrics")
        self._raw_eeg_graph = _g({"eeg": (1, 1, 1, 1)}, {"eeg": 500.0}, "diary_raw")
        self._freq_graph = _g(BAND_COLORS, BAND_SCALES, "diary_freq")


class TestGraphSeriesPersistence(unittest.TestCase):
    """The series picker, persistence, and restore generalized to every graph."""

    def setUp(self):
        self.db_path = os.path.join(tempfile.gettempdir(), "test_series.db")
        self.app = EEGMeditationApp.__new__(EEGMeditationApp)
        self.app._db = DatabaseManager(db_path=self.db_path)
        self.uid = self.app._db.create_user("Alice")
        self.app._current_user_id = self.uid

        self.app._live_screen = _FakeLive()
        self.app._diary_screen = _FakeDiary()
        self.graph = self.app._live_screen.graph

        metric_keys = [k for k in METRICS_COLORS if k != "custom_formula"]
        settings = types.SimpleNamespace()
        settings._graph_toggles = {k: (k == "shamatha_score") for k in metric_keys}
        settings.formulas = types.SimpleNamespace(set_formula_slot=lambda *a, **k: None,
                                                  set_formula_slot_status=lambda *a, **k: None)
        self.app._settings_screen = settings
        self.app._formulas = FormulaSlots()
        self.app._formulas.evaluators[0] = types.SimpleNamespace(is_valid=False)
        self.app._audio_metric_key = "shamatha_score"  # the app's default: no formula slot drives the sound
        self.app._program_settings = make_programs(self.app._db, self.uid)  # simple mode: the user's own series
        self.app._formula_settings = make_formula_settings(self.app)
        self.app._graph_series = make_graph_series(self.app)

    def tearDown(self):
        self.app._db.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    # ── restore ──

    def test_json_selection_applied_per_graph(self):
        self.app._db.set_user_json_setting(
            self.uid, "graph_series_live_metrics", ["distraction", "sinking"]
        )
        self.app._db.set_user_json_setting(
            self.uid, "graph_series_diary_freq", ["alpha", "beta"]
        )
        self.app._graph_series.restore(self.uid)

        self.assertTrue(self.graph.is_visible("distraction"))
        self.assertTrue(self.graph.is_visible("sinking"))
        self.assertFalse(self.graph.is_visible("shamatha_score"))

        freq = self.app._diary_screen._freq_graph
        self.assertTrue(freq.is_visible("alpha"))
        self.assertTrue(freq.is_visible("beta"))
        self.assertFalse(freq.is_visible("gamma"))

    def test_legacy_migration_only_for_live_metrics(self):
        self.app._db.set_user_setting(self.uid, "toggle_native_attention", "True")
        self.app._db.set_user_setting(self.uid, "toggle_shamatha_score", "False")
        self.app._graph_series.restore(self.uid)

        self.assertTrue(self.graph.is_visible("native_attention"))
        self.assertFalse(self.graph.is_visible("shamatha_score"))
        # Diary graphs ignore the legacy live-only keys → default to all-visible, but a program's lines, which follow
        # the session shown.
        diary_m = self.app._diary_screen._metrics_graph
        self.assertEqual(set(diary_m.visible_keys()), set(diary_m.series_keys()) - set(PROGRAM_FORMULA_KEYS))

    def test_first_run_defaults(self):
        self.app._graph_series.restore(self.uid)
        # Live metrics: _graph_toggles default = Shamatha only.
        self.assertTrue(self.graph.is_visible("shamatha_score"))
        self.assertFalse(self.graph.is_visible("distraction"))
        # Other multi-series graphs: all visible.
        band = self.app._live_screen.band_graph
        self.assertEqual(set(band.visible_keys()), set(band.series_keys()))

    def test_single_series_graphs_untouched(self):
        # 1-series graphs are skipped by restore (a picker there could only blank
        # the line); their sole series stays visible.
        self.app._graph_series.restore(self.uid)
        self.assertTrue(self.app._live_screen.raw_graph.is_visible("eeg"))
        self.assertTrue(self.app._diary_screen._raw_eeg_graph.is_visible("eeg"))

    # ── toggle + persist ──

    def _toggle(self, graph, key):
        self.app._graph_series._toggle(graph, key, types.SimpleNamespace())

    def test_toggle_flips_and_persists_per_graph(self):
        self.app._graph_series.restore(self.uid)  # live: shamatha only
        self._toggle(self.graph, "distraction")
        self.assertTrue(self.graph.is_visible("distraction"))
        self.app._graph_series.persist(self.graph)
        saved = self.app._db.get_user_json_setting(self.uid, "graph_series_live_metrics")
        self.assertIn("distraction", saved)

        freq = self.app._diary_screen._freq_graph
        self._toggle(freq, "gamma")  # gamma was visible by default → now hidden
        self.assertFalse(freq.is_visible("gamma"))
        self.app._graph_series.persist(freq)
        saved_freq = self.app._db.get_user_json_setting(self.uid, "graph_series_diary_freq")
        self.assertNotIn("gamma", saved_freq)

    def test_a_detail_showing_a_programs_lines_lists_them_and_saves_none_of_its_set(self):
        diary = self.app._diary_screen._metrics_graph
        shown = frozenset({"shamatha_score", "program_formula"})
        series = make_graph_series(self.app, detail_program=lambda g: shown if g is diary else frozenset())
        for key in diary.series_keys():
            diary.set_visible(key, key in shown)  # what show_program_series does for a program session
        listed = []

        def capture(_title, rows, footer=None, **_kw):
            listed.extend(getattr(row, "text", None) or row.children[-1].text for row in rows)
            return types.SimpleNamespace(bind=lambda **_k: None, open=lambda: None)

        with mock.patch.object(graph_series, "make_scroll_popup", capture):
            series.present_picker(diary)
        self.assertIn(diary.series_name("program_formula"), listed)
        series.persist(diary)
        self.assertIsNone(self.app._db.get_user_json_setting(self.uid, "graph_series_diary_metrics"))

    def test_custom_formula_gated_on_live_graph_only(self):
        # Live metrics: custom_formula stays hidden while the formula is invalid.
        self.app._formulas.evaluators[0].is_valid = False
        self._toggle(self.graph, "custom_formula")
        self.assertFalse(self.graph.is_visible("custom_formula"))
        self.app._formulas.evaluators[0].is_valid = True
        self._toggle(self.graph, "custom_formula")
        self.assertTrue(self.graph.is_visible("custom_formula"))

        # Diary metrics: custom_formula is recorded data → toggles freely.
        diary_m = self.app._diary_screen._metrics_graph
        self.app._formulas.evaluators[0].is_valid = False
        diary_m.set_visible("custom_formula", False)
        self._toggle(diary_m, "custom_formula")
        self.assertTrue(diary_m.is_visible("custom_formula"))

    def test_custom_formula_2_gated_on_its_own_slot(self):
        # The per-slot gate must key off slot 1's evaluator, not slot 0's.
        self.app._formulas.evaluators[1] = types.SimpleNamespace(is_valid=False)
        self._toggle(self.graph, "custom_formula_2")
        self.assertFalse(self.graph.is_visible("custom_formula_2"))
        self.app._formulas.evaluators[1].is_valid = True
        self._toggle(self.graph, "custom_formula_2")
        self.assertTrue(self.graph.is_visible("custom_formula_2"))

    def test_custom_formula_hidden_choice_survives_reload(self):
        # Reload round-trip: a user who HID the live custom_formula line but kept a
        # valid saved formula must not have it force-shown on next launch. Mirrors
        # the production order in _load_user_settings (the profile's formulas
        # loaded, then _restore_graph_series decides visibility).
        from app.metrics.custom_formula import CustomFormulaEvaluator

        self.app._formulas.evaluators[0] = CustomFormulaEvaluator()
        formula = "alpha + beta"

        self.app._db.set_user_json_setting(
            self.uid, "graph_series_live_metrics", ["shamatha_score", "distraction"]
        )
        self.app._db.set_user_setting(self.uid, "custom_formula", formula)

        self.app._formula_settings.load(self.uid)
        self.app._graph_series.restore(self.uid)

        self.assertTrue(self.app._formulas.evaluators[0].is_valid)  # formula loaded
        self.assertFalse(self.graph.is_visible("custom_formula"))  # hide survived

    def test_custom_formula_visible_choice_survives_reload(self):
        from app.metrics.custom_formula import CustomFormulaEvaluator

        self.app._formulas.evaluators[0] = CustomFormulaEvaluator()
        formula = "alpha + beta"

        self.app._db.set_user_json_setting(
            self.uid, "graph_series_live_metrics", ["shamatha_score", "custom_formula"]
        )
        self.app._db.set_user_setting(self.uid, "custom_formula", formula)

        self.app._formula_settings.load(self.uid)
        self.app._graph_series.restore(self.uid)

        self.assertTrue(self.graph.is_visible("custom_formula"))




def _threshold_ys(g) -> tuple[list[float], float, float]:
    """The y of every threshold dash the graph drew, and its plot area's bottom and top (its outer grid lines)."""
    from app.ui.theme import C
    ys, grid, colour = [], [], None
    for ins in g._gfx.children:
        if ins.__class__.__name__ in ("Color", "ThemedColor"):
            colour = tuple(round(v, 3) for v in ins.rgba)
        elif ins.__class__.__name__ == "Line":
            pts = list(ins.points)[1::2]
            if colour == tuple(round(v, 3) for v in C.THRESHOLD_LINE):
                ys += pts
            elif colour == tuple(round(v, 3) for v in C.GRAPH_GRID):
                grid += pts
    return ys, min(grid), max(grid)


def test_a_threshold_below_zero_is_drawn_on_the_graphs_floor_like_its_values():
    # Values below 0 are drawn on the floor; a threshold there must not fall under the graph.
    from app.ui.raw_eeg_screen import ScrollableGraphWidget
    g = ScrollableGraphWidget(colors={"a": (1, 1, 1, 1)}, scales={"a": 100}, size=(400, 200), pos=(0, 0))
    for v in (-40.0, 10.0, 60.0):
        g.add_point({"a": v})
    for draw in (lambda: g.set_threshold(-30.0), lambda: g.set_threshold_steps([(0, -30.0)])):
        draw()
        ys, bottom, top = _threshold_ys(g)
        assert ys
        assert all(bottom <= y <= top for y in ys), (ys, bottom)


def test_the_live_screen_and_a_sessions_detail_draw_a_series_in_one_colour():
    from app.ui.diary_screen import DiaryScreen
    from app.ui.live_session import LiveSessionScreen
    live, detail = LiveSessionScreen(), DiaryScreen()
    for key in METRICS_COLORS:
        assert detail._metrics_graph.series_color(key) == live.graph.series_color(key), key
    for key in BAND_COLORS:
        assert detail._freq_graph.series_color(key) == live.band_graph.series_color(key), key


class _LiveGraph:
    """The live metrics graph as the picker and Settings use it: its series' names and visibility."""

    def __init__(self):
        self.names, self.shown = {}, {}

    def set_series_name(self, key, name):
        self.names[key] = name

    def series_name(self, key):
        return self.names.get(key, key)

    def set_visible(self, key, visible):
        self.shown[key] = visible

    def is_visible(self, key):
        return self.shown.get(key, False)


def test_choosing_a_saved_formula_renames_its_picker_row_at_once(tmp_path, monkeypatch):
    # The open picker's row follows Choose at once, as the graph line and the legend do.
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    uid = db.create_user("A")
    db.add_saved_formula(uid, "Calm", "alpha1 * 2")
    graph = _LiveGraph()
    app = types.SimpleNamespace(_db=db, _formulas=FormulaSlots(), _current_user_id=uid, _require_user=lambda _a: uid,
                                _audio_metric_key="shamatha_score", _live_screen=types.SimpleNamespace(graph=graph))
    app._formula_settings = make_formula_settings(app)
    series = make_graph_series(app, graphs=lambda: [graph])
    shown_rows = []
    monkeypatch.setattr(graph_series, "make_scroll_popup",
                        lambda title, rows, **kw: shown_rows.extend(rows) or MagicMock())
    row = StyledButton(text="Formula 1")

    series._choose_saved_formula(0, row)
    shown_rows[0].dispatch("on_release")
    db.close()

    assert graph.series_name("custom_formula") == "Calm"
    assert row.text == "Calm"  # the open picker's row says what the line and the legend say


def test_showing_a_series_already_shown_or_naming_it_as_named_changes_nothing():
    g = _g(METRICS_COLORS, METRICS_SCALES, "diary_metrics")
    changes, redraws = [], []
    wire(g, on_series_change=lambda: changes.append(1))
    g._redraw = lambda: redraws.append(1)
    g.set_visible("shamatha_score", g.is_visible("shamatha_score"))
    g.set_series_name("custom_formula", g.series_name("custom_formula"))
    assert changes == [] and redraws == []
    g.set_visible("shamatha_score", not g.is_visible("shamatha_score"))
    g.set_series_name("custom_formula", "Calm")
    assert changes == [1, 1] and redraws == [1, 1]
