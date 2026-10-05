"""Select mode deletes the selected sessions in one confirmed step, one transaction, without a rebuild (#57)."""

import os
import sqlite3
import tempfile
import time
from unittest.mock import MagicMock

import pytest
from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.uix.label import Label
from kivy.uix.popup import Popup

import app.ui.app_manager as am
from app.session.manager import SessionManager
from app.storage.database import DatabaseManager
from app.ui.app_manager import EEGMeditationApp
from app.ui.history_screen import HistoryScreen
from app.ui.theme import StyledButton
from app.ui.widgets.loading_overlay import LoadingOverlay


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


def _session(db, uid: int, ticks: int = 3) -> int:
    return db.checkpoint_session(None, {"duration": 60}, [{"timestamp": i * 0.5, "shamatha_score": 70}
                                                          for i in range(ticks)], user_id=uid)


def _counts(db, sid: int) -> tuple:
    c = db._conn
    return (c.execute("SELECT COUNT(*) FROM sessions WHERE id = ?", (sid,)).fetchone()[0],
            c.execute("SELECT COUNT(*) FROM metrics WHERE session_id = ?", (sid,)).fetchone()[0])


# ---- the database: one transaction for the whole selection ----


def test_deleting_sessions_removes_them_and_their_data_and_nothing_else(db):
    me, other = db.create_user("me"), db.create_user("other")
    a, b, keep = _session(db, me), _session(db, me), _session(db, me)
    theirs = _session(db, other)
    assert db.delete_sessions([a, b]) == 2
    assert _counts(db, a) == _counts(db, b) == (0, 0)
    assert _counts(db, keep) == _counts(db, theirs) == (1, 3)


def test_a_failure_part_way_deletes_none_of_the_selection(db):
    me = db.create_user("me")
    a, b = _session(db, me), _session(db, me)
    db._conn.execute(f"CREATE TRIGGER refuse BEFORE DELETE ON sessions WHEN old.id = {b} "
                     "BEGIN SELECT RAISE(ABORT, 'disk I/O error'); END")
    with pytest.raises(sqlite3.Error):
        db.delete_sessions([a, b])
    assert _counts(db, a) == _counts(db, b) == (1, 3)  # rolled back: a's data is still there too


def test_one_selection_is_one_commit(db, monkeypatch):
    me = db.create_user("me")
    ids = [_session(db, me) for _ in range(5)]
    writes = []
    real = db._write
    monkeypatch.setattr(db, "_write", lambda: (writes.append(1), real())[1])
    db.delete_sessions(ids)
    assert len(writes) == 1


def test_a_large_delete_leaves_no_large_write_ahead_log(db):
    # One big transaction parks every deleted page in the WAL, which keeps its size until a clean close.
    me = db.create_user("me")
    ids = [_session(db, me, ticks=2000) for _ in range(10)]
    db.delete_sessions(ids)
    assert os.path.getsize(db._db_path + "-wal") == 0



def test_a_checkpoint_that_fails_after_the_delete_still_reports_it_deleted(db):
    # A read still open on the shared connection (another thread mid-fetch) makes the checkpoint raise "database
    # table is locked" after the delete has committed: History has to drop the rows, not report a failure.
    me = db.create_user("me")
    gone, keep = _session(db, me), _session(db, me)
    reading = db._conn.execute("SELECT * FROM metrics")
    reading.fetchone()
    assert db.delete_sessions([gone]) == 1
    reading.close()
    assert _counts(db, gone) == (0, 0) and _counts(db, keep) == (1, 3)

def test_deleting_one_session_is_a_selection_of_one(db, monkeypatch):
    calls = []
    monkeypatch.setattr(db, "delete_sessions", lambda ids: calls.append(list(ids)) or len(ids))
    db.delete_session(7)
    assert calls == [[7]]


# ---- the app: the one delete path, off the main thread ----


