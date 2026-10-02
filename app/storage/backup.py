"""DB backup and restore — file-level operations isolated from UI."""

import errno
import os
import re
import sqlite3
import tempfile
from datetime import datetime

from app.logger import logger
from app.storage.fileops import copy_file_atomic, discard_file

# Path separators, whitespace, control characters and the characters FAT/exFAT storage rejects.
_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\s\x00-\x1f]+')
# Keeps the name far below the 255-byte filename limit even for multi-byte (e.g. Cyrillic) names.
_MAX_NAME_CHARS = 40


class BackupValidationError(Exception):
    """Raised when a candidate backup file fails schema validation."""


def backup_filename(user_name: str | None, now: datetime) -> str:
    """Suggested backup name: profile and local time up front, where a narrow save field still shows them."""
    stamp = now.strftime("%Y-%m-%d_%H-%M")
    user = _UNSAFE_FILENAME_CHARS.sub("_", user_name or "")[:_MAX_NAME_CHARS].strip("._")
    return f"eeg_backup_{user}_{stamp}.db" if user else f"eeg_backup_{stamp}.db"


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
        discard_file(tmp_path)
        raise
    return tmp_path


def make_backup(db, target_path: str) -> None:
    """Write a transaction-safe copy of the live DB to `target_path`.

    Uses SQLite's online backup API so concurrent writes from the live
    DB don't corrupt the result.
    """
    if os.path.realpath(target_path) == os.path.realpath(db._db_path):
        # Replacing the live file would leave the open connection writing to the swapped-out copy.
        raise OSError(errno.EINVAL, "Choose another name: this is the app's live database", target_path)
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    tmp_path = online_backup_to_tempfile(db)
    try:
        copy_file_atomic(tmp_path, target_path)
    finally:
        discard_file(tmp_path)
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
    copy_file_atomic(source_path, target_path)
    # SQLite would replay the replaced DB's leftover WAL onto the restored file.
    for suffix in ("-wal", "-shm"):
        discard_file(target_path + suffix)
    logger.info(f"Restored {source_path} -> {target_path}")
