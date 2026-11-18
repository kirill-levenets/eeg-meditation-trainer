"""The app's pause and resume (Android: a screen lock and unlock): pausing saves what was changed and raises the flag
that keeps a locked session's ticks from queueing a redraw each; resuming drops it."""
from tests._app import frames


def test_a_pause_saves_the_settings_and_raises_the_paused_flag(fresh_app):
    app = fresh_app
    app._settings_screen.threshold = 62  # a slider move still inside its settle window: not yet written
    assert app._session.ui_paused is False and app._db.get_user_setting(app._current_user_id, "threshold") != "62"
    assert app.on_pause() is True
    assert app._session.ui_paused is True and app._db.get_user_setting(app._current_user_id, "threshold") == "62"


def test_a_resume_drops_the_paused_flag(fresh_app):
    app = fresh_app
    app.on_pause()
    app.on_resume()
    frames()
    assert app._session.ui_paused is False
