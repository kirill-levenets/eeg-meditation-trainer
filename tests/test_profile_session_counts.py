"""Settings › User Profile's session counts are current whenever Settings shows them, and count what History lists."""
import sqlite3

from app.storage.database import DatabaseManager
from app.ui.hooks import wire
from app.ui.settings_screen import SettingsScreen
from tests._app import frames, start_ticked_by_hand


def _rows(screen) -> set[str]:
    rows = screen._user_picker_form._existing_list.walk(restrict=True)
    return {w.text for w in rows if "session" in getattr(w, "text", "")}


def test_entering_settings_reads_the_counts_again():
    counts = {1: 5}
    screen = SettingsScreen()
    wire(screen, session_counter=lambda uid: counts[uid])
    screen.populate_users([{"id": 1, "name": "Mock"}], 1)
    assert _rows(screen) == {"Mock (5 sessions)"}
    counts[1] = 6  # a session saved since
    screen.on_pre_enter()
    assert _rows(screen) == {"Mock (6 sessions)"}


def _session_ended_on(app, screen: str) -> None:
    """A mock session of two ticks, ended (a timer's way: no confirm) while `screen` shows."""
    start_ticked_by_hand(app, ticks=2)
    app._switch_screen(screen)
    app._stop_and_save(reason="timer")
    frames()


def test_the_end_of_a_session_redraws_them_on_settings(fresh_app):
    app = fresh_app
    app._switch_screen("settings")
    name = app._profiles.current_name()
    assert _rows(app._settings_screen) == {f"{name} (0 sessions)"}
    _session_ended_on(app, "settings")  # a timer ended it there
    assert _rows(app._settings_screen) == {f"{name} (1 session)"}


def test_elsewhere_entering_settings_redraws_them_instead(fresh_app):
    app = fresh_app
    name = app._profiles.current_name()
    _session_ended_on(app, "live_session")
    assert _rows(app._settings_screen) == {f"{name} (0 sessions)"}  # not drawn again behind the Session screen
    app._switch_screen("settings")
    frames()
    assert _rows(app._settings_screen) == {f"{name} (1 session)"}


def test_a_failed_count_shows_the_profile_without_one_and_the_end_card_still_opens(fresh_app, monkeypatch):
    app = fresh_app

    def failing(*_args):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(app._db, "count_sessions", failing)
    _session_ended_on(app, "settings")
    form = app._settings_screen._user_picker_form
    assert {w.text for w in form._existing_list.walk(restrict=True) if getattr(w, "text", "") == app._profiles.current_name()}
    assert app._live_screen.summary_session_id is not None  # the end card


def test_a_running_sessions_row_is_counted_once_it_ends(fresh_app):
    app = fresh_app
    uid = app._current_user_id
    app._db.save_session({"duration": 600}, user_id=uid)
    start_ticked_by_hand(app, ticks=2)
    app._checkpoint_or_report()  # its first checkpoint: the row exists
    assert len(app._db.get_all_sessions(uid)) == 2
    assert app._profiles.count_sessions(uid) == 1 == len(app._history.finished_sessions(uid))
    app._stop_and_save()
    assert app._profiles.count_sessions(uid) == 2 == len(app._history.finished_sessions(uid))


def test_the_count_is_each_profiles_own_and_zero_once_the_database_is_closing(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    try:
        first, second = db.create_user("Mock"), db.create_user("Second mock")
        for uid in (first, first, second):
            db.save_session({"duration": 60}, user_id=uid)
        assert (db.count_sessions(first), db.count_sessions(second)) == (2, 1)
        db.mark_shutting_down()
        db.close()
        assert db.count_sessions(first) == 0  # late access is a no-op, never a crash
    finally:
        db.close()
