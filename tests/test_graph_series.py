import os
import tempfile
import types
import unittest

from app.storage.database import DatabaseManager
from app.ui.app_manager import EEGMeditationApp
from app.ui.diary_screen import (
    FREQ_PREVIEW_COLORS,
    FREQ_PREVIEW_SCALES,
    METRICS_PREVIEW_COLORS,
    METRICS_PREVIEW_SCALES,
)
from app.ui.live_session import (
    _BAND_COLORS,
    METRICS_COLORS,
    METRICS_SCALES,
    SERIES_NAMES,
)
from app.ui.raw_eeg_screen import ScrollableGraphWidget


def _g(colors, scales, graph_id, names=None):
    return ScrollableGraphWidget(colors=colors, scales=scales, graph_id=graph_id, names=names)


class _FakeLive:
    def __init__(self):
        self.graph = _g(METRICS_COLORS, METRICS_SCALES, "live_metrics", SERIES_NAMES)
        self.raw_graph = _g({"eeg": (1, 1, 1, 1)}, {"eeg": 500.0}, "live_raw")
        self.band_graph = _g(_BAND_COLORS, dict.fromkeys(_BAND_COLORS, 1.0), "live_band")


class _FakeDiary:
    def __init__(self):
        self._metrics_graph = _g(METRICS_PREVIEW_COLORS, METRICS_PREVIEW_SCALES, "diary_metrics")
        self._raw_eeg_graph = _g({"eeg": (1, 1, 1, 1)}, {"eeg": 500.0}, "diary_raw")
        self._freq_graph = _g(FREQ_PREVIEW_COLORS, FREQ_PREVIEW_SCALES, "diary_freq")


