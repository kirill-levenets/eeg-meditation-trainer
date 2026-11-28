import csv
import io
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

from app.config import APP
from app.eeg.band_spec import BAND_KEYS, group_powers
from app.logger import logger
from app.metrics.custom_formula import CustomFormulaEvaluator, compile_formula
from app.metrics.engine import MetricsEngine


class _NullCursor:
    """Empty cursor returned by the null connection while shutting down."""

    lastrowid = None
    rowcount = 0

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def __iter__(self):
        return iter(())


class _NullConnection:
    """No-op connection used only while the DB is shutting down / mid-restore:
    swallows writes and returns no rows, so late access from any path (reads,
    writes, the session's runner) is a benign no-op instead of crashing on a
    None connection or reopening-and-clobbering the freshly-restored DB file."""

    def execute(self, *_a, **_k):
        return _NullCursor()

    def executemany(self, *_a, **_k):
        return _NullCursor()

    def executescript(self, *_a, **_k):
        return None

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def backup(self, *_a, **_k):
        # A silent no-op here would produce an EMPTY backup file that a user
        # later restores over their data. Raise so the backup workers surface
        # a "Backup failed" diagnostic instead.
        raise sqlite3.OperationalError("database connection is closed (shutting down)")


_NULL_CONN = _NullConnection()


# A session row's stats columns and their defaults: the same for its insert and every checkpoint's update.
_SESSION_STAT_DEFAULTS: tuple[tuple[str, object], ...] = (
    ("duration", 0), ("threshold_used", 50), ("avg_meditation", 0), ("avg_shamatha", 0), ("max_meditation", 0),
    ("time_above_threshold", 0), ("longest_streak", 0), ("time_shamatha_90", 0),
    ("score_metric_key", ""), ("score_metric_name", ""), ("avg_score", None), ("score_targets", ""),
)
# A session row's fields besides its stats, with their defaults: its profile and name, set when it is inserted, and its
# formula lines, program and engine version, which every checkpoint writes when it has them.
_SESSION_FIELD_DEFAULTS: tuple[tuple[str, object], ...] = (
    ("user_id", None), ("session_name", ""), ("custom_formulas", ""), ("session_program", ""), ("engine_version", ""),
)
_SESSION_INSERT_ONLY = ("user_id", "session_name")

# Each table's columns after its key, in the order a new database has them (an older one, migrated, has the ones it
# lacked added at its end): the CREATE, the migration and the inserts are built from these.
_SESSION_COLUMNS: tuple[tuple[str, str], ...] = (
    ("user_id", "INTEGER DEFAULT NULL"), ("date_time", "TEXT NOT NULL"), ("duration", "INTEGER NOT NULL"),
    ("threshold_used", "INTEGER DEFAULT 50"), ("avg_meditation", "REAL DEFAULT 0"), ("avg_shamatha", "REAL DEFAULT 0"),
    ("max_meditation", "REAL DEFAULT 0"), ("time_above_threshold", "INTEGER DEFAULT 0"),
    ("longest_streak", "INTEGER DEFAULT 0"), ("notes", "TEXT DEFAULT ''"), ("tags", "TEXT DEFAULT ''"),
    ("mood_rating", "INTEGER DEFAULT 0"), ("engine_version", "TEXT DEFAULT ''"), ("session_name", "TEXT DEFAULT ''"),
    ("time_shamatha_90", "INTEGER DEFAULT 0"), ("custom_formulas", "TEXT DEFAULT ''"),
    ("session_program", "TEXT DEFAULT ''"),
    # Which metric the session was scored on (#51); '' marks rows from before, scored on meditation.
    ("score_metric_key", "TEXT DEFAULT ''"), ("score_metric_name", "TEXT DEFAULT ''"), ("avg_score", "REAL DEFAULT NULL"),
    ("score_targets", "TEXT DEFAULT ''"),  # the targets in force, in order
)

