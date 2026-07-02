import csv
import io
import json
import math
import os
import sqlite3
import threading
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from app.config import APP
from app.logger import logger

if TYPE_CHECKING:
    from app.metrics.custom_formula import CustomFormulaEvaluator


class _NullCursor:
    """Empty cursor returned by the null connection while shutting down."""

    lastrowid = None

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def __iter__(self):
        return iter(())


class _NullConnection:
    """No-op connection used only while the DB is shutting down / mid-restore:
    swallows writes and returns no rows, so late access from any path (reads,
    writes, the daemon tick thread) is a benign no-op instead of crashing on a
    None connection or reopening-and-clobbering the freshly-restored DB file."""

    def execute(self, *_a, **_k):
        return _NullCursor()

    def executemany(self, *_a, **_k):
        return _NullCursor()

    def executescript(self, *_a, **_k):
        return None

    def commit(self):
        pass

    def close(self):
        pass

    def backup(self, *_a, **_k):
        # A silent no-op here would produce an EMPTY backup file that a user
        # later restores over their data. Raise so the backup workers surface
        # a "Backup failed" diagnostic instead.
        raise sqlite3.OperationalError("database connection is closed (shutting down)")


_NULL_CONN = _NullConnection()


class UserExistsError(Exception):
    """Raised by DatabaseManager.create_user when the name already exists."""

    def __init__(self, user_id: int, name: str) -> None:
        super().__init__(f"User '{name}' already exists (id={user_id})")
        self.user_id = user_id
        self.name = name