class TestGraphSeriesPersistence(unittest.TestCase):
    """The series picker, persistence, and restore generalized to every graph."""

    def setUp(self):
        self.db_path = os.path.join(tempfile.gettempdir(), "test_series.db")
        self.app = EEGMeditationApp.__new__(EEGMeditationApp)
        self.app._db = DatabaseManager(db_path=self.db_path)
        self.uid = self.app._db.create_user("Alice")
        self.app._current_user_id = self.uid
        self.app._fullscreen_overlay = None
        self.app._fullscreen_graph = None

        self.app._live_screen = _FakeLive()
        self.app._diary_screen = _FakeDiary()
        self.graph = self.app._live_screen.graph

        metric_keys = [k for k in METRICS_COLORS if k != "custom_formula"]
        settings = types.SimpleNamespace()
        settings._graph_toggles = {k: (k == "shamatha_score") for k in metric_keys}
        self.app._settings_screen = settings
        self.app._init_formula_slots()
        self.app._formula_slots[0] = types.SimpleNamespace(is_valid=False)

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
        self.app._restore_graph_series(self.uid)

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
        self.app._restore_graph_series(self.uid)

        self.assertTrue(self.graph.is_visible("native_attention"))
        self.assertFalse(self.graph.is_visible("shamatha_score"))
        # Diary graphs ignore the legacy live-only keys → default to all-visible.
        diary_m = self.app._diary_screen._metrics_graph
        self.assertEqual(set(diary_m.visible_keys()), set(diary_m.series_keys()))

    def test_first_run_defaults(self):
        self.app._restore_graph_series(self.uid)
        # Live metrics: _graph_toggles default = Shamatha only.
        self.assertTrue(self.graph.is_visible("shamatha_score"))
        self.assertFalse(self.graph.is_visible("distraction"))
        # Other multi-series graphs: all visible.
        band = self.app._live_screen.band_graph
        self.assertEqual(set(band.visible_keys()), set(band.series_keys()))

    def test_single_series_graphs_untouched(self):
        # 1-series graphs are skipped by restore (a picker there could only blank
        # the line); their sole series stays visible.
        self.app._restore_graph_series(self.uid)
        self.assertTrue(self.app._live_screen.raw_graph.is_visible("eeg"))
        self.assertTrue(self.app._diary_screen._raw_eeg_graph.is_visible("eeg"))

    # ── toggle + persist ──

    def _toggle(self, graph, key):
        self.app._toggle_series_row(graph, key, types.SimpleNamespace())

    def test_toggle_flips_and_persists_per_graph(self):
        self.app._restore_graph_series(self.uid)  # live: shamatha only
        self._toggle(self.graph, "distraction")
        self.assertTrue(self.graph.is_visible("distraction"))
        self.app._persist_graph_series(self.graph)
        saved = self.app._db.get_user_json_setting(self.uid, "graph_series_live_metrics")
        self.assertIn("distraction", saved)

        freq = self.app._diary_screen._freq_graph
        self._toggle(freq, "gamma")  # gamma was visible by default → now hidden
        self.assertFalse(freq.is_visible("gamma"))
        self.app._persist_graph_series(freq)
        saved_freq = self.app._db.get_user_json_setting(self.uid, "graph_series_diary_freq")
        self.assertNotIn("gamma", saved_freq)

    def test_custom_formula_gated_on_live_graph_only(self):
        # Live metrics: custom_formula stays hidden while the formula is invalid.
        self.app._formula_slots[0].is_valid = False
        self._toggle(self.graph, "custom_formula")
        self.assertFalse(self.graph.is_visible("custom_formula"))
        self.app._formula_slots[0].is_valid = True
        self._toggle(self.graph, "custom_formula")
        self.assertTrue(self.graph.is_visible("custom_formula"))

        # Diary metrics: custom_formula is recorded data → toggles freely.
        diary_m = self.app._diary_screen._metrics_graph
        self.app._formula_slots[0].is_valid = False
        diary_m.set_visible("custom_formula", False)
        self._toggle(diary_m, "custom_formula")
        self.assertTrue(diary_m.is_visible("custom_formula"))

    def test_custom_formula_2_gated_on_its_own_slot(self):
        # The per-slot gate must key off slot 1's evaluator, not slot 0's.
        self.app._formula_slots[1] = types.SimpleNamespace(is_valid=False)
        self._toggle(self.graph, "custom_formula_2")
        self.assertFalse(self.graph.is_visible("custom_formula_2"))
        self.app._formula_slots[1].is_valid = True
        self._toggle(self.graph, "custom_formula_2")
        self.assertTrue(self.graph.is_visible("custom_formula_2"))

    def test_custom_formula_hidden_choice_survives_reload(self):
        # Reload round-trip: a user who HID the live custom_formula line but kept a
        # valid saved formula must not have it force-shown on next launch. Mirrors
        # the production order in _load_user_settings (formula loaded show=False,
        # then _restore_graph_series decides visibility).
        from app.metrics.custom_formula import CustomFormulaEvaluator

        self.app._formula_slots[0] = CustomFormulaEvaluator()
        self.app._settings_screen.set_formula_status = lambda *a, **k: None
        formula = "alpha + beta"

        self.app._db.set_user_json_setting(
            self.uid, "graph_series_live_metrics", ["shamatha_score", "distraction"]
        )
        self.app._db.set_user_setting(self.uid, "custom_formula", formula)

        self.app._on_custom_formula_change(formula, show=False)
        self.app._restore_graph_series(self.uid)

        self.assertTrue(self.app._formula_slots[0].is_valid)  # formula loaded
        self.assertFalse(self.graph.is_visible("custom_formula"))  # hide survived

    def test_custom_formula_visible_choice_survives_reload(self):
        from app.metrics.custom_formula import CustomFormulaEvaluator

        self.app._formula_slots[0] = CustomFormulaEvaluator()
        self.app._settings_screen.set_formula_status = lambda *a, **k: None
        formula = "alpha + beta"

        self.app._db.set_user_json_setting(
            self.uid, "graph_series_live_metrics", ["shamatha_score", "custom_formula"]
        )
        self.app._db.set_user_setting(self.uid, "custom_formula", formula)

        self.app._on_custom_formula_change(formula, show=False)
        self.app._restore_graph_series(self.uid)

        self.assertTrue(self.graph.is_visible("custom_formula"))
