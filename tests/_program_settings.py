"""A ProgramSettings with mock dependencies for the program tests; any of them can be given instead."""
from unittest.mock import MagicMock

from app.ui.program_settings import ProgramSettings


def make_programs(db=None, uid=None, *, timer_section=None, live_screen=None, session_manager=None,
                  **deps) -> ProgramSettings:
    """`uid` is the active profile, the one require_user lets through."""
    defaults = {"user_id": lambda: uid, "require_user": lambda _action: uid, "confirm": MagicMock(),
                "info": MagicMock(), "confirm_saved_delete": MagicMock(), "show_saved_series": MagicMock(),
                "save_settings": MagicMock()}
    return ProgramSettings(MagicMock() if db is None else db, timer_section or MagicMock(),
                           live_screen or MagicMock(), session_manager or MagicMock(), **{**defaults, **deps})
