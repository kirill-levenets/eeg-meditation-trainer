"""A running session is checkpointed whole: its row and its data reach the DB together, so a killed app keeps both (#30)."""

import os
import tempfile
import threading
import time
from unittest.mock import MagicMock

import pytest

from app.config import APP
from app.session.manager import SessionManager
from app.storage.database import DatabaseManager
from app.ui.app_manager import EEGMeditationApp


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


def _rows(n: int, start: int = 0) -> list[dict]:
    return [{"timestamp": (start + i) * 0.5, "shamatha_score": 70, "meditation_score": 60} for i in range(n)]


def _row(db, sid) -> tuple:
    r = db.get_session(sid)
    return r["duration"], db._conn.execute("SELECT COUNT(*) FROM metrics WHERE session_id = ?", (sid,)).fetchone()[0]


# ---- the database: one transaction ----


def test_a_checkpoint_creates_the_session_with_its_data(db):
    uid = db.create_user("t")
    sid = db.checkpoint_session(None, {"duration": 60, "avg_shamatha": 70}, _rows(120), user_id=uid, session_name="s")
    assert sid is not None and _row(db, sid) == (60, 120)
    assert db.get_session(sid)["session_name"] == "s"


def test_the_next_checkpoint_updates_the_row_and_adds_the_new_data(db):
    sid = db.checkpoint_session(None, {"duration": 60}, _rows(120))
    assert db.checkpoint_session(sid, {"duration": 120}, _rows(120, start=120)) == sid
    assert _row(db, sid) == (120, 240)


def test_a_failed_checkpoint_leaves_the_previous_one_whole(db, monkeypatch):
    sid = db.checkpoint_session(None, {"duration": 60}, _rows(120))

    def boom(c, session_id, rows):
        raise RuntimeError("disk full")

    monkeypatch.setattr(db, "_insert_metrics", boom)
    with pytest.raises(RuntimeError):
        db.checkpoint_session(sid, {"duration": 120}, _rows(120, start=120))
    assert _row(db, sid) == (60, 120)  # the row didn't move without its data


# ---- the app: every snapshot point goes through one checkpoint ----


def _app(db) -> EEGMeditationApp:
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = db
    app._current_user_id = db.create_user("t")
    app._current_session_id = None
    app._metrics_buffer = []
    app._flush_counter = 0
    app._session_manager = SessionManager()
    app._session_manager.start()
    app._with_score = lambda stats: stats
    app._session_custom_formulas_json = lambda: ""
    app._session_program_json = lambda: ""
    app._make_session_name = lambda: "06:00 - Mock"
    return app


def _ticks(app, n: int) -> None:
    for _ in range(n):
        metrics = {"shamatha_score": 70, "meditation_score": 60}
        app._record_tick(metrics, {"timestamp": 0.0, **metrics})


def _run_for(app, seconds: float) -> None:
    app._session_manager._start_time = time.time() - seconds


def test_every_tick_flush_brings_the_row_up_to_date():
    # The kill repro: 150 s into a session the row still said 59 s (written once, at the first flush).
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = DatabaseManager(db_path=path)
    try:
        app = _app(db)
        per_flush = int(APP.FLUSH_INTERVAL_SECONDS / APP.UPDATE_FREQUENCY)
        for minute in (1, 2):
            _ticks(app, per_flush)
            _run_for(app, 60 * minute)
            for _ in range(per_flush):
                app._flush_tick()
        assert _row(db, app._current_session_id) == (120, 2 * per_flush)
        assert app._metrics_buffer == []
    finally:
        db.close()
        os.remove(path)


def test_leaving_the_app_mid_session_checkpoints_it(db):
    app = _app(db)
    app._live_screen = None
    app._save_user_settings = MagicMock()
    app._leaving = False
    _ticks(app, 50)  # under a minute: nothing flushed yet
    _run_for(app, 25)
    app._flush_on_leave()
    assert _row(db, app._current_session_id) == (25, 50)


def test_leaving_the_app_without_a_session_writes_nothing(db):
    app = _app(db)
    app._session_manager = SessionManager()  # idle
    app._live_screen = None
    app._save_user_settings = MagicMock()
    app._leaving = False
    app._flush_on_leave()
    assert db._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_a_backup_holds_the_running_session_as_of_the_backup(db, monkeypatch):
    import app.ui.app_manager as am
    app = _app(db)
    app._settings_screen = MagicMock()
    _ticks(app, 40)
    _run_for(app, 20)
    seen = []
    monkeypatch.setattr(am._backup, "make_backup", lambda d, path: seen.append(_row(d, app._current_session_id)))
    monkeypatch.setattr(am.threading, "Thread", lambda target, **k: MagicMock(start=target))
    monkeypatch.setattr(am.Clock, "schedule_once", lambda *a, **k: None)
    app._run_backup_async("/tmp/unused.db")
    assert seen == [(20, 40)]


