import os
import tempfile
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
