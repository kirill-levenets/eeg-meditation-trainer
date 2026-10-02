"""File copies write only the data, and atomically: Android app storage refuses the SELinux label copy (#63)."""

import errno
import os
import shutil
import sqlite3
from unittest.mock import MagicMock

import pytest

import app.ui.app_manager as am
from app.storage.backup import make_backup, restore_backup
from app.storage.database import DatabaseManager
from app.ui.app_manager import EEGMeditationApp


@pytest.fixture
def android_xattrs(monkeypatch):
    """copy2's metadata step as on the phone: setting the SELinux label raises EACCES, which Python 3.11 doesn't ignore (3.12 does)."""

    def _py311_copyxattr(src, dst, *, follow_symlinks=True):
        raise PermissionError(errno.EACCES, "Permission denied", str(dst))

    monkeypatch.setattr(shutil, "_copyxattr", _py311_copyxattr)


def _db_with_user(path, name: str) -> None:
    db = DatabaseManager(db_path=str(path))
    db.create_user(name)
    db.close()


def _users(path) -> list[str]:
    conn = sqlite3.connect(str(path))
    try:
        return [r[0] for r in conn.execute("SELECT name FROM users")]
    finally:
        conn.close()


@pytest.fixture
def backup_and_live(tmp_path):
    backup, live = tmp_path / "backup.db", tmp_path / "live.db"
    _db_with_user(backup, "from-backup")
    _db_with_user(live, "live")
    return backup, live


# --- the copy itself ---------------------------------------------------------------------------------------------

def test_restore_succeeds_where_the_selinux_label_cannot_be_copied(android_xattrs, backup_and_live):
    backup, live = backup_and_live
    restore_backup(str(backup), str(live))
    assert _users(live) == ["from-backup"]


def test_a_failed_restore_copy_leaves_the_live_db_unchanged_and_no_temp_file(monkeypatch, backup_and_live):
    backup, live = backup_and_live
    before = live.read_bytes()

    def _disk_full_midway(fsrc, fdst, *a, **k):
        fdst.write(fsrc.read(1024))
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(shutil, "copyfileobj", _disk_full_midway)
    with pytest.raises(OSError):
        restore_backup(str(backup), str(live))
    assert live.read_bytes() == before
    assert sorted(p.name for p in live.parent.iterdir()) == ["backup.db", "live.db"]


def test_restore_removes_the_replaced_dbs_wal_and_shm(backup_and_live):
    backup, live = backup_and_live
    wal, shm = live.with_name("live.db-wal"), live.with_name("live.db-shm")
    wal.write_bytes(b"stale wal of the replaced db")
    shm.write_bytes(b"stale shm of the replaced db")
    restore_backup(str(backup), str(live))
    assert not wal.exists() and not shm.exists()
    assert _users(live) == ["from-backup"]


def test_backup_succeeds_where_the_selinux_label_cannot_be_copied(android_xattrs, tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "live.db"))
    try:
        db.create_user("someone")
        make_backup(db, str(tmp_path / "out" / "backup.db"))
    finally:
        db.close()
    assert _users(tmp_path / "out" / "backup.db") == ["someone"]


def test_db_migration_copies_without_reporting_where_the_label_cannot_be_copied(android_xattrs, tmp_path):
    from app import crash_handler
    from app.config import _maybe_migrate_desktop_db

    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    (old_dir / "meditation.db").write_bytes(b"OLD")
    crash_handler._PRE_APP_ERRORS.clear()
    _maybe_migrate_desktop_db(new_dir=str(new_dir), legacy_dirs=[str(old_dir)])
    assert (new_dir / "meditation.db").read_bytes() == b"OLD"
    assert crash_handler._PRE_APP_ERRORS == []


# --- the temp copy of the picked file (_restore_candidate.db) never outlives the restore ---------------------

def _restore_app(tmp_path, monkeypatch) -> EEGMeditationApp:
    monkeypatch.setattr(am.APP, "DB_PATH", str(tmp_path / "meditation.db"))
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = MagicMock()
    app._db.get_record_counts.return_value = {"users": 1, "sessions": 3}
    app._confirm_action = MagicMock()
    app._do_restore_and_restart = MagicMock()
    return app


def _candidate(tmp_path, valid: bool = True):
    path = tmp_path / "_restore_candidate.db"
    if valid:
        _db_with_user(path, "from-backup")
    else:
        path.write_bytes(b"not a database")
    return path


def test_an_invalid_picked_file_discards_the_temp_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(am, "report_soft_error", MagicMock())
    app = _restore_app(tmp_path, monkeypatch)
    cand = _candidate(tmp_path, valid=False)
    app._confirm_restore(str(cand), discard_after=True)
    assert not cand.exists()
    am.report_soft_error.assert_called_once()


