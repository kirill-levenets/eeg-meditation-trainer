"""The app's AudioMetric wired to an app built with __new__, as build() wires it: its context reads the app when used
(tests/_context.py); the formula slots, the program run and the Settings screen are the app's at construction (a slot
set, no program running and a stand-in for the ones it lacks)."""
from unittest.mock import MagicMock

from app.metrics.formula_slots import FormulaSlots
from app.ui.audio_metric import AudioMetric
from tests._context import make_context
from tests._program_run import make_run


def make_audio_metric(app, **ctx_fields) -> AudioMetric:
    def attr(name, default):
        value = getattr(app, name, None)
        return default() if value is None else value

    return AudioMetric(make_context(app, **ctx_fields), attr("_formulas", FormulaSlots), attr("_program_run", make_run),
                       attr("_settings_screen", MagicMock))
