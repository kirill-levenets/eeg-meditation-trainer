"""A ProgramSettings with mock dependencies for the program tests; any of them, or a context field, can be given."""
from unittest.mock import MagicMock

from app.ui.program_settings import ProgramSettings
from tests._context import context_fields, stub_context


def make_programs(db=None, uid=None, *, timer_section=None, live_screen=None, session_manager=None,
                  **deps) -> ProgramSettings:
    """`uid` is the active profile, the one require_user lets through."""
    ctx = stub_context(db=MagicMock() if db is None else db, user_id=lambda: uid, **context_fields(deps))
    return ProgramSettings(ctx, timer_section or MagicMock(), live_screen or MagicMock(),
                           session_manager or MagicMock(), **{"show_saved_series": MagicMock(), **deps})
