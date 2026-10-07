"""Each tick records what it was scored on: the metric, its value and the target in force. A threshold change
mid-session moves the scoring from that tick on, and the session row keeps the targets in order for the cards."""

import csv
import io
import os
import sqlite3
import tempfile

import pytest

from app.session.manager import SessionManager
from app.session.scoring import extend_steps, target_steps
from app.storage.database import DatabaseManager
from app.ui.session_labels import session_score_rows


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    d = DatabaseManager(db_path=path)
    yield d
    d.close()
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)


def _running(threshold: int = 70) -> SessionManager:
    sm = SessionManager()
    sm.start(threshold=threshold)
    sm.set_active_goal("shamatha_score")
    return sm


# ---- the steps of a target series ----


def test_steps_start_where_the_target_changes():
    assert target_steps([70, 70, 85, 85, 85, 75]) == [(0, 70), (2, 85), (5, 75)]
    assert target_steps([70]) == [(0, 70)]


def test_no_steps_without_a_target_on_every_tick():
    # Rows from before the targets were recorded have NULL ones: nothing is deduced from them.
    assert target_steps([]) is None
    assert target_steps([None, None]) is None
    assert target_steps([70, None, 70]) is None


def test_steps_built_tick_by_tick_equal_the_steps_of_the_whole_series():
    targets = [70, 70, 72, 76, 85, 85, 70]
    steps: list = []
    for i, t in enumerate(targets):
        extend_steps(steps, i, t)
    assert steps == target_steps(targets)


# ---- the session manager stamps every scored tick ----


def test_each_tick_returns_its_metric_value_and_target():
    sm = _running(70)
    assert sm.add_metric({"shamatha_score": 64.0}) == {"score_key": "shamatha_score", "score_value": 64.0,
                                                     "score_target": 70}


def test_a_threshold_change_scores_the_following_ticks_against_the_new_value():
    sm = _running(70)
    for _ in range(4):
        sm.add_metric({"shamatha_score": 80.0})  # above 70: 2 s
    sm.set_threshold(85)
    stamp = sm.add_metric({"shamatha_score": 80.0})  # below 85
    assert stamp["score_target"] == 85
    sm.add_metric({"shamatha_score": 90.0})  # above 85: 0.5 s
    stats = sm.compute_statistics()
    assert stats["time_above_threshold"] == 2  # int(2.5): before the fix 80 counted as above all along (3.0)
    assert stats["longest_streak"] == 2
    assert stats["threshold_used"] == 70  # the Start value
    assert stats["score_targets"] == "[70, 85]"


def test_a_session_that_kept_its_threshold_records_one_target():
    sm = _running(70)
    sm.add_metric({"shamatha_score": 50.0})
    sm.set_threshold(70)  # the slider let go where it was
    sm.add_metric({"shamatha_score": 50.0})
    assert sm.compute_statistics()["score_targets"] == "[70]"


def test_a_session_with_no_scored_tick_records_no_targets():
    assert _running(70).compute_statistics()["score_targets"] == ""


def test_a_program_segment_target_is_what_its_ticks_record():
    sm = _running(70)
    sm.set_active_goal("custom_formula", 120)
    sm.set_threshold(40)  # the slider: a segment's own target stays in force
    stamp = sm.add_metric({"custom_formula": 130.0})
    assert stamp == {"score_key": "custom_formula", "score_value": 130.0, "score_target": 120}


def test_the_next_session_records_only_its_own_targets():
    sm = _running(70)
    sm.add_metric({"shamatha_score": 80.0})
    sm.set_threshold(85)
    sm.add_metric({"shamatha_score": 80.0})
    sm.stop()
    sm.start(threshold=60)
    sm.add_metric({"shamatha_score": 80.0})
    assert sm.compute_statistics()["score_targets"] == "[60]"
    sm.reset()
    sm.start(threshold=65)
    sm.add_metric({"shamatha_score": 80.0})
    assert sm.compute_statistics()["score_targets"] == "[65]"


def test_a_tick_while_not_running_records_nothing():
    sm = _running(70)
    sm.pause()
    assert sm.add_metric({"shamatha_score": 80.0}) == {}


# ---- storage ----


