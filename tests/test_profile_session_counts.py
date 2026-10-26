"""Settings › User Profile's session counts are current whenever Settings shows them, and count what History lists."""
import sqlite3
from unittest.mock import MagicMock

from app.session.manager import SessionState
from app.storage.database import DatabaseManager
from app.ui.app_manager import EEGMeditationApp
from app.ui.hooks import wire
from app.ui.settings_screen import SettingsScreen


def _rows(screen) -> set[str]:
    return {w.text for w in screen._user_picker_form._existing_list.walk() if "session" in getattr(w, "text", "")}


def test_entering_settings_reads_the_counts_again():
    counts = {1: 5}
    screen = SettingsScreen()
    wire(screen, session_counter=lambda uid: counts[uid])
    screen.populate_users([{"id": 1, "name": "Mock"}], 1)
    assert _rows(screen) == {"Mock (5 sessions)"}
    counts[1] = 6  # a session saved since
    screen.on_pre_enter()
    assert _rows(screen) == {"Mock (6 sessions)"}


def _ending_app(shown: str) -> EEGMeditationApp:
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    for name in ("_live_screen", "_mirror", "_session_manager", "_settings_screen", "_undo_session_setup",
                 "_mark_history_dirty"):
        setattr(app, name, MagicMock())
    app._sm = MagicMock(current=shown)
    return app


def test_the_end_of_a_session_redraws_them_on_settings():
    app = _ending_app("settings")  # a timer ended it there
    app._finalize_stop_ui({}, None)
    app._settings_screen.refresh_profile_counts.assert_called_once_with()


def test_elsewhere_entering_settings_redraws_them_instead():
    app = _ending_app("live_session")
    app._finalize_stop_ui({}, None)
    app._settings_screen.refresh_profile_counts.assert_not_called()


def test_a_failed_count_shows_the_profile_without_one_and_the_end_card_still_opens():
    app = _ending_app("settings")
    app._db = MagicMock()
    app._db.count_sessions.side_effect = sqlite3.OperationalError("disk I/O error")
    app._db.get_session.return_value = {"id": 9, "date_time": "2026-10-03T20:05:46", "session_name": "Mock"}
    app._recorder, app._waiting_for_bt, app._ticker = MagicMock(session_id=9), False, MagicMock(running=False)
    app._session_manager.state = SessionState.FINISHED
    screen = SettingsScreen()
    wire(screen, session_counter=app._count_sessions_for_user)
    app._settings_screen = screen
    screen.populate_users([{"id": 1, "name": "Mock"}], 1)
    app._finalize_stop_ui({"duration": 96}, 9)
    assert {w.text for w in screen._user_picker_form._existing_list.walk() if getattr(w, "text", "") == "Mock"}
    app._live_screen.show_summary.assert_called_once()


def test_a_running_sessions_row_is_counted_once_it_ends(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    try:
        uid = db.create_user("Mock")
        db.save_session({"duration": 600}, user_id=uid)
        running = db.save_session({"duration": 60}, user_id=uid)  # its first checkpoint
        app = EEGMeditationApp.__new__(EEGMeditationApp)
        app._db, app._waiting_for_bt, app._ticker = db, False, MagicMock(running=False)
        app._session_manager, app._recorder = MagicMock(), MagicMock(session_id=running)
        app._session_manager.state = SessionState.RUNNING
        assert app._count_sessions_for_user(uid) == 1 == len(app._finished_sessions(uid))
        app._session_manager.state = SessionState.IDLE
        assert app._count_sessions_for_user(uid) == 2
    finally:
        db.close()


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
