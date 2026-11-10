"""A running session is checkpointed whole: its row and its data reach the DB together, so a killed app keeps both (#30)."""

import os
import tempfile
import threading
import time
from unittest.mock import MagicMock

import pytest

import app.ui.app_manager as am
import app.ui.backup_flow as bf
from app.config import APP
from app.session.manager import SessionManager
from app.session.recorder import SessionRecorder
from app.storage.database import DatabaseManager
from tests._app import popup_titles, start_ticked_by_hand


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


# ---- the recorder: every snapshot point goes through one checkpoint ----


class _Recording:
    """A SessionRecorder built by its constructor on `db`, its session running; `with_score` can be made to fail."""

    def __init__(self, db) -> None:
        self.db, self.manager = db, SessionManager()
        uid = db.create_user("t")
        self.with_score = lambda stats: stats
        self.recorder = SessionRecorder(db, self.manager, with_score=lambda stats: self.with_score(stats),
                                        row_fields=lambda: {"user_id": uid, "session_name": "06:00 - Mock"})
        self.recorder.begin()
        self.manager.start()

    def ticks(self, n: int) -> None:
        for _ in range(n):
            metrics = {"shamatha_score": 70, "meditation_score": 60}
            self.recorder.record(metrics, {"timestamp": 0.0, **metrics})

    def run_for(self, seconds: float) -> None:
        self.manager._start_time = time.time() - seconds

    def row(self) -> tuple:
        return _row(self.db, self.recorder.session_id)


def test_every_tick_flush_brings_the_row_up_to_date(db):
    # The kill repro: 150 s into a session the row still said 59 s (written once, at the first flush).
    session = _Recording(db)
    per_flush = int(APP.FLUSH_INTERVAL_SECONDS / APP.UPDATE_FREQUENCY)
    for minute in (1, 2):
        session.ticks(per_flush)
        session.run_for(60 * minute)
        for _ in range(per_flush):
            session.recorder.flush_tick()
    assert session.row() == (120, 2 * per_flush)
    assert session.recorder._buffer == []


def test_a_tick_recorded_during_a_checkpoint_waits_for_it_and_is_kept(db):
    session = _Recording(db)
    session.ticks(10)
    started, release = threading.Event(), threading.Event()
    real = db.checkpoint_session

    def slow(*a, **k):
        started.set()
        release.wait(2)
        return real(*a, **k)

    db.checkpoint_session = slow
    writer = threading.Thread(target=session.recorder.checkpoint)
    writer.start()
    assert started.wait(2)
    ticker = threading.Thread(target=session.ticks, args=(1,))
    ticker.start()
    ticker.join(0.2)
    assert ticker.is_alive()  # the tick waits: the checkpoint's stats and data stay one consistent snapshot
    release.set()
    writer.join(2)
    ticker.join(2)
    assert len(session.recorder._buffer) == 1  # recorded after the snapshot, kept for the next checkpoint
    assert session.row()[1] == 10


def test_a_failed_checkpoint_keeps_the_ticks_for_the_next_one(db, monkeypatch):
    session = _Recording(db)
    session.ticks(20)
    real = db.checkpoint_session
    monkeypatch.setattr(db, "checkpoint_session", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("locked")))
    with pytest.raises(RuntimeError):
        session.recorder.checkpoint()
    assert len(session.recorder._buffer) == 20
    monkeypatch.setattr(db, "checkpoint_session", real)
    session.ticks(5)
    session.recorder.checkpoint()
    assert session.row()[1] == 25


def test_a_paused_session_keeps_its_length_up_to_the_pause():
    sm = SessionManager()
    sm.start()
    sm._start_time = time.time() - 300
    sm.pause()
    time.sleep(0.05)
    assert 299 <= sm.elapsed_seconds <= 301  # not 0: the length is frozen at the pause
    assert 299 <= sm.compute_statistics()["duration"] <= 301


# ---- the app: leaving it and a backup checkpoint the running session ----