class _Deferred:
    """Stands in for the worker thread and the main-thread queue, so a test runs each side when it chooses."""

    def __init__(self, monkeypatch):
        self.workers, self.main = [], []
        monkeypatch.setattr(am.threading, "Thread", lambda target, **k: MagicMock(start=lambda: self.workers.append(target)))

    def run(self):
        while self.workers or self.main:
            if self.workers:
                self.workers.pop(0)()
            if self.main:
                self.main.pop(0)()


def _app(db, monkeypatch) -> tuple[EEGMeditationApp, _Deferred, list]:
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._db = db
    app._history_screen = MagicMock()
    app._live_screen = MagicMock()
    app._live_screen.summary_session_id = None
    app._audio = MagicMock()
    app._session_manager = SessionManager()
    app._waiting_for_bt = False
    app._tick_thread = None
    app._current_session_id = None
    app._info_popup = MagicMock()
    app.show_loading = MagicMock()
    app.hide_loading = MagicMock()
    deferred = _Deferred(monkeypatch)
    app._on_main = deferred.main.append
    done = []
    return app, deferred, done


def test_the_app_deletes_a_selection_off_the_main_thread_in_one_call(db, monkeypatch):
    me = db.create_user("me")
    ids = [_session(db, me) for _ in range(3)]
    app, deferred, done = _app(db, monkeypatch)
    calls = []
    real = db.delete_sessions
    monkeypatch.setattr(db, "delete_sessions", lambda s: calls.append(list(s)) or real(s))
    app._delete_sessions(ids, done.append)
    assert calls == [] and _counts(db, ids[0]) == (1, 3)  # nothing on the main thread yet
    app._history_screen.remove_sessions.assert_not_called()
    deferred.run()
    assert calls == [ids] and done == [True]
    app._history_screen.remove_sessions.assert_called_once_with(ids)


class _Touch:
    x, y = 10, 10
    pos = (10, 10)


def _with_overlay(app) -> LoadingOverlay:
    del app.show_loading, app.hide_loading  # the app's own, on a real overlay
    app._loading_overlay = LoadingOverlay()
    return app._loading_overlay


def _wait(seconds: float) -> None:
    time.sleep(seconds)
    Clock.tick()


def test_the_screen_is_modal_while_deleting_and_a_quick_delete_never_paints_the_overlay(db, monkeypatch):
    # A tap in the first moments of a delete reached the rows and the end card being deleted (opening a session
    # that was about to go, or saving notes to it).
    me = db.create_user("me")
    sid = _session(db, me)
    app, deferred, done = _app(db, monkeypatch)
    overlay = _with_overlay(app)
    app._delete_sessions([sid], done.append)
    assert overlay.on_touch_down(_Touch()) and not overlay.is_visible  # modal at once, nothing painted yet
    deferred.run()  # finishes before the overlay's delay
    _wait(0.25)
    assert not overlay.is_visible and not overlay.on_touch_down(_Touch())
    assert done == [True]


def test_a_slow_delete_shows_the_overlay_until_it_ends(db, monkeypatch):
    me = db.create_user("me")
    sid = _session(db, me)
    app, deferred, done = _app(db, monkeypatch)
    overlay = _with_overlay(app)
    app._delete_sessions([sid], done.append)
    _wait(0.25)
    assert overlay.is_visible and overlay._status.text.startswith("Deleting 1 session")
    deferred.run()
    assert not overlay.is_visible and not overlay.on_touch_down(_Touch())
    assert done == [True]


