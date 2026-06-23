import unittest

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
