"""The database's tables come from one column list each: a new database and a migrated old one have the same columns,
every tick key is written to its column, and a session row's checkpoint inserts and updates the same columns."""
import sqlite3

import pytest

from app.storage import database
from app.storage.database import DatabaseManager

# The initial commit's tables (v1.0.0 already had profiles): no profiles, raw bands, scoring record or formula lines.
_OLD_SCHEMA = """
CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, date_time TEXT NOT NULL, duration INTEGER NOT NULL,
    threshold_used INTEGER DEFAULT 50, avg_meditation REAL DEFAULT 0, avg_shamatha REAL DEFAULT 0,
    max_meditation REAL DEFAULT 0, time_above_threshold INTEGER DEFAULT 0, notes TEXT DEFAULT '',
    tags TEXT DEFAULT '', mood_rating INTEGER DEFAULT 0);
CREATE TABLE metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL, timestamp REAL NOT NULL,
    alpha_norm REAL DEFAULT 0, beta_norm REAL DEFAULT 0, theta_norm REAL DEFAULT 0, delta_norm REAL DEFAULT 0,
    gamma_norm REAL DEFAULT 0, meditation_score REAL DEFAULT 0, distraction REAL DEFAULT 0,
    subtle_distraction REAL DEFAULT 0, sinking REAL DEFAULT 0, shamatha_score REAL DEFAULT 0);
"""


def _columns(path, table) -> list[tuple]:
    with sqlite3.connect(path) as conn:
        return [(row[1], row[2], row[3], row[4]) for row in conn.execute(f"PRAGMA table_info({table})")]


@pytest.fixture
def db(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "new.db"))
    yield db
    db.close()


def test_a_migrated_old_database_has_a_new_ones_columns_and_indexes(tmp_path, db):
    old = tmp_path / "old.db"
    with sqlite3.connect(old) as conn:
        conn.executescript(_OLD_SCHEMA)
    DatabaseManager(db_path=str(old)).close()
    for table in ("sessions", "metrics"):
        assert sorted(_columns(old, table)) == sorted(_columns(db._db_path, table)), table
    with sqlite3.connect(old) as conn:  # the profile's index too, made once its column is there
        assert {row[1] for row in conn.execute("PRAGMA index_list(sessions)")} == {"idx_sessions_user"}
    # A new database has its columns in the table's order: an export's CSV follows it.
    assert [c[0] for c in _columns(db._db_path, "metrics")][2:] == [c[0] for c in database._METRIC_COLUMNS]
    assert [c[0] for c in _columns(db._db_path, "sessions")][1:] == [c[0] for c in database._SESSION_COLUMNS]


def test_every_tick_key_lands_in_its_column(db):
    tick = {key: (f"key{i}" if key == "score_key" else float(i + 1)) for i, (_c, _s, key, _d) in
            enumerate(database._METRIC_COLUMNS)}
    sid = db.checkpoint_session(None, {"duration": 1}, [tick, {}])
    empty, stored = db.get_session_metrics(sid)  # by timestamp: the empty tick's is 0
    assert {col: stored[col] for col, *_ in database._METRIC_COLUMNS} == {
        col: tick[key] for col, _sql, key, _d in database._METRIC_COLUMNS}
    assert {col: empty[col] for col, *_ in database._METRIC_COLUMNS} == {
        col: default for col, _sql, _key, default in database._METRIC_COLUMNS}  # a tick without a value: the default


def test_a_checkpoint_updates_what_it_inserted_but_the_profile_and_name(db):
    uid, other = db.create_user("A"), db.create_user("B")
    row = {"duration": 60, "threshold_used": 70, "avg_score": 61.5, "score_targets": "[70]", "user_id": uid,
           "session_name": "first", "custom_formulas": "[1]", "session_program": "[2]", "engine_version": "3",
           "started_at": 1_759_648_500.0}
    sid = db.checkpoint_session(None, row, [])
    db.checkpoint_session(sid, {**row, "duration": 120, "user_id": other, "session_name": "renamed",
                                "custom_formulas": "[9]", "started_at": 0.0}, [])
    stored = db.get_session(sid)
    assert (stored["duration"], stored["custom_formulas"], stored["session_program"], stored["engine_version"]) \
        == (120, "[9]", "[2]", "3")
    assert (stored["user_id"], stored["session_name"], stored["date_time"]) == (uid, "first", "2025-10-05T10:15:00")
    db.checkpoint_session(sid, {"duration": 180}, [])  # a row without its fields keeps them
    stored = db.get_session(sid)
    assert (stored["duration"], stored["custom_formulas"], stored["avg_score"]) == (180, "[9]", None)
