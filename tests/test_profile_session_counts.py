"""Settings › User Profile's session counts are current whenever Settings shows them, and count what History lists."""
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


def test_the_end_of_a_session_redraws_them():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    for name in ("_live_screen", "_mirror", "_settings_screen", "_undo_session_setup", "_mark_history_dirty"):
        setattr(app, name, MagicMock())
    app._finalize_stop_ui({}, None)
    app._settings_screen.refresh_profile_counts.assert_called_once_with()


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
