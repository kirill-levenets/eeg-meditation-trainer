"""A profile switch mid-session would reload timer/threshold/sound settings under the running session."""

from unittest.mock import MagicMock

from app.session.manager import SessionState
from app.ui.app_manager import EEGMeditationApp


def _make_app(state: SessionState) -> EEGMeditationApp:
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._session_manager = MagicMock()
    app._session_manager.state = state
    app._waiting_for_bt = False
    app._tick_thread = None
    app._current_user_id = 1
    app._view_all_users = False
    app._db = MagicMock()
    app._db.get_user.return_value = {"name": "B"}
    app._info_popup = MagicMock()
    app._refresh_profile = MagicMock()
    app._save_user_settings = MagicMock()
    app._load_user_settings = MagicMock()
    app._mark_history_dirty = MagicMock()
    return app


def test_switch_is_refused_while_a_session_runs():
    app = _make_app(SessionState.RUNNING)
    app._on_user_switch(2)

    assert app._current_user_id == 1
    app._save_user_settings.assert_not_called()
    app._load_user_settings.assert_not_called()
    app._info_popup.assert_called_once()
    app._refresh_profile.assert_called_once()


def test_all_users_view_is_refused_while_a_session_runs():
    app = _make_app(SessionState.PAUSED)
    app._on_user_switch(None)
    assert app._current_user_id == 1
    assert app._view_all_users is False


def test_switch_proceeds_when_idle():
    app = _make_app(SessionState.IDLE)
    app._on_user_switch(2)

    assert app._current_user_id == 2
    app._save_user_settings.assert_called_once()
    app._load_user_settings.assert_called_once_with(2)
    app._info_popup.assert_not_called()
