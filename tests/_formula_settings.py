"""A FormulaSettings wired to an app built with __new__, as build() wires it; any dependency, or a context field, can
be given instead."""
from unittest.mock import MagicMock

from app.ui.formula_settings import FormulaSettings
from tests._context import context_fields, make_context


def make_formula_settings(app, **deps) -> FormulaSettings:
    """The app's db, Settings formula section, live graph and formula slots (mocks for the ones it lacks), and its user
    and scoring lock, read when they are needed."""
    live_screen = getattr(app, "_live_screen", None)
    settings_screen = getattr(app, "_settings_screen", None)
    ctx = make_context(app, **context_fields(deps))
    defaults = {"scoring_locked": lambda key, doing: app._audio_metric.formula_scoring_locked(key, doing)}
    return FormulaSettings(ctx, MagicMock() if settings_screen is None else settings_screen.formulas,
                           MagicMock() if live_screen is None else live_screen.graph, app._formulas,
                           **{**defaults, **deps})
