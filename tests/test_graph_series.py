import os
import tempfile
import unittest

from app.storage.database import DatabaseManager
from app.ui.app_manager import EEGMeditationApp
from app.ui.live_session import METRICS_COLORS, METRICS_SCALES
from app.ui.raw_eeg_screen import ScrollableGraphWidget


class _CB:
    def __init__(self):
        self.active = False


class TestGraphSeriesPersistence(unittest.TestCase):
    """_restore_graph_series: JSON selection wins; else migrate legacy toggles."""

    def setUp(self):
        self.db_path = os.path.join(tempfile.gettempdir(), "test_series.db")
        self.app = EEGMeditationApp.__new__(EEGMeditationApp)
        self.app._db = DatabaseManager(db_path=self.db_path)
        self.uid = self.app._db.create_user("Alice")

        graph = ScrollableGraphWidget(colors=METRICS_COLORS, scales=METRICS_SCALES)
        live = type("LS", (), {})()
        live.graph = graph
        live._rebuild_metric_legend = lambda keys: None
        self.app._live_screen = live
        self.graph = graph

        metric_keys = [k for k in METRICS_COLORS if k != "custom_formula"]
        settings = type("SS", (), {})()
        settings._checkboxes = {k: _CB() for k in metric_keys}
        settings._graph_toggles = {k: (k == "shamatha_score") for k in metric_keys}
        self.app._settings_screen = settings
        self.app._custom_formula = type("CF", (), {"is_valid": False})()

    def tearDown(self):
        self.app._db.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_json_selection_applied(self):
        self.app._db.set_user_json_setting(
            self.uid, "graph_series_live_metrics", ["distraction", "sinking"]
        )
        self.app._restore_graph_series(self.uid)
        self.assertTrue(self.graph.is_visible("distraction"))
        self.assertTrue(self.graph.is_visible("sinking"))
        self.assertFalse(self.graph.is_visible("shamatha_score"))

    def test_migrates_legacy_toggles_when_no_json(self):
        self.app._db.set_user_setting(self.uid, "toggle_native_attention", "True")
        self.app._db.set_user_setting(self.uid, "toggle_shamatha_score", "False")
        self.app._restore_graph_series(self.uid)
        self.assertTrue(self.graph.is_visible("native_attention"))
        self.assertFalse(self.graph.is_visible("shamatha_score"))

    def test_first_run_defaults_when_nothing_saved(self):
        self.app._restore_graph_series(self.uid)
        self.assertTrue(self.graph.is_visible("shamatha_score"))  # the only default
        self.assertFalse(self.graph.is_visible("distraction"))

    def test_toggle_flips_graph_visibility_directly(self):
        self.app._restore_graph_series(self.uid)  # shamatha on by default
        self.app._fullscreen_overlay = None  # _refresh_fullscreen_legend no-op
        self.app._on_series_toggle("distraction")
        self.assertTrue(self.graph.is_visible("distraction"))
        self.app._on_series_toggle("shamatha_score")
        self.assertFalse(self.graph.is_visible("shamatha_score"))