def test_a_failed_delete_is_reported_and_history_keeps_the_rows(db, monkeypatch):
    reported = []
    monkeypatch.setattr(am, "report_soft_error", lambda label, detail, **k: reported.append(label))
    app, deferred, done = _app(db, monkeypatch)
    monkeypatch.setattr(db, "delete_sessions", lambda ids: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    app._delete_sessions([1, 2], done.append)
    deferred.run()
    assert reported == ["session_delete_failed"] and done == [False]
    app._history_screen.remove_sessions.assert_not_called()
    app.hide_loading.assert_called_once()


def test_the_running_session_is_not_deleted(db, monkeypatch):
    # Its row is in History after the first checkpoint; deleting it left the next checkpoints writing orphan data.
    me = db.create_user("me")
    running, finished = _session(db, me), _session(db, me)
    app, deferred, done = _app(db, monkeypatch)
    app._session_manager.start()
    app._current_session_id = running
    app._delete_sessions([finished, running], done.append)
    deferred.run()
    assert done == [False]
    assert _counts(db, running) == _counts(db, finished) == (1, 3)  # nothing deleted
    message = app._info_popup.call_args.args[1]
    assert "Stop the session" in message and "Nothing was deleted" in message
    app._history_screen.remove_sessions.assert_not_called()


def test_deleting_the_end_cards_session_from_history_closes_the_card(db, monkeypatch):
    me = db.create_user("me")
    shown, other = _session(db, me), _session(db, me)
    app, deferred, done = _app(db, monkeypatch)
    app._live_screen.summary_session_id = shown  # the session that just ended, its card still open
    app._delete_sessions([shown, other], done.append)
    deferred.run()
    app._live_screen.hide_summary.assert_called_once()
    app._audio.stop_timer_bell.assert_called_once()


def test_a_failed_delete_leaves_the_end_card_and_its_notes(db, monkeypatch):
    monkeypatch.setattr(am, "report_soft_error", lambda *a, **k: None)
    app, deferred, done = _app(db, monkeypatch)
    app._live_screen.summary_session_id = 5
    monkeypatch.setattr(db, "delete_sessions", lambda ids: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    app._delete_sessions([5], done.append)
    deferred.run()
    app._live_screen.hide_summary.assert_not_called()


# ---- History: Delete N in select mode, through the one confirm ----


def _sessions(n: int, users=(1,)) -> list[dict]:
    return [
        {"id": i, "user_id": users[i % len(users)], "date_time": f"2026-09-{28 - i // 2:02d}T{10 + i % 2}:00:00",
         "duration": 600, "avg_shamatha": 50, "session_name": f"Session {i}"}
        for i in range(n)
    ]


def _history(n: int = 6, users=(1,)) -> HistoryScreen:
    h = HistoryScreen()
    h.load_sessions(_sessions(n, users))
    return h


def _frames(n: int = 3) -> None:
    for _ in range(n):
        EventLoop.idle()


@pytest.fixture
def confirm():
    """Open History's delete confirm for real; yields (text, buttons) and closes what's left open."""
    from kivy.core.window import Window
    EventLoop.ensure_window()
    opened = []

    def _open(action):
        before = {id(w) for w in Window.children}
        action()
        _frames()
        popup = next(w for w in Window.children if isinstance(w, Popup) and id(w) not in before)
        opened.append(popup)
        text = "\n".join(w.text for w in popup.walk() if isinstance(w, Label) and not isinstance(w.parent, StyledButton))
        buttons = {w.text: w for w in popup.walk() if isinstance(w, StyledButton)}
        return text, buttons

    yield _open
    for popup in opened:
        if popup.parent is not None:
            popup.dismiss(animation=False)
    _frames()


def test_delete_n_follows_the_selection():
    h = _history()
    h.set_select_mode(True)
    assert (h._btn_delete.text, h._btn_delete.disabled) == ("Delete 0", True)
    h.toggle_session_selection(1)
    h.toggle_session_selection(4)
    assert (h._btn_delete.text, h._btn_delete.disabled) == ("Delete 2", False)


def test_delete_n_asks_with_the_count_and_the_days(confirm):
    h = _history()
    h.set_select_mode(True)
    for sid in (0, 3, 5):  # 2026-09-28, 2026-09-27, 2026-09-26
        h.toggle_session_selection(sid)
    text, buttons = confirm(h.delete_selected)
    assert "Delete 3 sessions from 2026-09-26 to 2026-09-28?" in text and "can't be undone" in text
    assert list(buttons) == ["Delete", "Cancel"]  # the order every confirm in the app uses


@pytest.mark.parametrize("users, note", [((1, 2), "2 profiles"), ((1, None), None)])
def test_the_confirm_names_several_profiles_in_the_all_users_view(confirm, users, note):
    h = _history(users=users)
    h.set_select_mode(True)
    h.select_all_shown()
    text, _buttons = confirm(h.delete_selected)
    assert (note in text) if note else ("profiles" not in text)  # a session with no profile isn't another profile


def test_cancel_deletes_nothing_and_confirm_deletes_the_selection_then_leaves_select_mode(confirm):
    h = _history()
    deleted = []
    h._on_delete_sessions = lambda ids, done: (deleted.append(ids), done(True))
    h.set_select_mode(True)
    h.toggle_session_selection(2)
    h.toggle_session_selection(1)
    _text, buttons = confirm(h.delete_selected)
    buttons["Cancel"].dispatch("on_release")
    _frames()
    assert deleted == [] and h._select_mode
    _text, buttons = confirm(h.delete_selected)
    buttons["Delete"].dispatch("on_release")
    assert deleted == [[1, 2]]
    assert not h._select_mode


def test_delete_tapped_during_the_fade_after_cancel_deletes_nothing(confirm):
    # Kivy still delivers taps to a popup while it fades out: the confirm decides once.
    h = _history()
    deleted = []
    h._on_delete_sessions = lambda ids, done: (deleted.append(ids), done(True))
    h.set_select_mode(True)
    h.select_all_shown()
    _text, buttons = confirm(h.delete_selected)
    buttons["Cancel"].dispatch("on_release")
    buttons["Delete"].dispatch("on_release")
    assert deleted == []


def test_a_failed_bulk_delete_keeps_select_mode_and_the_selection(confirm):
    h = _history()
    h._on_delete_sessions = lambda ids, done: done(False)
    h.set_select_mode(True)
    h.toggle_session_selection(3)
    _text, buttons = confirm(h.delete_selected)
    buttons["Delete"].dispatch("on_release")
    assert h._select_mode and h.selected_ids == {3}


def test_select_all_then_delete_takes_every_session_in_the_filter(confirm):
    h = _history(n=300)
    deleted = []
    h._on_delete_sessions = lambda ids, done: (deleted.append(ids), h.remove_sessions(ids), done(True))
    h.set_select_mode(True)
    h.select_all_shown()  # including the rows the list never built
    _text, buttons = confirm(h.delete_selected)
    buttons["Delete"].dispatch("on_release")
    assert deleted == [list(range(300))]
    assert h._rv.data == [] and h._date_label.text == "All sessions (0 sessions)"


def test_a_row_delete_asks_with_its_title_and_takes_the_same_path(confirm):
    h = _history()
    deleted = []
    h._on_delete_sessions = lambda ids, done: (deleted.append(ids), done(True))
    text, buttons = confirm(lambda: h._confirm_delete([2]))
    assert "2026-09-27 10:00 - Session 2" in text and "can't be undone" in text
    buttons["Delete"].dispatch("on_release")
    assert deleted == [[2]]


# ---- History lists finished sessions only ----


def test_history_does_not_list_the_running_session_until_it_ends(db, monkeypatch):
    # Its row is in the database from the first checkpoint, with stats as of that checkpoint: not a finished session.
    me = db.create_user("me")
    finished, running = _session(db, me), _session(db, me)
    app, _deferred, _done = _app(db, monkeypatch)
    app._current_user_id = me
    app._view_all_users = False
    app._history_view = None
    app._history_screen = HistoryScreen()
    app._session_manager.start()
    app._current_session_id = running
    app._refresh_history(force=True)
    assert [s["id"] for s in app._history_screen._sessions] == [finished]
    app._session_manager.stop()
    app._session_manager.reset()  # the session ended (the ending marks History dirty)
    app._refresh_history(force=True)
    assert sorted(s["id"] for s in app._history_screen._sessions) == sorted([finished, running])
