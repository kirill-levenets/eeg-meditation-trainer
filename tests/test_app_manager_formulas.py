import os
import tempfile
import types
import unittest

from app.storage.database import DatabaseManager
from app.ui.app_manager import FORMULA_KEYS, EEGMeditationApp


class TestMultiFormulaTick(unittest.TestCase):
    def _app(self):
        app = EEGMeditationApp.__new__(EEGMeditationApp)
        app._init_formula_slots()
        return app

    def test_three_independent_slots(self):
        app = self._app()
        self.assertEqual(len(app._formula_slots), 3)
        self.assertEqual(tuple(FORMULA_KEYS), ("custom_formula", "custom_formula_2", "custom_formula_3"))
        app._formula_slots[0].set_formula("avg(alpha1, 3)")
        app._formula_slots[1].set_formula("avg(alpha1, 3)")
        for v in (10.0, 20.0, 30.0):
            app._formula_slots[0].push_variables({"alpha1": v})
        app._formula_slots[1].push_variables({"alpha1": 99.0})
        self.assertNotEqual(
            app._formula_slots[0].evaluate({"alpha1": 0.0}),
            app._formula_slots[1].evaluate({"alpha1": 0.0}),
        )

    def test_formula_for_key(self):
        app = self._app()
        self.assertIs(app._formula_for_key("custom_formula"), app._formula_slots[0])
        self.assertIs(app._formula_for_key("custom_formula_3"), app._formula_slots[2])
        self.assertIsNone(app._formula_for_key("shamatha_score"))


class TestFormulaPersistence(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.gettempdir(), "f4_persist.db")
        if os.path.exists(self.path):
            os.remove(self.path)
        self.app = EEGMeditationApp.__new__(EEGMeditationApp)
        self.app._init_formula_slots()
        self.app._db = DatabaseManager(db_path=self.path)
        self.uid = self.app._db.create_user("A")

    def tearDown(self):
        self.app._db.close()
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_active_formulas_round_trip(self):
        self.app._apply_active_formulas([
            {"name": "Ratio", "formula": "alpha + beta"},
            {"name": "Med", "formula": "meditation_score"},
        ])
        self.app._persist_active_formulas(self.uid)

        fresh = EEGMeditationApp.__new__(EEGMeditationApp)
        fresh._init_formula_slots()
        fresh._db = self.app._db
        fresh._apply_active_formulas(
            fresh._db.get_user_json_setting(self.uid, "active_formulas")
        )
        self.assertEqual(fresh._formula_names[0], "Ratio")
        self.assertTrue(fresh._formula_slots[0].is_valid)
        self.assertEqual(fresh._formula_slots[0].formula, "alpha + beta")
        self.assertFalse(fresh._formula_slots[2].is_valid)

    def test_legacy_single_formula_migrates_to_slot1(self):
        self.app._db.set_user_setting(self.uid, "custom_formula", "alpha / (beta + 1)")
        active = self.app._read_active_formulas_with_migration(self.uid)
        self.assertEqual(active[0]["formula"], "alpha / (beta + 1)")
        self.assertEqual(active[0]["name"], "Custom 1")


class TestAudioDriveKey(unittest.TestCase):
    def _app(self):
        app = EEGMeditationApp.__new__(EEGMeditationApp)
        app._init_formula_slots()
        return app

    def test_audio_falls_back_to_shamatha_when_bound_slot_invalid(self):
        app = self._app()
        app._audio_metric_key = "custom_formula_2"   # slot 2 bound...
        app._audio_formula_index = 1                  # ...but slot 2 has no formula
        self.assertEqual(app._audio_drive_key(), "shamatha_score")
        app._formula_slots[1].set_formula("alpha + beta")  # now valid
        self.assertEqual(app._audio_drive_key(), "custom_formula_2")

    def test_audio_drive_key_passthrough_for_non_formula(self):
        app = self._app()
        app._audio_metric_key = "shamatha_score"
        self.assertEqual(app._audio_drive_key(), "shamatha_score")

    def test_index_tap_does_not_rebind_when_non_formula_active(self):
        # Tapping a slot button while a non-formula metric drives audio only
        # remembers the slot; it must not silently switch the live key.
        app = self._app()
        app._audio_metric_key = "shamatha_score"
        app._on_audio_formula_index(1)
        self.assertEqual(app._audio_metric_key, "shamatha_score")
        self.assertEqual(app._audio_formula_index, 1)


class _FakeGraph:
    def __init__(self):
        self._vis = {}
        self._names = {}

    def set_visible(self, key, v):
        self._vis[key] = v

    def is_visible(self, key):
        return self._vis.get(key, False)

    def set_series_name(self, key, name):
        self._names[key] = name


