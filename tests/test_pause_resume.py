"""Tests for EEGMeditationApp pause/resume flag handling.

Verifies that:
- on_pause sets _is_paused True
- on_resume clears _is_paused
- _update_tick respects _is_paused (skips per-tick UI dispatch)

These behaviors are critical for Android screen-lock UX:
- _is_paused prevents the tick thread from queueing thousands of Clock
  callbacks during a long screen lock that previously caused a black
  screen on resume.
"""

from unittest.mock import MagicMock


def _make_minimal_app():
    """Construct an EEGMeditationApp instance with stubbed dependencies.

    Bypasses __init__ via __new__ so we don't need Kivy widgets / DB / EEG
    streams to assert the pause flag handling.
    """
    from app.ui.app_manager import EEGMeditationApp

    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._is_paused = False
    app._save_user_settings = MagicMock()

    fake_state = MagicMock()
    fake_state.name = "IDLE"
    app._session_manager = MagicMock()
    app._session_manager.state = fake_state
    app._session_manager.elapsed_formatted = "0:00"
    app._live_screen = MagicMock()
    return app


def test_on_pause_sets_is_paused_flag():
    from app.ui.app_manager import EEGMeditationApp

    app = _make_minimal_app()
    assert app._is_paused is False

    result = EEGMeditationApp.on_pause(app)
    assert result is True
    assert app._is_paused is True
    assert app._save_user_settings.called


def test_on_resume_clears_is_paused_flag():
    from app.ui.app_manager import EEGMeditationApp

    app = _make_minimal_app()
    app._is_paused = True

    EEGMeditationApp.on_resume(app)
    assert app._is_paused is False
