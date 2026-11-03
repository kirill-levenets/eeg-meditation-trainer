"""A BackupFlow with mock dependencies for the backup/restore tests; any of them, or a context field, can be given."""
from unittest.mock import MagicMock

from app.ui.backup_flow import BackupFlow
from tests._context import context_fields, stub_context


def make_flow(db=None, settings_screen=None, **deps) -> BackupFlow:
    ctx = stub_context(db=MagicMock() if db is None else db, **context_fields(deps))
    defaults = {"user_name": lambda: None, "checkpoint": MagicMock(), "on_db_replaced": MagicMock()}
    return BackupFlow(ctx, settings_screen or MagicMock(), **{**defaults, **deps})
