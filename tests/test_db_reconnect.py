"""A closed DB connection during app actions must NOT silently no-op.

Repro of the field bug: after a restore (or an Android stop/resume that closed
the DB) the app keeps running with _conn=None, so writes silently dropped and
reads crashed. The DB must self-heal (reconnect) while the app is alive — for
writes, reads AND settings — and, once deliberately shutting down, degrade to a
benign no-op (not a crash), so teardown / the post-restore relaunch window can't
resurrect or clobber the DB.
"""
import os
import shutil
import tempfile

import pytest

from app.storage.database import DatabaseManager

_TMP_DIRS: list[str] = []


def _fresh() -> DatabaseManager:
    d = tempfile.mkdtemp()
    _TMP_DIRS.append(d)
    return DatabaseManager(db_path=os.path.join(d, "t.db"))


@pytest.fixture(autouse=True)
def _cleanup_tmp_dirs():
    yield
    while _TMP_DIRS:
        shutil.rmtree(_TMP_DIRS.pop(), ignore_errors=True)


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


def test_direct_table_read_self_heals_after_close_while_alive():
    # #3: reconnect must cover direct-table reads, not just get/set_setting.
    db = _fresh()
    uid = db.create_user("Kirill")
    db._conn.execute(
        "INSERT INTO sessions (user_id, date_time, duration) VALUES (?, '2026-07-01', 60)",
        (uid,),
    )
    db._conn.commit()
    db.close()  # closed while alive (not shutting down)
    rows = db.get_all_sessions(user_id=uid)  # must reconnect, not AttributeError
    assert len(rows) == 1
    assert db.get_all_users()[0]["name"] == "Kirill"


def test_use_after_shutdown_is_a_benign_noop_not_a_crash():
    # #6: once shutting down, access degrades to a no-op — never a crash dialog,
    # and never a reconnect that would resurrect / clobber the DB.
    db = _fresh()
    db.mark_shutting_down()
    db.close()
    db.set_setting("theme", "Dark Green")     # must not raise
    assert db.get_setting("theme") is None    # no reconnect while shutting down
    assert db.get_all_sessions() == []
