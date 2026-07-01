"""The startup user gate: the app must resolve a CONCRETE user or prompt —
it must never continue usable with no resolved user (the #29 root cause).

`resolve_startup_user(db)` returns the uid to restore, or None meaning "you
must show the blocking user-select gate". The old code gated the setup UI on
`get_all_users()` emptiness, which let "users exist but last_user_id doesn't
resolve" (reinstall / restored DB / deleted active profile / corrupt setting)
slip through into a usable-but-unset state.
"""
import os
import tempfile

from app.storage.database import DatabaseManager
from app.ui.app_manager import resolve_startup_user


def _fresh() -> DatabaseManager:
    return DatabaseManager(db_path=os.path.join(tempfile.mkdtemp(), "t.db"))


def test_resolves_uid_when_last_user_is_valid():
    db = _fresh()
    uid = db.create_user("Kirill")
    db.set_setting("last_user_id", str(uid))
    assert resolve_startup_user(db) == uid


def test_none_on_empty_db():
    assert resolve_startup_user(_fresh()) is None


def test_none_when_users_exist_but_no_last_user_setting():
    db = _fresh()
    db.create_user("Kirill")  # user exists, but last_user_id never set
    assert resolve_startup_user(db) is None


def test_none_when_last_user_points_to_deleted_user():
    db = _fresh()
    db.create_user("Kirill")
    db.set_setting("last_user_id", "999")  # stale id, no such user
    assert resolve_startup_user(db) is None


def test_none_when_last_user_setting_is_corrupt():
    db = _fresh()
    db.create_user("Kirill")
    db.set_setting("last_user_id", "not-an-int")
    assert resolve_startup_user(db) is None
