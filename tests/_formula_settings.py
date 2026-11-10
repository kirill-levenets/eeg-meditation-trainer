"""A FormulaSettings with mock dependencies for the formula tests; any of them, or a context field, can be given."""
from unittest.mock import MagicMock

from app.metrics.formula_slots import FormulaSlots
from app.ui.formula_settings import FormulaSettings
from tests._context import context_fields, stub_context


def make_formula_settings(db=None, uid=None, *, formulas=None, **deps) -> FormulaSettings:
    """`uid` is the active profile, the one require_user lets through; its formula slots are empty unless given, and
    no slot is locked by a session's scoring."""
    ctx = stub_context(db=MagicMock() if db is None else db, user_id=lambda: uid, **context_fields(deps))
    return FormulaSettings(ctx, MagicMock(), MagicMock(), formulas or FormulaSlots(),
                           **{"scoring_locked": lambda _key, _doing: False, **deps})