# (column, SQL type, the tick record's key it is written from, its value when the tick has none)
_METRIC_COLUMNS: tuple[tuple[str, str, str, object], ...] = (
    ("timestamp", "REAL NOT NULL", "timestamp", 0),
    *((f"{band}_raw", "REAL DEFAULT 0", band, 0) for band in BAND_KEYS),
    *((key, "REAL DEFAULT 0", key, 0) for key in (
        "alpha_norm", "beta_norm", "theta_norm", "delta_norm", "gamma_norm", "meditation_score", "distraction",
        "subtle_distraction", "sinking", "shamatha_score", "stability", "calmness", "native_attention",
        "native_meditation")),
    ("marker", "INTEGER DEFAULT 0", "marker", 0),
    # What the tick was scored on; NULL in rows from before it was recorded.
    ("score_key", "TEXT DEFAULT NULL", "score_key", None),
    ("score_value", "REAL DEFAULT NULL", "score_value", None),
    ("score_target", "REAL DEFAULT NULL", "score_target", None),
)


def _column_defs(columns: tuple[tuple, ...]) -> str:
    return ",\n".join(f"    {name} {sql}" for name, sql, *_ in columns)


_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
{_column_defs(_SESSION_COLUMNS)},
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
{_column_defs(_METRIC_COLUMNS)},
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""
# After the migration: an older database's sessions have no user_id until it adds the column.
_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_metrics_session ON metrics(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""
_METRICS_INSERT = (f"INSERT INTO metrics (session_id, {', '.join(col for col, *_ in _METRIC_COLUMNS)}) "
                   f"VALUES ({', '.join('?' * (len(_METRIC_COLUMNS) + 1))})")


class UserExistsError(Exception):
    """Raised by DatabaseManager.create_user when the name already exists."""

    def __init__(self, user_id: int, name: str) -> None:
        super().__init__(f"User '{name}' already exists (id={user_id})")
        self.user_id = user_id
        self.name = name


class DatabaseManager:
    """SQLite storage for sessions, metrics timeseries, and user profiles."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path: str = db_path or APP.DB_PATH
        self._conn_obj: sqlite3.Connection | None = None
        self._shutting_down: bool = False
        self._reconnect_lock = threading.Lock()
        # One transaction at a time: the tick and UI threads share this connection.
        self._write_lock = threading.RLock()
        self._init_db()

    @property
    def _conn(self):
        """Live connection, accessed by every query. Self-heals a connection
        closed while the app is still running (reopens the DB file). While the DB
        is shutting down / mid-restore it returns a null connection so late access
        is a benign no-op — never a crash, never a reopen that clobbers/resurrects
        the freshly-restored file. One choke point so no read/write path is missed."""
        conn = self._conn_obj
        if conn is not None:
            return conn
        if self._shutting_down:
            return _NULL_CONN
        with self._reconnect_lock:
            if self._conn_obj is None:
                logger.warning(f"DB connection was closed unexpectedly — reconnecting to {self._db_path}")
                # Full _init_db (not a bare connect) on purpose: the file on disk
                # may be an older-schema DB (e.g. a restored backup), so the
                # idempotent create/migrate pass must run before queries hit it.
                self._init_db()
            return self._conn_obj if self._conn_obj is not None else _NULL_CONN

    @_conn.setter
    def _conn(self, value) -> None:
        self._conn_obj = value

    @contextmanager
    def _write(self):
        """Run one write transaction under the write lock; commit on success, roll back on error."""
        with self._write_lock:
            conn = self._conn
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        self._migrate()
        logger.info(f"Database initialized at {self._db_path}")

    def _create_tables(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _migrate(self) -> None:
        """Add the columns an older database lacks, at its tables' ends."""
        for table, columns in (("metrics", _METRIC_COLUMNS), ("sessions", _SESSION_COLUMNS)):
            existing = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for name, sql, *_ in columns:
                if name not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql}")
                    logger.info(f"Migrated: added column {table}.{name}")
        self._conn.executescript(_INDEXES)
        self._conn.commit()

    @staticmethod
    def _insert_session(c, row: dict) -> int | None:
        """The session-row INSERT inside the caller's transaction: its id, or None from the null connection. `row` is
        its stats and fields; its `started_at` (epoch seconds) dates it, without one now."""
        started_at = row.get("started_at")
        values = {"date_time": (datetime.fromtimestamp(started_at) if started_at else datetime.now()).isoformat(),
                  **{col: row.get(col, default) for col, default in (*_SESSION_STAT_DEFAULTS, *_SESSION_FIELD_DEFAULTS)}}
        cursor = c.execute(f"INSERT INTO sessions ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
                           tuple(values.values()))
        return cursor.lastrowid

    @staticmethod
    def _insert_metrics(c, session_id: int, metrics_list: list[dict]) -> None:
        """The metrics INSERT inside the caller's transaction: each tick's values in their columns."""
        if metrics_list:
            c.executemany(_METRICS_INSERT, [(session_id, *(m.get(key, default) for _col, _sql, key, default
                                                            in _METRIC_COLUMNS)) for m in metrics_list])

    def get_all_sessions(self, user_id: int) -> list[dict]:
        """One profile's sessions, newest first: no caller may list every profile's."""
        cursor = self._conn.execute("SELECT * FROM sessions WHERE user_id = ? ORDER BY date_time DESC", (user_id,))
        return [dict(row) for row in cursor.fetchall()]

    def count_sessions(self, user_id: int, exclude_id: int | None = None) -> int:
        """One profile's sessions, leaving out `exclude_id` (a running session's row)."""
        return (self._conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ? AND id IS NOT ?",
                                   (user_id, exclude_id)).fetchone() or (0,))[0]  # the null connection has no row

    def get_session(self, session_id: int) -> dict | None:
        """Return a single session by ID."""
        cursor = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_session_metrics(self, session_id: int) -> list[dict]:
        """Return all metric rows for a session."""
        cursor = self._conn.execute(
            "SELECT * FROM metrics WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_session_band_totals(self, session_id: int) -> dict[str, float]:
        """Summed raw power per frequency band over the whole session (0.0 if no rows)."""
        bands = BAND_KEYS
        cols = ", ".join(f"SUM({b}_raw)" for b in bands)
        row = self._conn.execute(
            f"SELECT {cols} FROM metrics WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:  # null connection while shutting down
            return dict.fromkeys(bands, 0.0)
        return {b: float(row[i] or 0.0) for i, b in enumerate(bands)}

    def update_session_notes(
        self, session_id: int, notes: str | None = None, tags: str | None = None,
        mood_rating: int | None = None,
    ) -> bool:
        """Update only the diary fields given (others keep their value); True if the session row was updated."""
        fields = {"notes": notes, "tags": tags, "mood_rating": mood_rating}
        given = {k: v for k, v in fields.items() if v is not None}
        if not given:
            return False
        assignments = ", ".join(f"{k} = ?" for k in given)
        with self._write() as c:
            cur = c.execute(f"UPDATE sessions SET {assignments} WHERE id = ?", (*given.values(), session_id))
        return cur.rowcount > 0

    def delete_session(self, session_id: int) -> None:
        """Delete a session and its metrics."""
        self.delete_sessions([session_id])

    def delete_sessions(self, session_ids) -> int:
        """Delete sessions and their metrics in one transaction, so an error deletes none of them. Returns how many."""
        rows = [(sid,) for sid in session_ids]
        if not rows:
            return 0
        with self._write() as c:
            c.executemany("DELETE FROM metrics WHERE session_id = ?", rows)
            deleted = c.executemany("DELETE FROM sessions WHERE id = ?", rows).rowcount
        # One big transaction parks every deleted page in the WAL, which keeps that size until a clean close.
        try:
            with self._write_lock:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error as e:  # the delete has committed: only the WAL stays large, until the next checkpoint
            logger.warning(f"WAL checkpoint after deleting {deleted} session(s) failed: {e}")
        return deleted

    # ---- User profile methods ----

    def create_user(self, name: str) -> int:
        """Create a new user profile. Returns user ID.

        Raises:
            UserExistsError: if a user with this name already exists.
        """
        try:
            with self._write() as c:
                cursor = c.execute(
                    "INSERT INTO users (name, created_at) VALUES (?, ?)",
                    (name, datetime.now().isoformat()),
                )
        except sqlite3.IntegrityError:
            existing = self.find_user_by_name(name)
            if existing:
                raise UserExistsError(user_id=existing["id"], name=name) from None
            raise
        uid = cursor.lastrowid
        if uid is None:
            # Null connection (shutting down): a fake None id would be persisted
            # as last_user_id. Fail loudly — callers report_soft_error it.
            raise sqlite3.OperationalError("database connection is closed (shutting down)")
        logger.info(f"User '{name}' created with id {uid}")
        return uid

    def find_user_by_name(self, name: str) -> dict | None:
        """Return the user row matching `name` exactly (case-sensitive), or None."""
        cursor = self._conn.execute("SELECT * FROM users WHERE name = ?", (name,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_all_users(self) -> list[dict]:
        """Return all user profiles."""
        cursor = self._conn.execute("SELECT * FROM users ORDER BY name")
        return [dict(row) for row in cursor.fetchall()]

    def get_user(self, user_id: int) -> dict | None:
        """Return a single user by ID."""
        cursor = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def delete_user(self, user_id: int) -> None:
        """Delete a user and everything it owns; FKs aren't enforced, so children are purged explicitly."""
        with self._write() as c:
            c.execute(
                "DELETE FROM metrics WHERE session_id IN "
                "(SELECT id FROM sessions WHERE user_id = ?)", (user_id,)
            )
            c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            # GLOB, not LIKE: '_' is a LIKE wildcard, and user_1_* must not match user_11's keys.
            c.execute("DELETE FROM app_settings WHERE key GLOB ?", (f"user_{user_id}_*",))
            c.execute("DELETE FROM users WHERE id = ?", (user_id,))

    # ---- Session management ----

    @staticmethod
    def _update_session_row(c, session_id: int, row: dict) -> None:
        """The session-row UPDATE inside the caller's transaction: its stats, and the fields `row` has that a checkpoint
        rewrites (its profile and name stay as inserted)."""
        values = {col: row.get(col, default) for col, default in _SESSION_STAT_DEFAULTS}
        values.update({col: row[col] for col, _default in _SESSION_FIELD_DEFAULTS
                       if col in row and col not in _SESSION_INSERT_ONLY})
        c.execute(f"UPDATE sessions SET {', '.join(f'{col} = ?' for col in values)} WHERE id = ?",
                  (*values.values(), session_id))

    def checkpoint_session(self, session_id: int | None, row: dict, metrics: list[dict]) -> int | None:
        """Write a session's row (insert or update: its stats and fields, `_SESSION_FIELD_DEFAULTS` and `started_at`)
        and its new metric rows in one transaction, so a process killed at any point leaves both as of one checkpoint.
        Returns the session id; None when a new row couldn't be inserted (the null connection, shutting down) — an
        update there is a no-op that still returns the given id."""
        with self._write() as c:
            if session_id is None:
                session_id = self._insert_session(c, row)
            else:
                self._update_session_row(c, session_id, row)
            if session_id is not None:
                self._insert_metrics(c, session_id, metrics)
        return session_id

    def rename_session(self, session_id: int, new_name: str) -> None:
        """Rename a session."""
        with self._write() as c:
            c.execute(
                "UPDATE sessions SET session_name = ? WHERE id = ?",
                (new_name, session_id),
            )

    # ---- Settings persistence ----

    def get_setting(self, key: str) -> str | None:
        """Get a persisted setting value (the _conn property self-heals a closed conn)."""
        cursor = self._conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def set_setting(self, key: str, value: str) -> None:
        """Set a persisted setting value (upsert).

        The `_conn` property self-heals a connection closed while the app is still
        running; a write during deliberate shutdown / restore is a benign no-op via
        the null connection (never resurrects/clobbers the freshly-restored DB).
        """
        with self._write() as c:
            c.execute(
                "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
                (key, value),
            )

    def get_user_setting(self, user_id: int, key: str) -> str | None:
        """Get a per-user setting value."""
        return self.get_setting(f"user_{user_id}_{key}")

    def set_user_setting(self, user_id: int, key: str, value: str) -> None:
        """Set a per-user setting value."""
        self.set_setting(f"user_{user_id}_{key}", value)

    def set_user_settings(self, user_id: int, items: dict[str, str]) -> None:
        """Set many per-user settings in one transaction (one commit, not one per key)."""
        if not items:
            return
        with self._write() as c:
            c.executemany(
                "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
                [(f"user_{user_id}_{k}", v) for k, v in items.items()],
            )

    def get_json_setting(self, key: str, default=None):
        """Get a setting decoded from JSON, or `default` if absent/corrupt."""
        raw = self.get_setting(key)
        if not raw:
            return default
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return default

    def set_json_setting(self, key: str, value) -> None:
        """Persist a setting as a JSON string."""
        self.set_setting(key, json.dumps(value))

    def get_user_json_setting(self, user_id: int, key: str, default=None):
        """Get a per-user setting decoded from JSON, or `default` if absent/corrupt."""
        return self.get_json_setting(f"user_{user_id}_{key}", default)

    def set_user_json_setting(self, user_id: int, key: str, value) -> None:
        """Persist a per-user setting as a JSON string."""
        self.set_json_setting(f"user_{user_id}_{key}", value)

    # ---- Saved lists: a profile's saved formulas (max 50) and programs (max 20) ----

    _MAX_SAVED_FORMULAS = 50
    _MAX_SAVED_PROGRAMS = 20

    def _saved_list(self, user_id: int, key: str) -> list[dict]:
        """The JSON list stored under the profile setting `key`; [] when absent or unreadable."""
        raw = self.get_user_setting(user_id, key)
        if not raw:
            return []
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    def _add_saved(self, user_id: int, key: str, entry: dict, cap: int) -> bool:
        """Append `entry`; False if the list already holds `cap`."""
        entries = self._saved_list(user_id, key)
        if len(entries) >= cap:
            return False
        self.set_user_setting(user_id, key, json.dumps([*entries, entry]))
        return True

    def _replace_saved(self, user_id: int, key: str, index: int, entry: dict) -> bool:
        """Put `entry` at `index`; False if the index is out of range."""
        entries = self._saved_list(user_id, key)
        if not (0 <= index < len(entries)):
            return False
        entries[index] = entry
        self.set_user_setting(user_id, key, json.dumps(entries))
        return True

    def _remove_saved(self, user_id: int, key: str, index: int) -> None:
        entries = self._saved_list(user_id, key)
        if 0 <= index < len(entries):
            entries.pop(index)
            self.set_user_setting(user_id, key, json.dumps(entries))

    def get_saved_formulas(self, user_id: int) -> list[dict[str, str]]:
        """[{name, formula}, ...]."""
        return self._saved_list(user_id, "saved_formulas")

    def add_saved_formula(self, user_id: int, name: str, formula: str) -> bool:
        return self._add_saved(user_id, "saved_formulas", {"name": name, "formula": formula}, self._MAX_SAVED_FORMULAS)

    def update_saved_formula(self, user_id: int, index: int, name: str, formula: str) -> bool:
        return self._replace_saved(user_id, "saved_formulas", index, {"name": name, "formula": formula})

    def remove_saved_formula(self, user_id: int, index: int) -> None:
        self._remove_saved(user_id, "saved_formulas", index)

    def get_saved_programs(self, user_id: int) -> list[dict]:
        """[{name, segments}, ...]."""
        return self._saved_list(user_id, "saved_programs")

    def add_saved_program(self, user_id: int, name: str, segments: list[dict]) -> bool:
        return self._add_saved(user_id, "saved_programs", {"name": name, "segments": segments}, self._MAX_SAVED_PROGRAMS)

    def update_saved_program(self, user_id: int, index: int, name: str, segments: list[dict]) -> bool:
        return self._replace_saved(user_id, "saved_programs", index, {"name": name, "segments": segments})

    def remove_saved_program(self, user_id: int, index: int) -> None:
        self._remove_saved(user_id, "saved_programs", index)

    def get_db_size_bytes(self) -> int:
        """Return the database file size in bytes."""
        try:
            return os.path.getsize(self._db_path)
        except OSError:
            return 0

    def get_record_counts(self) -> dict[str, int]:
        """Return row counts for sessions and metrics tables."""
        sessions = (self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone() or (0,))[0]
        metrics = (self._conn.execute("SELECT COUNT(*) FROM metrics").fetchone() or (0,))[0]
        users = (self._conn.execute("SELECT COUNT(*) FROM users").fetchone() or (0,))[0]
        return {"sessions": sessions, "metrics": metrics, "users": users}

    # ---- CSV export ----

    @staticmethod
    def formula_vars_from_row(row: dict) -> dict[str, float]:
        """Shared var namespace so CSV export and diary recompute see identical inputs."""
        raw_bands = {k: row.get(f"{k}_raw", 0) for k in BAND_KEYS}
        groups = group_powers(lambda k: raw_bands[k])
        # The live tick's own band functions, so a replayed formula sees the inputs it saw live.
        fvars: dict[str, float] = {**raw_bands, **groups, "total_power": MetricsEngine.total_power(groups)}
        # The stored columns for normalized bands + scores feed formulas directly,
        # so diary replay sees the same namespace as the live tick (not silent zeros).
        for k in ("alpha_norm", "beta_norm", "gamma_norm", "theta_norm", "delta_norm",
                  "meditation_score", "shamatha_score", "distraction", "sinking",
                  "subtle_distraction", "stability", "calmness",
                  "native_attention", "native_meditation"):
            fvars[k] = row.get(k, 0.0)
        fvars.update({f"s_{k}": v for k, v in MetricsEngine.compute_sqrt_relative_bands(raw_bands).items()})
        return fvars

    def recompute_formula_series(
        self, session_id: int, evaluators: dict[str, CustomFormulaEvaluator], rows: list[dict] | None = None,
    ) -> dict[str, list[float]]:
        """Recompute each {series_key: evaluator} over a session's stored rows (`rows` when already read).

        Skips invalid evaluators. Returns {series_key: [value per tick]}.
        """
        if rows is None:
            rows = self.get_session_metrics(session_id)
        valid = {k: e for k, e in evaluators.items() if getattr(e, "is_valid", False)}
        out: dict[str, list[float]] = {k: [] for k in valid}
        for row in rows:
            fvars = self.formula_vars_from_row(row)
            for key, ev in valid.items():
                ev.push_variables(fvars)
                out[key].append(ev.evaluate(fvars))
        return out

    def export_session_csv(self, session_id: int, formula: str = "") -> str:
        """All metrics of a session as a CSV string; a `formula` that runs adds its `custom_formula` column, recomputed
        from the stored rows."""
        metrics = self.get_session_metrics(session_id)
        if not metrics:
            return ""

        evaluator, _error = compile_formula(formula)  # its own: its avg() windows see this session's rows only
        if evaluator is not None:
            for row in metrics:
                fvars = self.formula_vars_from_row(row)
                evaluator.push_variables(fvars)
                row["custom_formula"] = evaluator.evaluate(fvars)

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=metrics[0].keys())
        writer.writeheader()
        writer.writerows(metrics)
        return output.getvalue()

    def close(self) -> None:
        if self._conn_obj is not None:
            self._conn_obj.close()
            self._conn_obj = None

    def mark_shutting_down(self) -> None:
        """Mark the DB as deliberately closing (app exit / restore relaunch) so
        post-close access is a benign no-op (the null connection) instead of
        reopening the DB file — which would resurrect an abandoned process or
        clobber the freshly-restored DB."""
        self._shutting_down = True

    def reopen(self) -> None:
        """Undo mark_shutting_down() + close() after a restore that left the file untouched; the same object, so every holder stays live."""
        with self._reconnect_lock:
            self._shutting_down = False
            if self._conn_obj is None:
                self._init_db()
