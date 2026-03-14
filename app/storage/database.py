import csv
import io
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

from app.config import APP
from app.logger import logger


class DatabaseManager:
    """SQLite storage for sessions, metrics timeseries, and user profiles."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path: str = db_path or APP.DB_PATH
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        self._conn = sqlite3.connect(self._db_path)
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
                notes TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                mood_rating INTEGER DEFAULT 0,
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

        self._conn.commit()

    def save_session(self, stats: Dict, user_id: Optional[int] = None) -> int:
        """Insert a session record and return its ID."""
        cursor = self._conn.execute(
            """
            INSERT INTO sessions
            (user_id, date_time, duration, threshold_used, avg_meditation, avg_shamatha,
             max_meditation, time_above_threshold)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        self._conn.commit()
        session_id = cursor.lastrowid
        logger.info(f"Session {session_id} saved")
        return session_id

    def save_metrics_batch(self, session_id: int, metrics_list: List[Dict]) -> None:
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
             shamatha_score, stability, calmness)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()

    def get_all_sessions(self, user_id: Optional[int] = None) -> List[Dict]:
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

    def get_session(self, session_id: int) -> Optional[Dict]:
        """Return a single session by ID."""
        cursor = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_session_metrics(self, session_id: int) -> List[Dict]:
        """Return all metric rows for a session."""
        cursor = self._conn.execute(
            "SELECT * FROM metrics WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def update_session_notes(
        self, session_id: int, notes: str = "", tags: str = "", mood_rating: int = 0
    ) -> None:
        """Update diary fields for a session."""
        self._conn.execute(
            "UPDATE sessions SET notes = ?, tags = ?, mood_rating = ? WHERE id = ?",
            (notes, tags, mood_rating, session_id),
        )
        self._conn.commit()

    def get_sessions_in_range(self, start_date: str, end_date: str) -> List[Dict]:
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
        """Create a new user profile. Returns user ID."""
        cursor = self._conn.execute(
            "INSERT INTO users (name, created_at) VALUES (?, ?)",
            (name, datetime.now().isoformat()),
        )
        self._conn.commit()
        uid = cursor.lastrowid
        logger.info(f"User '{name}' created with id {uid}")
        return uid

    def get_all_users(self) -> List[Dict]:
        """Return all user profiles."""
        cursor = self._conn.execute("SELECT * FROM users ORDER BY name")
        return [dict(row) for row in cursor.fetchall()]

    def get_user(self, user_id: int) -> Optional[Dict]:
        """Return a single user by ID."""
        cursor = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def delete_user(self, user_id: int) -> None:
        """Delete a user profile."""
        self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self._conn.commit()

    # ---- Session management ----

    def rename_session(self, session_id: int, new_name: str) -> None:
        """Rename a session by updating its notes with a title prefix."""
        self._conn.execute(
            "UPDATE sessions SET notes = ? WHERE id = ?",
            (new_name, session_id),
        )
        self._conn.commit()

    # ---- Settings persistence ----

    def get_setting(self, key: str) -> Optional[str]:
        """Get a persisted setting value."""
        cursor = self._conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def set_setting(self, key: str, value: str) -> None:
        """Set a persisted setting value (upsert)."""
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

    def get_db_size_bytes(self) -> int:
        """Return the database file size in bytes."""
        try:
            return os.path.getsize(self._db_path)
        except OSError:
            return 0

    def get_record_counts(self) -> Dict[str, int]:
        """Return row counts for sessions and metrics tables."""
        sessions = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        metrics = self._conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
        users = self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return {"sessions": sessions, "metrics": metrics, "users": users}

    # ---- CSV export ----

    def export_session_csv(self, session_id: int) -> str:
        """Export all metrics for a session as a CSV string."""
        metrics = self.get_session_metrics(session_id)
        if not metrics:
            return ""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=metrics[0].keys())
        writer.writeheader()
        writer.writerows(metrics)
        return output.getvalue()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


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
