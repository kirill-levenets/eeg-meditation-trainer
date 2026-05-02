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