class _StubDiary:
    def __init__(self):
        self.series = None
        self.names = None

    def set_session_formulas(self, series, names):
        self.series = series
        self.names = names


class TestSessionFormulaSaveAndReplay(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.gettempdir(), "f4_replay.db")
        if os.path.exists(self.path):
            os.remove(self.path)
        self.app = EEGMeditationApp.__new__(EEGMeditationApp)
        self.app._init_formula_slots()
        self.app._db = DatabaseManager(db_path=self.path)
        self.app._current_user_id = self.app._db.create_user("A")
        self.app._audio_metric_key = "shamatha_score"
        self.app._live_screen = types.SimpleNamespace(graph=_FakeGraph())
        self.app._diary_screen = _StubDiary()

    def tearDown(self):
        self.app._db.close()
        if os.path.exists(self.path):
            os.remove(self.path)

    def _seed_session(self) -> int:
        cf = self.app._session_custom_formulas_json()
        sid = self.app._db.save_session(
            {"duration": 1}, user_id=self.app._current_user_id, custom_formulas=cf
        )
        self.app._db.save_metrics_batch(sid, [{
            "timestamp": 0.5, "alpha1": 100, "alpha2": 50, "beta1": 10, "beta2": 5,
        }])
        return sid

    def test_record_includes_visible_and_drove_audio(self):
        self.app._formula_slots[0].set_formula("alpha + beta")
        self.app._formula_names[0] = "Ratio"
        self.app._live_screen.graph.set_visible("custom_formula", True)
        self.app._audio_metric_key = "custom_formula"
        import json
        rec = json.loads(self.app._session_custom_formulas_json())
        self.assertEqual(rec[0]["name"], "Ratio")
        self.assertEqual(rec[0]["formula"], "alpha + beta")
        self.assertTrue(rec[0]["visible"])
        self.assertTrue(rec[0]["drove_audio"])

    def test_replay_recomputes_from_stored_defs(self):
        self.app._formula_slots[0].set_formula("alpha + beta")
        self.app._formula_names[0] = "Ratio"
        sid = self._seed_session()
        # Mutate today's slot — replay must ignore it and use the stored def.
        self.app._formula_slots[0].set_formula("delta")
        session = self.app._db.get_session(sid)
        self.app._inject_session_formulas(sid, session)
        injected = self.app._diary_screen.series[FORMULA_KEYS[0]]
        from app.metrics.custom_formula import CustomFormulaEvaluator
        ev = CustomFormulaEvaluator()
        ev.set_formula("alpha + beta")
        expected = self.app._db.recompute_formula_series(sid, {FORMULA_KEYS[0]: ev})
        self.assertEqual(injected, expected[FORMULA_KEYS[0]])
        self.assertAlmostEqual(injected[0], 165.0, places=3)
        self.assertEqual(self.app._diary_screen.names[FORMULA_KEYS[0]], "Ratio")

    def test_replay_no_formulas_is_empty(self):
        sid = self._seed_session()  # no valid slots
        session = self.app._db.get_session(sid)
        self.app._inject_session_formulas(sid, session)
        self.assertEqual(self.app._diary_screen.series, {})

    def test_replay_tolerates_malformed_json(self):
        sid = self.app._db.save_session(
            {"duration": 1}, user_id=self.app._current_user_id, custom_formulas="{not json"
        )
        session = self.app._db.get_session(sid)
        self.app._inject_session_formulas(sid, session)  # must not raise
        self.assertEqual(self.app._diary_screen.series, {})


class TestAssignSavedToSlot(unittest.TestCase):
    def _app(self):
        app = EEGMeditationApp.__new__(EEGMeditationApp)
        app._init_formula_slots()
        app._current_user_id = None
        app._live_screen = types.SimpleNamespace(graph=_FakeGraph())
        app._settings_screen = types.SimpleNamespace(
            set_formula_slot=lambda *a, **k: None,
            set_formula_slot_status=lambda *a, **k: None,
        )
        return app

    def test_assign_saved_formula_to_slot(self):
        app = self._app()
        app._assign_saved_to_slot(0, {"name": "Ratio", "formula": "alpha + beta"})
        self.assertTrue(app._formula_slots[0].is_valid)
        self.assertEqual(app._formula_names[0], "Ratio")
        self.assertTrue(app._live_screen.graph.is_visible("custom_formula"))

    def test_first_empty_slot(self):
        app = self._app()
        self.assertEqual(app._first_empty_slot(), 0)
        app._formula_slots[0].set_formula("alpha")
        self.assertEqual(app._first_empty_slot(), 1)
        for ev in app._formula_slots:
            ev.set_formula("alpha")
        self.assertEqual(app._first_empty_slot(), 0)  # all full → slot 0