def test_a_tick_recorded_during_a_checkpoint_waits_for_it_and_is_kept(db):
    app = _app(db)
    _ticks(app, 10)
    started, release = threading.Event(), threading.Event()
    real = db.checkpoint_session

    def slow(*a, **k):
        started.set()
        release.wait(2)
        return real(*a, **k)

    db.checkpoint_session = slow
    writer = threading.Thread(target=app._checkpoint_session)
    writer.start()
    assert started.wait(2)
    ticker = threading.Thread(target=_ticks, args=(app, 1))
    ticker.start()
    ticker.join(0.2)
    assert ticker.is_alive()  # the tick waits: the checkpoint's stats and data stay one consistent snapshot
    release.set()
    writer.join(2)
    ticker.join(2)
    assert len(app._metrics_buffer) == 1  # recorded after the snapshot, kept for the next checkpoint
    assert _row(db, app._current_session_id)[1] == 10


def test_an_android_backup_holds_the_running_session_as_of_the_backup(db, monkeypatch):
    import app.ui.app_manager as am
    app = _app(db)
    _ticks(app, 30)
    _run_for(app, 15)
    seen = []

    def snapshot(d):
        seen.append(_row(d, app._current_session_id))
        raise OSError("stop here")  # the copy itself isn't under test

    monkeypatch.setattr(am._backup, "online_backup_to_tempfile", snapshot)
    monkeypatch.setattr(am.Clock, "schedule_once", lambda *a, **k: None)
    app._backup_to_uri_worker("content://unused")
    assert seen == [(15, 30)]


def test_a_failed_checkpoint_keeps_the_ticks_for_the_next_one(db, monkeypatch):
    app = _app(db)
    _ticks(app, 20)
    real = db.checkpoint_session
    monkeypatch.setattr(db, "checkpoint_session", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("locked")))
    with pytest.raises(RuntimeError):
        app._checkpoint_session()
    assert len(app._metrics_buffer) == 20
    monkeypatch.setattr(db, "checkpoint_session", real)
    _ticks(app, 5)
    app._checkpoint_session()
    assert _row(db, app._current_session_id)[1] == 25


# ---- review round: a paused session, and a failing checkpoint never blocks the rest ----


def test_a_paused_session_keeps_its_length_up_to_the_pause():
    sm = SessionManager()
    sm.start()
    sm._start_time = time.time() - 300
    sm.pause()
    time.sleep(0.05)
    assert 299 <= sm.elapsed_seconds <= 301  # not 0: the length is frozen at the pause
    assert 299 <= sm.compute_statistics()["duration"] <= 301


def test_leaving_the_app_while_paused_checkpoints_the_length_before_the_pause(db):
    app = _app(db)
    app._live_screen = None
    app._save_user_settings = MagicMock()
    app._leaving = False
    _ticks(app, 600)
    _run_for(app, 300)
    app._session_manager.pause()
    app._flush_on_leave()
    duration, rows = _row(db, app._current_session_id)
    assert 299 <= duration <= 301 and rows == 600


def test_a_failing_checkpoint_on_leave_still_saves_the_settings(db, monkeypatch):
    import app.ui.app_manager as am
    reported = []
    monkeypatch.setattr(am, "report_soft_error", lambda label, detail, **k: reported.append(label))
    app = _app(db)
    app._live_screen = None
    app._save_user_settings = MagicMock()
    app._leaving = False
    monkeypatch.setattr(app, "_with_score", lambda stats: (_ for _ in ()).throw(KeyError("graph")))
    app._flush_on_leave()
    app._save_user_settings.assert_called_once()
    assert reported == ["session_checkpoint_failed"]


def test_a_failing_checkpoint_does_not_stop_a_backup(db, monkeypatch):
    import app.ui.app_manager as am
    reported, copied = [], []
    monkeypatch.setattr(am, "report_soft_error", lambda label, detail, **k: reported.append(label))
    monkeypatch.setattr(am._backup, "make_backup", lambda d, path: copied.append(path))
    monkeypatch.setattr(am.threading, "Thread", lambda target, **k: MagicMock(start=target))
    monkeypatch.setattr(am.Clock, "schedule_once", lambda cb, *a, **k: cb(0))
    app = _app(db)
    app._settings_screen = MagicMock()
    app._report_backup_saved = MagicMock()
    monkeypatch.setattr(app, "_with_score", lambda stats: (_ for _ in ()).throw(KeyError("graph")))
    app._run_backup_async("/tmp/unused.db")
    assert copied == ["/tmp/unused.db"]  # the rest of the database is still backed up
    assert reported == ["session_checkpoint_failed"]
    app._report_backup_saved.assert_called_once()
