"""A closed DB connection during app actions must NOT silently no-op.

Repro of the field bug: after a restore (or an Android stop/resume that closed
the DB) the app keeps running with _conn=None, so set_setting silently drops
every write and get_setting returns None — settings edits vanish with no error.
The DB must self-heal (reconnect) while the app is alive, and raise (never
silently no-op) once it is deliberately shutting down.
"""
import os
import tempfile

import pytest

from app.storage.database import DatabaseManager


def _fresh() -> DatabaseManager:
    d = tempfile.mkdtemp()
    return DatabaseManager(db_path=os.path.join(d, "t.db"))


def test_global_setting_survives_a_closed_connection():
    db = _fresh()
    db.close()  # _conn = None while the app is still running
    db.set_setting("theme", "Dark Green")
    assert db.get_setting("theme") == "Dark Green"


def test_user_setting_survives_a_closed_connection():
    db = _fresh()
    uid = db.create_user("Kirill")
    db.close()
    db.set_user_setting(uid, "threshold", "70")
    assert db.get_user_setting(uid, "threshold") == "70"


def test_use_after_shutdown_raises_instead_of_silent_noop():
    db = _fresh()
    db.mark_shutting_down()
    db.close()
    with pytest.raises(RuntimeError):
        db.set_setting("theme", "Dark Green")
