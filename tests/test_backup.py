import os
import sqlite3
import tempfile

import pytest

from app.storage.backup import (
    BackupValidationError,
    make_backup,
    restore_backup,
    validate_backup,
)
from app.storage.database import DatabaseManager


@pytest.fixture
def db():
    path = os.path.join(tempfile.gettempdir(), "test_backup_src.db")
    if os.path.exists(path):
        os.remove(path)
    db = DatabaseManager(db_path=path)
    db.create_user("Alice")
    yield db
    db.close()
    if os.path.exists(path):
        os.remove(path)


def test_make_backup_creates_valid_sqlite(db, tmp_path):
    target = tmp_path / "out.db"
    make_backup(db, str(target))
    assert target.exists()
    conn = sqlite3.connect(str(target))
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "users" in tables
    assert "sessions" in tables
    conn.close()


def test_make_backup_uses_temp_beside_live_then_copies(tmp_path):
    # SQLite can't open a DB on Android FUSE storage, so make_backup writes a temp
    # copy beside the live DB and byte-copies it out. Guard: target lands in its own
    # dir and no temp .db residue is left beside the live DB.
    live_dir = tmp_path / "internal"
    live_dir.mkdir()
    live = live_dir / "live.db"
    db = DatabaseManager(db_path=str(live))
    db.create_user("Bob")
    try:
        target = tmp_path / "sdcard" / "out.db"
        make_backup(db, str(target))
        assert target.exists()
        ok, msg = validate_backup(str(target))
        assert ok, msg
        stray = [p.name for p in live_dir.iterdir()
                 if p.suffix == ".db" and p.name != "live.db"]
        assert stray == [], f"temp residue left beside live DB: {stray}"
    finally:
        db.close()


def test_validate_backup_accepts_valid_db(db, tmp_path):
    target = tmp_path / "out.db"
    make_backup(db, str(target))
    ok, msg = validate_backup(str(target))
    assert ok, msg


def test_validate_backup_rejects_non_sqlite(tmp_path):
    bad = tmp_path / "garbage.db"
    bad.write_bytes(b"not-a-sqlite-file")
    ok, msg = validate_backup(str(bad))
    assert not ok
    assert msg


def test_validate_backup_rejects_sqlite_without_schema(tmp_path):
    bad = tmp_path / "empty.db"
    conn = sqlite3.connect(str(bad))
    conn.execute("CREATE TABLE other (id INTEGER)")
    conn.commit()
    conn.close()
    ok, msg = validate_backup(str(bad))
    assert not ok
    assert "users" in msg.lower() or "sessions" in msg.lower()


def test_validate_backup_rejects_missing_path(tmp_path):
    ok, msg = validate_backup(str(tmp_path / "does_not_exist.db"))
    assert not ok


def test_restore_backup_replaces_target_file(db, tmp_path):
    backup = tmp_path / "out.db"
    make_backup(db, str(backup))

    target = tmp_path / "live.db"
    target.write_bytes(b"OLD CONTENTS")

    restore_backup(str(backup), str(target))
    conn = sqlite3.connect(str(target))
    rows = conn.execute("SELECT name FROM users").fetchall()
    conn.close()
    assert ("Alice",) in rows


def test_restore_backup_raises_on_invalid_source(tmp_path):
    bad = tmp_path / "garbage.db"
    bad.write_bytes(b"not-a-db")
    target = tmp_path / "live.db"
    with pytest.raises(BackupValidationError):
        restore_backup(str(bad), str(target))