def _session_of(app, ticks: int, seconds: float) -> None:
    """A mock session of `ticks` hand-run ticks that has been running for `seconds`."""
    start_ticked_by_hand(app, ticks=ticks)
    app._session_manager._start_time = time.time() - seconds


def _running_row(app) -> tuple:
    return _row(app._db, app._recorder.session_id)


def test_leaving_the_app_mid_session_checkpoints_it(fresh_app):
    app = fresh_app
    _session_of(app, 50, 25)  # under a minute: nothing flushed yet
    assert app._recorder.session_id is None
    app._flush_on_leave()
    assert _running_row(app) == (25, 50)


def test_leaving_the_app_without_a_session_writes_nothing(fresh_app):
    app = fresh_app
    app._flush_on_leave()
    assert app._db.get_all_sessions(app._current_user_id) == []


def test_leaving_the_app_while_paused_checkpoints_the_length_before_the_pause(fresh_app):
    app = fresh_app
    _session_of(app, 60, 300)
    app._on_pause()
    app._flush_on_leave()
    duration, rows = _running_row(app)
    assert 299 <= duration <= 301 and rows == 60


def _failing_score(_stats):
    raise KeyError("graph")


def test_a_failing_checkpoint_on_leave_still_saves_the_settings(fresh_app, monkeypatch):
    reported = []
    monkeypatch.setattr(am, "report_soft_error", lambda label, detail, **k: reported.append(label))
    app = fresh_app
    _session_of(app, 4, 2)
    app._settings_screen.threshold = 62  # changed, not yet written
    monkeypatch.setattr(app, "_with_score", _failing_score)
    app._flush_on_leave()
    assert app._db.get_user_setting(app._current_user_id, "threshold") == "62"
    assert reported == ["session_checkpoint_failed"]


def _backup_inline(monkeypatch, *, after=lambda cb, *a, **k: None) -> None:
    """From here the backup's worker runs in the call (as would any thread started meanwhile); what it queues for the
    main thread goes to `after`."""
    monkeypatch.setattr(bf.threading, "Thread", lambda target, **k: MagicMock(start=target))
    monkeypatch.setattr(bf.Clock, "schedule_once", after)


def test_a_backup_holds_the_running_session_as_of_the_backup(fresh_app, monkeypatch):
    app = fresh_app
    _session_of(app, 40, 20)
    seen = []
    monkeypatch.setattr(bf._backup, "make_backup", lambda d, path: seen.append(_running_row(app)))
    _backup_inline(monkeypatch)
    app._backup_flow._run_backup_async("/tmp/unused.db")
    assert seen == [(20, 40)]


def test_an_android_backup_holds_the_running_session_as_of_the_backup(fresh_app, monkeypatch):
    app = fresh_app
    _session_of(app, 30, 15)
    seen = []

    def snapshot(d):
        seen.append(_running_row(app))
        raise OSError("stop here")  # the copy itself isn't under test

    monkeypatch.setattr(bf._backup, "online_backup_to_tempfile", snapshot)
    monkeypatch.setattr(bf, "report_soft_error", lambda *a, **k: None)
    _backup_inline(monkeypatch)
    app._backup_flow._backup_to_uri_worker("content://unused")
    assert seen == [(15, 30)]


def test_a_failing_checkpoint_does_not_stop_a_backup(fresh_app, monkeypatch):
    reported, copied = [], []
    monkeypatch.setattr(am, "report_soft_error", lambda label, detail, **k: reported.append(label))
    monkeypatch.setattr(bf, "report_soft_error", lambda label, detail, **k: reported.append(label))
    monkeypatch.setattr(bf._backup, "make_backup", lambda d, path: copied.append(path))
    app = fresh_app
    _session_of(app, 4, 2)
    _backup_inline(monkeypatch, after=lambda cb, *a, **k: cb(0))  # once the session's own threads are up
    monkeypatch.setattr(app, "_with_score", _failing_score)
    app._backup_flow._run_backup_async("/tmp/unused.db")
    assert copied == ["/tmp/unused.db"]  # the rest of the database is still backed up
    assert reported == ["session_checkpoint_failed"]
    assert popup_titles() == ["Backup saved"]