class DatabaseManager:
    """SQLite storage for sessions, metrics timeseries, and user profiles."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path: str = db_path or APP.DB_PATH
        self._conn_obj: Optional[sqlite3.Connection] = None
        self._shutting_down: bool = False
        self._reconnect_lock = threading.Lock()
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

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        self._migrate()
        logger.info(f"Database initialized at {self._db_path}")

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER DEFAULT NULL,
                date_time TEXT NOT NULL,
                duration INTEGER NOT NULL,
                threshold_used INTEGER DEFAULT 50,
                avg_meditation REAL DEFAULT 0,
                avg_shamatha REAL DEFAULT 0,
                max_meditation REAL DEFAULT 0,
                time_above_threshold INTEGER DEFAULT 0,
                longest_streak INTEGER DEFAULT 0,
                notes TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                mood_rating INTEGER DEFAULT 0,
                engine_version TEXT DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                delta_raw REAL DEFAULT 0,
                theta_raw REAL DEFAULT 0,
                alpha1_raw REAL DEFAULT 0,
                alpha2_raw REAL DEFAULT 0,
                beta1_raw REAL DEFAULT 0,
                beta2_raw REAL DEFAULT 0,
                gamma1_raw REAL DEFAULT 0,
                gamma2_raw REAL DEFAULT 0,
                alpha_norm REAL DEFAULT 0,
                beta_norm REAL DEFAULT 0,
                theta_norm REAL DEFAULT 0,
                delta_norm REAL DEFAULT 0,
                gamma_norm REAL DEFAULT 0,
                meditation_score REAL DEFAULT 0,
                distraction REAL DEFAULT 0,
                subtle_distraction REAL DEFAULT 0,
                sinking REAL DEFAULT 0,
                shamatha_score REAL DEFAULT 0,
                stability REAL DEFAULT 0,
                calmness REAL DEFAULT 0,
                native_attention REAL DEFAULT 0,
                native_meditation REAL DEFAULT 0,
                marker INTEGER DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_metrics_session
            ON metrics(session_id);

            CREATE INDEX IF NOT EXISTS idx_sessions_user
            ON sessions(user_id);

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns that may be missing in older databases."""
        existing = set()
        cursor = self._conn.execute("PRAGMA table_info(metrics)")
        for row in cursor.fetchall():
            existing.add(row[1])

        new_columns = {
            "delta_raw": "REAL DEFAULT 0",
            "theta_raw": "REAL DEFAULT 0",
            "alpha1_raw": "REAL DEFAULT 0",
            "alpha2_raw": "REAL DEFAULT 0",
            "beta1_raw": "REAL DEFAULT 0",
            "beta2_raw": "REAL DEFAULT 0",
            "gamma1_raw": "REAL DEFAULT 0",
            "gamma2_raw": "REAL DEFAULT 0",
            "stability": "REAL DEFAULT 0",
            "calmness": "REAL DEFAULT 0",
            "native_attention": "REAL DEFAULT 0",
            "native_meditation": "REAL DEFAULT 0",
            "marker": "INTEGER DEFAULT 0",
        }
        for col, col_type in new_columns.items():
            if col not in existing:
                self._conn.execute(f"ALTER TABLE metrics ADD COLUMN {col} {col_type}")
                logger.info(f"Migrated: added column metrics.{col}")

        sess_cursor = self._conn.execute("PRAGMA table_info(sessions)")
        sess_cols = {row[1] for row in sess_cursor.fetchall()}
        if "user_id" not in sess_cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN user_id INTEGER DEFAULT NULL")
            logger.info("Migrated: added column sessions.user_id")
        if "longest_streak" not in sess_cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN longest_streak INTEGER DEFAULT 0")
            logger.info("Migrated: added column sessions.longest_streak")
        if "session_name" not in sess_cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN session_name TEXT DEFAULT ''")
            logger.info("Migrated: added column sessions.session_name")
        if "time_shamatha_90" not in sess_cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN time_shamatha_90 INTEGER DEFAULT 0")
            logger.info("Migrated: added column sessions.time_shamatha_90")
        if "custom_formulas" not in sess_cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN custom_formulas TEXT DEFAULT ''")
            logger.info("Migrated: added column sessions.custom_formulas")
        if "session_program" not in sess_cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN session_program TEXT DEFAULT ''")
            logger.info("Migrated: added column sessions.session_program")
        if "engine_version" not in sess_cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN engine_version TEXT DEFAULT ''")
            logger.info("Migrated: added column sessions.engine_version")

        self._conn.commit()

    def save_session(self, stats: dict, user_id: Optional[int] = None,
                     session_name: str = "", custom_formulas: str = "",
                     session_program: str = "", engine_version: str = "") -> Optional[int]:
        """Insert a session record and return its ID — or None if the write was
        no-oped by the null connection (shutting down); callers must treat None
        as "not persisted". `custom_formulas` is a JSON string. `engine_version`
        stamps which metric-formula version produced the stored values.
        """
        cursor = self._conn.execute(
            """
            INSERT INTO sessions
            (user_id, date_time, duration, threshold_used, avg_meditation, avg_shamatha,
             max_meditation, time_above_threshold, longest_streak, session_name,
             time_shamatha_90, custom_formulas, session_program, engine_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                datetime.now().isoformat(),
                stats.get("duration", 0),
                stats.get("threshold_used", 50),
                stats.get("avg_meditation", 0),
                stats.get("avg_shamatha", 0),
                stats.get("max_meditation", 0),
                stats.get("time_above_threshold", 0),
                stats.get("longest_streak", 0),
                session_name,
                stats.get("time_shamatha_90", 0),
                custom_formulas,
                session_program,
                engine_version,
            ),
        )
        self._conn.commit()
        session_id = cursor.lastrowid
        if session_id is None:
            logger.error("save_session no-oped — DB is shutting down; session NOT persisted")
            return None
        logger.info(f"Session {session_id} saved")
        return session_id

    def save_metrics_batch(self, session_id: int, metrics_list: list[dict]) -> None:
        """Batch insert metrics rows with raw and computed data."""
        if not metrics_list:
            return
        rows = [
            (
                session_id,
                m.get("timestamp", 0),
                m.get("delta", 0),
                m.get("theta", 0),
                m.get("alpha1", 0),
                m.get("alpha2", 0),
                m.get("beta1", 0),
                m.get("beta2", 0),
                m.get("gamma1", 0),
                m.get("gamma2", 0),
                m.get("alpha_norm", 0),
                m.get("beta_norm", 0),
                m.get("theta_norm", 0),
                m.get("delta_norm", 0),
                m.get("gamma_norm", 0),
                m.get("meditation_score", 0),
                m.get("distraction", 0),
                m.get("subtle_distraction", 0),
                m.get("sinking", 0),
                m.get("shamatha_score", 0),
                m.get("stability", 0),
                m.get("calmness", 0),
                m.get("native_attention", 0),
                m.get("native_meditation", 0),
                m.get("marker", 0),
            )
            for m in metrics_list
        ]
        self._conn.executemany(
            """
            INSERT INTO metrics
            (session_id, timestamp, delta_raw, theta_raw, alpha1_raw, alpha2_raw,
             beta1_raw, beta2_raw, gamma1_raw, gamma2_raw,
             alpha_norm, beta_norm, theta_norm, delta_norm, gamma_norm,
             meditation_score, distraction, subtle_distraction, sinking,
             shamatha_score, stability, calmness,
             native_attention, native_meditation, marker)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()

    def get_all_sessions(self, user_id: Optional[int] = None) -> list[dict]:
        """Return sessions ordered by date descending, optionally filtered by user."""
        if user_id is not None:
            cursor = self._conn.execute(
                "SELECT * FROM sessions WHERE user_id = ? ORDER BY date_time DESC",
                (user_id,),
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM sessions ORDER BY date_time DESC"
            )
        return [dict(row) for row in cursor.fetchall()]

    def get_session(self, session_id: int) -> Optional[dict]:
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
        bands = ["delta", "theta", "alpha1", "alpha2", "beta1", "beta2", "gamma1", "gamma2"]
        cols = ", ".join(f"SUM({b}_raw)" for b in bands)
        row = self._conn.execute(
            f"SELECT {cols} FROM metrics WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:  # null connection while shutting down
            return dict.fromkeys(bands, 0.0)
        return {b: float(row[i] or 0.0) for i, b in enumerate(bands)}

    def update_session_notes(
        self, session_id: int, notes: str = "", tags: str = "", mood_rating: int = 0
    ) -> None:
        """Update diary fields for a session."""
        self._conn.execute(
            "UPDATE sessions SET notes = ?, tags = ?, mood_rating = ? WHERE id = ?",
            (notes, tags, mood_rating, session_id),
        )
        self._conn.commit()

    def get_sessions_in_range(self, start_date: str, end_date: str) -> list[dict]:
        """Return sessions within a date range for analytics."""
        cursor = self._conn.execute(
            "SELECT * FROM sessions WHERE date_time BETWEEN ? AND ? ORDER BY date_time",
            (start_date, end_date),
        )
        return [dict(row) for row in cursor.fetchall()]

    def delete_session(self, session_id: int) -> None:
        """Delete a session and its metrics."""
        self._conn.execute("DELETE FROM metrics WHERE session_id = ?", (session_id,))
        self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.commit()

    # ---- User profile methods ----

    def create_user(self, name: str) -> int:
        """Create a new user profile. Returns user ID.

        Raises:
            UserExistsError: if a user with this name already exists.
        """
        try:
            cursor = self._conn.execute(
                "INSERT INTO users (name, created_at) VALUES (?, ?)",
                (name, datetime.now().isoformat()),
            )
            self._conn.commit()
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

    def find_user_by_name(self, name: str) -> Optional[dict]:
        """Return the user row matching `name` exactly (case-sensitive), or None."""
        cursor = self._conn.execute("SELECT * FROM users WHERE name = ?", (name,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_all_users(self) -> list[dict]:
        """Return all user profiles."""
        cursor = self._conn.execute("SELECT * FROM users ORDER BY name")
        return [dict(row) for row in cursor.fetchall()]

    def get_user(self, user_id: int) -> Optional[dict]:
        """Return a single user by ID."""
        cursor = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def delete_user(self, user_id: int) -> None:
        """Delete a user profile."""
        self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self._conn.commit()

    # ---- Session management ----

    def update_session(self, session_id: int, stats: dict,
                       custom_formulas: str | None = None,
                       session_program: str | None = None,
                       engine_version: str | None = None) -> None:
        """Update an existing session's aggregate stats (+ formula snapshot if given)."""
        cols = ["duration = ?", "threshold_used = ?", "avg_meditation = ?",
                "avg_shamatha = ?", "max_meditation = ?", "time_above_threshold = ?",
                "longest_streak = ?", "time_shamatha_90 = ?"]
        vals: list = [
            stats.get("duration", 0),
            stats.get("threshold_used", 50),
            stats.get("avg_meditation", 0),
            stats.get("avg_shamatha", 0),
            stats.get("max_meditation", 0),
            stats.get("time_above_threshold", 0),
            stats.get("longest_streak", 0),
            stats.get("time_shamatha_90", 0),
        ]
        if custom_formulas is not None:
            cols.append("custom_formulas = ?")
            vals.append(custom_formulas)
        if session_program is not None:
            cols.append("session_program = ?")
            vals.append(session_program)
        if engine_version is not None:
            cols.append("engine_version = ?")
            vals.append(engine_version)
        vals.append(session_id)
        self._conn.execute(
            f"UPDATE sessions SET {', '.join(cols)} WHERE id = ?", vals
        )
        self._conn.commit()
        logger.info(f"Session {session_id} updated with final stats")

    def rename_session(self, session_id: int, new_name: str) -> None:
        """Rename a session."""
        self._conn.execute(
            "UPDATE sessions SET session_name = ? WHERE id = ?",
            (new_name, session_id),
        )
        self._conn.commit()

    # ---- Settings persistence ----

    def get_setting(self, key: str) -> Optional[str]:
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
        self._conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    def get_user_setting(self, user_id: int, key: str) -> Optional[str]:
        """Get a per-user setting value."""
        return self.get_setting(f"user_{user_id}_{key}")

    def set_user_setting(self, user_id: int, key: str, value: str) -> None:
        """Set a per-user setting value."""
        self.set_setting(f"user_{user_id}_{key}", value)

    def get_user_json_setting(self, user_id: int, key: str, default=None):
        """Get a per-user setting decoded from JSON, or `default` if absent/corrupt."""
        raw = self.get_user_setting(user_id, key)
        if not raw:
            return default
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return default

    def set_user_json_setting(self, user_id: int, key: str, value) -> None:
        """Persist a per-user setting as a JSON string."""
        self.set_user_setting(user_id, key, json.dumps(value))

    # ---- Saved formulas (per-user, max 50) ----

    _MAX_SAVED_FORMULAS = 50

    def get_saved_formulas(self, user_id: int) -> list[dict[str, str]]:
        """Return saved formulas for a user as [{name, formula}, ...]."""
        raw = self.get_user_setting(user_id, "saved_formulas")
        if not raw:
            return []
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    def _save_formulas_list(self, user_id: int, formulas: list[dict[str, str]]) -> None:
        self.set_user_setting(user_id, "saved_formulas", json.dumps(formulas))

    def add_saved_formula(self, user_id: int, name: str, formula: str) -> bool:
        """Save a formula. Returns False if limit reached."""
        formulas = self.get_saved_formulas(user_id)
        if len(formulas) >= self._MAX_SAVED_FORMULAS:
            return False
        formulas.append({"name": name, "formula": formula})
        self._save_formulas_list(user_id, formulas)
        return True

    def update_saved_formula(self, user_id: int, index: int, name: str, formula: str) -> None:
        """Update a saved formula by index."""
        formulas = self.get_saved_formulas(user_id)
        if 0 <= index < len(formulas):
            formulas[index] = {"name": name, "formula": formula}
            self._save_formulas_list(user_id, formulas)

    def remove_saved_formula(self, user_id: int, index: int) -> None:
        """Remove a saved formula by index."""
        formulas = self.get_saved_formulas(user_id)
        if 0 <= index < len(formulas):
            formulas.pop(index)
            self._save_formulas_list(user_id, formulas)

    # ---- Saved programs (per-user, max 20) ----

    _MAX_SAVED_PROGRAMS = 20

    def get_saved_programs(self, user_id: int) -> list[dict]:
        """Return saved programs for a user as [{name, segments}, ...]."""
        raw = self.get_user_setting(user_id, "saved_programs")
        if not raw:
            return []
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    def _save_programs_list(self, user_id: int, programs: list[dict]) -> None:
        self.set_user_setting(user_id, "saved_programs", json.dumps(programs))

    def add_saved_program(self, user_id: int, name: str, segments: list[dict]) -> bool:
        """Save a program. Returns False if the limit is reached."""
        programs = self.get_saved_programs(user_id)
        if len(programs) >= self._MAX_SAVED_PROGRAMS:
            return False
        programs.append({"name": name, "segments": segments})
        self._save_programs_list(user_id, programs)
        return True

    def update_saved_program(self, user_id: int, index: int, name: str, segments: list[dict]) -> None:
        """Update a saved program by index."""
        programs = self.get_saved_programs(user_id)
        if 0 <= index < len(programs):
            programs[index] = {"name": name, "segments": segments}
            self._save_programs_list(user_id, programs)

    def remove_saved_program(self, user_id: int, index: int) -> None:
        """Remove a saved program by index."""
        programs = self.get_saved_programs(user_id)
        if 0 <= index < len(programs):
            programs.pop(index)
            self._save_programs_list(user_id, programs)

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
        raw_bands = {
            "delta": row.get("delta_raw", 0),
            "theta": row.get("theta_raw", 0),
            "alpha1": row.get("alpha1_raw", 0),
            "alpha2": row.get("alpha2_raw", 0),
            "beta1": row.get("beta1_raw", 0),
            "beta2": row.get("beta2_raw", 0),
            "gamma1": row.get("gamma1_raw", 0),
            "gamma2": row.get("gamma2_raw", 0),
        }
        alpha = raw_bands["alpha1"] + raw_bands["alpha2"]
        beta = raw_bands["beta1"] + raw_bands["beta2"]
        gamma = raw_bands["gamma1"] + raw_bands["gamma2"]
        fvars: dict[str, float] = {
            **raw_bands,
            "alpha": alpha,
            "beta": beta,
            "gamma": gamma,
            # Matches MetricsEngine.normalize_bands so total_power replays identically.
            "total_power": alpha + beta + gamma + raw_bands["theta"] + raw_bands["delta"] + 1.0,
        }
        # The stored columns for normalized bands + scores feed formulas directly,
        # so diary replay sees the same namespace as the live tick (not silent zeros).
        for k in ("alpha_norm", "beta_norm", "gamma_norm", "theta_norm", "delta_norm",
                  "meditation_score", "shamatha_score", "distraction", "sinking",
                  "subtle_distraction", "stability", "calmness",
                  "native_attention", "native_meditation"):
            fvars[k] = row.get(k, 0.0)
        sqrt_keys = ("delta", "theta", "alpha1", "alpha2", "beta1", "beta2")
        sqrt_vals = {k: max(raw_bands.get(k, 0.0), 0.0) for k in sqrt_keys}
        total = sum(sqrt_vals.values())
        for k in sqrt_keys:
            fvars[f"s_{k}"] = math.sqrt(sqrt_vals[k] / total) if total >= 1.0 else 0.0
        return fvars

    def recompute_formula_series(
        self, session_id: int, evaluators: "dict[str, CustomFormulaEvaluator]"
    ) -> dict[str, list[float]]:
        """Recompute each {series_key: evaluator} over a session's stored rows.

        Skips invalid evaluators. Returns {series_key: [value per tick]}.
        """
        rows = self.get_session_metrics(session_id)
        valid = {k: e for k, e in evaluators.items() if getattr(e, "is_valid", False)}
        out: dict[str, list[float]] = {k: [] for k in valid}
        for row in rows:
            fvars = self.formula_vars_from_row(row)
            for key, ev in valid.items():
                ev.push_variables(fvars)
                out[key].append(ev.evaluate(fvars))
        return out

    def export_session_csv(self, session_id: int, custom_formula=None) -> str:
        """Export all metrics for a session as a CSV string.

        If custom_formula (CustomFormulaEvaluator) is provided and has a valid
        formula, recomputes custom_formula values from stored band powers and
        appends the column.
        """
        metrics = self.get_session_metrics(session_id)
        if not metrics:
            return ""

        if custom_formula and custom_formula.is_valid:
            for row in metrics:
                fvars = self.formula_vars_from_row(row)
                custom_formula.push_variables(fvars)
                row["custom_formula"] = custom_formula.evaluate(fvars)

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


if __name__ == "__main__":
    import tempfile

    db_path = os.path.join(tempfile.gettempdir(), "test_meditation.db")
    db = DatabaseManager(db_path=db_path)

    uid = db.create_user("TestUser")
    print(f"Created user ID: {uid}")

    sid = db.save_session({
        "duration": 600,
        "threshold_used": 50,
        "avg_meditation": 65.5,
        "avg_shamatha": 42.3,
        "max_meditation": 180.0,
        "time_above_threshold": 300,
        "longest_streak": 45,
    }, user_id=uid)
    print(f"Created session ID: {sid}")

    db.save_metrics_batch(sid, [
        {"timestamp": 0.5, "delta": 300, "theta": 200, "alpha1": 500, "alpha2": 400,
         "beta1": 100, "beta2": 80, "gamma1": 30, "gamma2": 20,
         "meditation_score": 60, "shamatha_score": 40, "stability": 5, "calmness": 3.2},
        {"timestamp": 1.0, "delta": 310, "theta": 210, "alpha1": 510, "alpha2": 410,
         "beta1": 110, "beta2": 85, "gamma1": 35, "gamma2": 25,
         "meditation_score": 70, "shamatha_score": 45, "stability": 4, "calmness": 3.5},
    ])

    db.update_session_notes(sid, notes="Good session", tags="morning,calm", mood_rating=4)

    sessions = db.get_all_sessions(user_id=uid)
    print(f"User sessions: {len(sessions)}")

    csv_data = db.export_session_csv(sid)
    print(f"CSV export ({len(csv_data)} chars):\n{csv_data[:200]}")

    db.set_setting("last_user_id", str(uid))
    print(f"Saved setting last_user_id: {db.get_setting('last_user_id')}")

    db.rename_session(sid, "Morning meditation")
    s = db.get_session(sid)
    print(f"Renamed session notes: {s['notes']}")

    print(f"DB size: {db.get_db_size_bytes()} bytes")
    print(f"Record counts: {db.get_record_counts()}")

    db.delete_session(sid)
    print(f"Session after delete: {db.get_session(sid)}")

    db.close()
    os.remove(db_path)
    print("Test DB cleaned up")
