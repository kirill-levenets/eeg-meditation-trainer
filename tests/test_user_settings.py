"""UserSettings' settle: a continuous input is written once it has stopped changing for the settle window."""
from unittest.mock import MagicMock

import pytest

from app.settings.registry import INT, held
from app.ui.user_settings import UserSettings
from tests._app import frames, frames_until

SETTLE_S = 0.3


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setattr(UserSettings, "SETTLE_S", SETTLE_S)
    s = UserSettings(MagicMock(), user_id=lambda: 1)
    s.register([held("width", INT, 1, lambda _v: None, settle=True)])
    frames()  # the Clock's time is now: after a pause between tests a trigger would be due at once
    return s


def _written(settings) -> list:
    return [c.args[1:] for c in settings._db.set_user_setting.call_args_list]


def test_a_drag_that_goes_on_past_the_window_is_written_once_after_it_stops(settings):
    settings.change("width", 2)
    frames_until(lambda: False, SETTLE_S * 2 / 3)
    settings.change("width", 3)  # still moving: the window starts again
    frames_until(lambda: False, SETTLE_S * 2 / 3)
    assert _written(settings) == []  # longer than one window since the first change, shorter since the last
    frames_until(lambda: _written(settings), 2.0)
    assert _written(settings) == [("width", "3")]


def test_nothing_is_written_while_a_profile_loads(settings):
    with settings.loading():
        settings.change("width", 4)
    frames_until(lambda: False, SETTLE_S * 2)
    assert _written(settings) == [] and settings.value("width") == 4  # applied, not written back