def test_cancelling_the_restore_confirm_discards_the_temp_copy(tmp_path, monkeypatch):
    app = _restore_app(tmp_path, monkeypatch)
    cand = _candidate(tmp_path)
    app._confirm_restore(str(cand), discard_after=True)
    app._confirm_action.call_args.kwargs["on_cancel"]()
    assert not cand.exists()
    app._do_restore_and_restart.assert_not_called()


def test_confirming_the_restore_restores_then_discards_the_temp_copy(tmp_path, monkeypatch):
    app = _restore_app(tmp_path, monkeypatch)
    cand = _candidate(tmp_path)
    present_during_restore = []
    app._do_restore_and_restart.side_effect = lambda path: present_during_restore.append(os.path.exists(path))
    app._confirm_restore(str(cand), discard_after=True)
    app._confirm_action.call_args.args[3]()  # the user confirms
    app._do_restore_and_restart.assert_called_once_with(str(cand))
    assert present_during_restore == [True]
    assert not cand.exists()


def test_a_desktop_restore_never_deletes_the_users_own_file(tmp_path, monkeypatch):
    app = _restore_app(tmp_path, monkeypatch)
    picked = tmp_path / "my_backup.db"
    _db_with_user(picked, "from-backup")
    app._confirm_restore(str(picked))
    app._confirm_action.call_args.args[3]()
    app._confirm_action.call_args.kwargs["on_cancel"]()
    assert picked.exists()


def test_a_failed_read_of_the_picked_file_discards_the_partial_temp_copy(tmp_path, monkeypatch):
    app = _restore_app(tmp_path, monkeypatch)
    cand = tmp_path / "_restore_candidate.db"

    def _partial_read(uri, dest):
        with open(dest, "wb") as f:
            f.write(b"half a file")
        return False

    monkeypatch.setattr(am._saf, "read_uri_to_file", _partial_read)
    monkeypatch.setattr(am, "report_soft_error", MagicMock())
    monkeypatch.setattr(am.Clock, "schedule_once", lambda fn, *a: fn(0))
    app._restore_from_uri_worker("content://picked/backup")
    assert not cand.exists()
    am.report_soft_error.assert_called_once()


# --- review round: the copy keeps copy2's useful semantics; a failed restore keeps one live DB --------------------

def _open_fds() -> int:
    return len(os.listdir("/proc/self/fd"))


def test_copying_a_missing_source_leaks_no_fd_and_leaves_no_temp_file(tmp_path):
    from app.storage.fileops import copy_file_atomic

    fds = _open_fds()
    with pytest.raises(FileNotFoundError):
        copy_file_atomic(str(tmp_path / "gone.db"), str(tmp_path / "dst.db"))
    assert _open_fds() == fds
    assert list(tmp_path.iterdir()) == []


def test_copying_onto_a_symlink_writes_through_to_its_target(tmp_path):
    from app.storage.fileops import copy_file_atomic

    real, link, src = tmp_path / "real.db", tmp_path / "link.db", tmp_path / "src.db"
    real.write_bytes(b"old")
    link.symlink_to(real)
    src.write_bytes(b"new")
    copy_file_atomic(str(src), str(link))
    assert link.is_symlink() and real.read_bytes() == b"new"


def test_the_copy_keeps_the_sources_permission_bits(tmp_path):
    from app.storage.fileops import copy_file_atomic

    src = tmp_path / "export.csv"
    src.write_bytes(b"a,b\n")
    src.chmod(0o644)
    copy_file_atomic(str(src), str(tmp_path / "out.csv"))
    assert (tmp_path / "out.csv").stat().st_mode & 0o777 == 0o644


def test_a_backup_onto_the_live_database_is_refused(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "meditation.db"))
    try:
        db.create_user("someone")
        with pytest.raises(OSError):
            make_backup(db, str(tmp_path / "meditation.db"))
        db.create_user("after")  # the open connection still writes to the file on disk
    finally:
        db.close()
    assert sorted(_users(tmp_path / "meditation.db")) == ["after", "someone"]


def test_a_failed_restore_keeps_the_same_live_db_for_everything_holding_it(tmp_path, monkeypatch):
    monkeypatch.setattr(am.APP, "DB_PATH", str(tmp_path / "meditation.db"))
    db = DatabaseManager(db_path=str(tmp_path / "meditation.db"))
    uid = db.create_user("someone")
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = db
    app._session_pipeline_live = lambda: False
    monkeypatch.setattr(am, "report_soft_error", MagicMock())

    def _disk_full(*_a):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(am, "restore_backup", _disk_full)
    try:
        app._do_restore_and_restart(str(tmp_path / "backup.db"))
        assert app._db is db  # the settings store and any other holder keep a working reference
        db.set_user_setting(uid, "threshold", "70")
        assert db.get_user_setting(uid, "threshold") == "70"
    finally:
        db.close()
    am.report_soft_error.assert_called_once()
