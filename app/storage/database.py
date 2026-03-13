import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

from app.config import APP
from app.logger import logger


class DatabaseManager:
    """SQLite storage for sessions and metrics timeseries data."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path: str = db_path or APP.DB_PATH
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        logger.info(f"Database initialized at {self._db_path}")

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_time TEXT NOT NULL,
                duration INTEGER NOT NULL,
                threshold_used INTEGER DEFAULT 50,
                avg_meditation REAL DEFAULT 0,
                avg_shamatha REAL DEFAULT 0,
                max_meditation REAL DEFAULT 0,
                time_above_threshold INTEGER DEFAULT 0,
                notes TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                mood_rating INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
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
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_metrics_session
            ON metrics(session_id);
            """
        )
        self._conn.commit()

    def save_session(self, stats: Dict) -> int:
        """Insert a session record and return its ID."""
        cursor = self._conn.execute(
            """
            INSERT INTO sessions
            (date_time, duration, threshold_used, avg_meditation, avg_shamatha,
             max_meditation, time_above_threshold)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
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
        """Batch insert metrics rows for a session."""
        if not metrics_list:
            return
        rows = [
            (
                session_id,
                m.get("timestamp", 0),
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
            )
            for m in metrics_list
        ]
        self._conn.executemany(
            """
            INSERT INTO metrics
            (session_id, timestamp, alpha_norm, beta_norm, theta_norm,
             delta_norm, gamma_norm, meditation_score, distraction,
             subtle_distraction, sinking, shamatha_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()

    def get_all_sessions(self) -> List[Dict]:
        """Return all sessions ordered by date descending."""
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

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


if __name__ == "__main__":
    import tempfile
    import os

    db_path = os.path.join(tempfile.gettempdir(), "test_meditation.db")
    db = DatabaseManager(db_path=db_path)

    sid = db.save_session({
        "duration": 600,
        "threshold_used": 50,
        "avg_meditation": 65.5,
        "avg_shamatha": 42.3,
        "max_meditation": 180.0,
        "time_above_threshold": 300,
    })
    print(f"Created session ID: {sid}")

    db.save_metrics_batch(sid, [
        {"timestamp": 0.5, "meditation_score": 60, "shamatha_score": 40},
        {"timestamp": 1.0, "meditation_score": 70, "shamatha_score": 45},
    ])

    db.update_session_notes(sid, notes="Good session", tags="morning,calm", mood_rating=4)

    sessions = db.get_all_sessions()
    print(f"Total sessions: {len(sessions)}")
    for s in sessions:
        print(f"  Session {s['id']}: {s['date_time']}, mood={s['mood_rating']}")

    metrics = db.get_session_metrics(sid)
    print(f"Metrics for session {sid}: {len(metrics)} rows")

    db.close()
    os.remove(db_path)
    print("Test DB cleaned up")
