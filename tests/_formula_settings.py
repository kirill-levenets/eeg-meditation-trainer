"""A FormulaSettings wired to an app built with __new__, as build() wires it; any dependency can be given instead."""
from unittest.mock import MagicMock

from app.ui.formula_settings import FormulaSettings


def make_formula_settings(app, **deps) -> FormulaSettings:
    """The app's db, Settings formula section, live graph and formula slots (mocks for the ones it lacks), and its user,
    scoring lock and sound metric, read when they are needed."""
    def attr(name):
        value = getattr(app, name, None)
        return MagicMock() if value is None else value

    live_screen = getattr(app, "_live_screen", None)
    settings_screen = getattr(app, "_settings_screen", None)
    defaults = {"user_id": lambda: app._current_user_id, "require_user": lambda action: app._require_user(action),
                "scoring_locked": lambda doing: app._scoring_locked(doing), "audio_key": lambda: app._audio_metric_key,
                "confirm_saved_delete": lambda *a: app._confirm_saved_delete(*a)}
    return FormulaSettings(attr("_db"), MagicMock() if settings_screen is None else settings_screen.formulas,
                           MagicMock() if live_screen is None else live_screen.graph, app._formulas,
                           **{**defaults, **deps})
