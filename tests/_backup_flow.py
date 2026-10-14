"""A BackupFlow with mock dependencies for the backup/restore tests; any of them can be given instead."""
from unittest.mock import MagicMock

from app.ui.backup_flow import BackupFlow


def make_flow(db=None, settings_screen=None, **deps) -> BackupFlow:
    defaults = {"user_name": lambda: None, "save_settings": MagicMock(), "checkpoint": MagicMock(),
                "refused_while_session_runs": MagicMock(return_value=False), "confirm": MagicMock(),
                "info": MagicMock(), "on_db_replaced": MagicMock()}
    return BackupFlow(MagicMock() if db is None else db, settings_screen or MagicMock(), **{**defaults, **deps})
