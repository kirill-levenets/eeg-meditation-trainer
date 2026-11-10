"""A profile switch mid-session would reload timer/threshold/sound settings under the running session."""
import pytest

from tests._app import frames, popup_titles, reload_with


@pytest.fixture
def app(fresh_app):
    """The app on its profile (`app.mine`, threshold 60), with a profile B (`app.other`, threshold 85) to switch to."""
    app = fresh_app
    reload_with(app, threshold="60")
    app.mine, app.other = app._current_user_id, app._db.create_user("B")
    app._db.set_user_setting(app.other, "threshold", "85")
    app._db.set_user_setting(app.other, "use_mock", "True")
    app._profiles.refresh()
    return app


def _current(app) -> str:
    return app._settings_screen._profile_current_label.text


def test_switch_is_refused_while_a_session_runs(app):
    mine = _current(app)
    app._on_start()
    app._settings_screen._profile_current_label.text = "Current: B"  # what the picker's tap showed
    app._profiles.on_switch(app.other)
    frames()
    assert app._current_user_id == app.mine and popup_titles() == ["Session in progress"]
    assert app._settings_screen.threshold == 60  # B's settings were not loaded under the running session
    assert _current(app) == mine  # the picker snapped back


def test_switch_proceeds_when_idle(app):
    app._settings_screen.threshold = 62  # changed, not yet saved
    app._profiles.on_switch(app.other)
    frames()
    assert app._current_user_id == app.other and popup_titles() == []
    assert app._settings_screen.threshold == 85 and _current(app) == "Current: B"
    assert app._db.get_user_setting(app.mine, "threshold") == "62"  # the first profile's settings were saved first