def _old_database(path: str) -> None:
    """A database as an older app version left it: no per-tick score columns, no session targets."""
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
        CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT NULL,
            date_time TEXT NOT NULL, duration INTEGER NOT NULL, threshold_used INTEGER DEFAULT 50);
        CREATE TABLE metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL,
            timestamp REAL NOT NULL, shamatha_score REAL DEFAULT 0);
        INSERT INTO sessions (date_time, duration, threshold_used) VALUES ('2026-09-01T07:30:00', 600, 65);
        INSERT INTO metrics (session_id, timestamp, shamatha_score) VALUES (1, 0.0, 61.0), (1, 0.5, 66.0);
    """)
    c.commit()
    c.close()


def test_opening_an_old_database_adds_the_columns_and_leaves_its_rows_unknown():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _old_database(path)
        d = DatabaseManager(db_path=path)
        rows = d.get_session_metrics(1)
        assert [(r["score_key"], r["score_value"], r["score_target"]) for r in rows] == [(None, None, None)] * 2
        assert [r["shamatha_score"] for r in rows] == [61.0, 66.0]
        assert d.get_session(1)["score_targets"] == ""
        d.close()
        DatabaseManager(db_path=path).close()  # the next open finds them there
    finally:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(path + suffix):
                os.remove(path + suffix)


def _scored_session(db) -> int:
    sm = _running(70)
    rows = []
    for t, value in enumerate((80.0, 75.0, 82.0, 90.0)):
        if t == 2:
            sm.set_threshold(85)
        tick = {"timestamp": t * 0.5, "shamatha_score": value}
        rows.append({**tick, **sm.add_metric(tick)})
    return db.checkpoint_session(None, sm.compute_statistics(), rows, session_name="s")


def test_a_checkpoint_stores_each_ticks_score_and_the_sessions_targets(db):
    sid = _scored_session(db)
    rows = db.get_session_metrics(sid)
    assert [(r["score_key"], r["score_value"], r["score_target"]) for r in rows] == [
        ("shamatha_score", 80.0, 70), ("shamatha_score", 75.0, 70),
        ("shamatha_score", 82.0, 85), ("shamatha_score", 90.0, 85)]
    session = db.get_session(sid)
    assert session["score_targets"] == "[70, 85]" and session["threshold_used"] == 70


def test_the_next_checkpoint_updates_the_sessions_targets(db):
    sm = _running(70)
    sm.add_metric({"shamatha_score": 80.0})
    sid = db.checkpoint_session(None, sm.compute_statistics(), [], session_name="s")
    assert db.get_session(sid)["score_targets"] == "[70]"
    sm.set_threshold(60)
    sm.add_metric({"shamatha_score": 80.0})
    db.checkpoint_session(sid, sm.compute_statistics(), [])
    assert db.get_session(sid)["score_targets"] == "[70, 60]"


def test_the_csv_export_has_each_ticks_score(db):
    sid = _scored_session(db)
    exported = list(csv.DictReader(io.StringIO(db.export_session_csv(sid))))
    assert [(r["score_key"], r["score_target"]) for r in exported] == [
        ("shamatha_score", "70.0"), ("shamatha_score", "70.0"), ("shamatha_score", "85.0"), ("shamatha_score", "85.0")]


# ---- the cards' Threshold row ----


def _row(targets: str, threshold: int = 70, key: str = "shamatha_score") -> dict:
    return {"score_metric_key": key, "score_metric_name": "Shamatha", "avg_score": 64.0, "threshold_used": threshold,
            "score_targets": targets}


def _threshold(session: dict) -> str:
    return dict(session_score_rows(session))["Threshold"]


@pytest.mark.parametrize("targets, shown", [
    ("[70]", "70"),
    ("[70, 85]", "70 › 85"),
    ("[70, 85, 75]", "70 › 85 › 75"),
    ("[70, 85, 75, 80]", "70 › … › 80"),
    ("[72.5, 80]", "72.5 › 80"),
])
def test_the_threshold_row_shows_the_targets_in_order(targets, shown):
    assert _threshold(_row(targets)) == shown


def test_a_session_saved_before_the_targets_shows_its_threshold():
    assert _threshold(_row("", threshold=65)) == "65"
    assert _threshold({k: v for k, v in _row("", threshold=65).items() if k != "score_targets"}) == "65"


def test_a_program_still_shows_per_segment():
    assert _threshold(_row("[70, 120]", key="program")) == "Per segment"


@pytest.mark.parametrize("stored", ["70", "[null]", '["70"]', '{"a": 1}'])
def test_targets_that_are_not_a_list_of_numbers_show_the_threshold(stored):
    # A hand-edited or foreign database: the card falls back instead of failing.
    assert _threshold(_row(stored, threshold=65)) == "65"
