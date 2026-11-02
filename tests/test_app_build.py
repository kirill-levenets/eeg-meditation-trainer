"""The app made by its real constructor and build(), as main.py makes it, on a temp DB whose profile uses the mock
headset: the startup profile is restored, the screens' hooks reach their flows, and each profile's settings come back."""
import pytest
from kivy.base import EventLoop
from kivy.core.window import Window

import app.ui.app_manager as am
from app.config import APP
from app.eeg.neurosky_stream import NeuroSkyStream
from app.storage.database import DatabaseManager
from app.ui.line_colours import LINE_COLOURS
from app.ui.theme import C, F


def _frames(n: int = 10) -> None:
    for _ in range(n):
        EventLoop.idle()


def _tap(parent, label: str) -> None:
    next(w for w in parent.walk() if getattr(w, "text", None) == label).dispatch("on_release")


@pytest.fixture
def built(tmp_path, monkeypatch):
    db_path = str(tmp_path / "meditation.db")
    seed = DatabaseManager(db_path=db_path)
    uid = seed.create_user("me")
    seed.set_setting("last_user_id", str(uid))
    seed.set_user_setting(uid, "use_mock", "True")  # no headset scan at the load
    seed.close()
    monkeypatch.setattr(APP, "DB_PATH", db_path)
    monkeypatch.setattr(NeuroSkyStream, "scan_paired_devices", staticmethod(lambda: []))
    installed = []
    monkeypatch.setattr(am, "install_crash_handler", installed.append)  # its hooks are process-wide
    theme, scale, colours = C.theme_name, F.SCALE, LINE_COLOURS.name
    app = am.EEGMeditationApp()
    app.build()
    try:
        yield app, uid, installed
    finally:
        _frames()  # what the app queued runs while it is whole
        Window.unbind(on_key_down=app._on_key_down, on_keyboard=app._on_keyboard)
        app._db.close()
        C.set_theme(theme)
        F.set_scale(scale)
        LINE_COLOURS.set(colours)


def test_the_built_app_restores_its_profile_and_the_hooks_reach_their_flows(built):
    app, uid, installed = built
    assert installed == [app]
    assert app._current_user_id == uid and not app._gate.shown() and not app._bottom_nav.disabled
    _tap(app._history_screen._toggle_col, "14d")  # History -> HistoryFlow -> the profile's setting
    assert app._db.get_user_setting(uid, "history_view_mode") == "bars"
    app._settings_screen.audio._sinking_alert_cb.active = True  # Settings -> the settings store
    other = app._db.create_user("other")
    app._profiles.on_switch(other)
    _frames()
    assert app._history_screen._view_mode == "calendar" and not app._settings_screen.audio._sinking_alert_cb.active
    app._profiles.on_switch(uid)
    _frames()
    assert app._history_screen._view_mode == "bars" and app._settings_screen.audio._sinking_alert_cb.active
