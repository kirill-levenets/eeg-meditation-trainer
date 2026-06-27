"""DB backup and restore — file-level operations isolated from UI."""

import os
import shutil
import sqlite3
import tempfile

from app.logger import logger


class BackupValidationError(Exception):
    """Raised when a candidate backup file fails schema validation."""


def online_backup_to_tempfile(db) -> str:
    """Run SQLite's online backup into a temp .db beside the live DB; caller deletes it.

    SQLite can't open/lock a DB on Android FUSE storage (/sdcard) — it returns
    SQLITE_CANTOPEN. The temp file lives in internal storage (where the live DB is,
    which supports the locks SQLite needs); callers byte-copy or stream it to the
    final destination, which works on /sdcard and content:// URIs.
    """
    live_dir = os.path.dirname(db._db_path) or "."
    fd, tmp_path = tempfile.mkstemp(suffix=".db", dir=live_dir)
    os.close(fd)
    try:
        target_conn = sqlite3.connect(tmp_path)
        try:
            db._conn.backup(target_conn)
        finally:
            target_conn.close()
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            logger.warning(f"Could not remove temp backup {tmp_path}")
        raise
    return tmp_path


def make_backup(db, target_path: str) -> None:
    """Write a transaction-safe copy of the live DB to `target_path`.

    Uses SQLite's online backup API so concurrent writes from the live
    DB don't corrupt the result.
    """
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    tmp_path = online_backup_to_tempfile(db)
    try:
        shutil.copy2(tmp_path, target_path)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            logger.warning(f"Could not remove temp backup {tmp_path}")
    logger.info(f"Backup written: {target_path}")


def validate_backup(source_path: str) -> tuple[bool, str]:
    """Check that `source_path` is a valid SQLite backup of this app.

    Returns (ok, message). On failure, message describes why.
    """
    if not os.path.isfile(source_path):
        return False, f"File not found: {source_path}"
    try:
        conn = sqlite3.connect(source_path)
        try:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        return False, f"Not a valid SQLite file: {e}"

    missing = {"users", "sessions"} - tables
    if missing:
        return False, f"Backup is missing required tables: {sorted(missing)}"
    return True, "ok"


def restore_backup(source_path: str, target_path: str) -> None:
    """Validate `source_path` and copy it over `target_path`.

    Caller is responsible for closing any active DB connection on
    `target_path` before invoking this function.

    Raises:
        BackupValidationError: if the source file is not a valid backup.
    """
    ok, msg = validate_backup(source_path)
    if not ok:
        raise BackupValidationError(msg)
    shutil.copy2(source_path, target_path)
    logger.info(f"Restored {source_path} -> {target_path}")
