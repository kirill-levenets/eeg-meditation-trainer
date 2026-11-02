"""The app made by its real constructor and build(), as main.py makes it, on a temp DB: the startup profile is restored,
or the gate blocks the app until one is made; the screens' hooks reach their flows, and each profile's settings come
back."""
import time

import pytest
from kivy.base import EventLoop
from kivy.core.window import Window

import app.ui.app_manager as am
from app.config import APP
from app.eeg.neurosky_stream import NeuroSkyStream
from app.storage.database import DatabaseManager
from app.ui.line_colours import LINE_COLOURS
from app.ui.theme import C, F
from app.ui.widgets.user_picker import UserPickerForm


def _frames(n: int = 10) -> None:
    for _ in range(n):
        EventLoop.idle()


def _frames_until(done, seconds: float = 3.0) -> None:
    end = time.monotonic() + seconds
    while not done() and time.monotonic() < end:
        EventLoop.idle()


def _tap(parent, label: str) -> None:
    next(w for w in parent.walk() if getattr(w, "text", None) == label).dispatch("on_release")


def _create(form: UserPickerForm, name: str) -> None:
    form._name_input.text = name
    form._on_create_pressed()


@pytest.fixture
def build_app(tmp_path, monkeypatch):
    """build(seed): the app built on a DB that `seed(db)` prepared; with the mock headset, so no profile load scans."""
    monkeypatch.setattr(APP, "DB_PATH", str(tmp_path / "meditation.db"))
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", True)
    monkeypatch.setattr(NeuroSkyStream, "scan_paired_devices", staticmethod(lambda: []))
    installed: list = []
    monkeypatch.setattr(am, "install_crash_handler", installed.append)  # its hooks are process-wide
    theme, scale, colours = C.theme_name, F.SCALE, LINE_COLOURS.name
    apps = []

    def build(seed):
        seeding = DatabaseManager(db_path=APP.DB_PATH)
        seed(seeding)
        seeding.close()
        app = am.EEGMeditationApp()
        app.build()
        assert installed[-1] is app
        apps.append(app)
        return app

    try:
        yield build
    finally:
        for app in apps:
            _frames()  # what the app queued runs while it is whole
            if app._gate._gate_popup is not None:
                app._gate._gate_popup.dismiss()
            Window.unbind(on_key_down=app._on_key_down, on_keyboard=app._on_keyboard)
            app._db.close()
        C.set_theme(theme)
        F.set_scale(scale)
        LINE_COLOURS.set(colours)


def _last_used(name: str):
    def seed(db):
        uid = db.create_user(name)
        db.set_setting("last_user_id", str(uid))
        db.set_user_setting(uid, "use_mock", "True")
    return seed


def test_the_built_app_restores_its_profile_and_the_hooks_reach_their_flows(build_app):
    app = build_app(_last_used("me"))
    uid = app._current_user_id
    assert uid is not None and not app._gate.shown() and not app._bottom_nav.disabled
    _tap(app._history_screen._toggle_col, "14d")  # History -> HistoryFlow -> the profile's setting
    assert app._db.get_user_setting(uid, "history_view_mode") == "bars"
    app._settings_screen.audio._sinking_alert_cb.active = True  # Settings -> the settings store
    form = app._settings_screen._user_picker_form
    _create(form, "other")  # Settings -> Profiles
    other = next(u["id"] for u in app._db.get_all_users() if u["name"] == "other")
    _create(form, "other")
    assert "already exists" in form._error_label.text and len(app._db.get_all_users()) == 2
    app._profiles.on_switch(other)
    _frames()
    assert app._history_screen._view_mode == "calendar" and not app._settings_screen.audio._sinking_alert_cb.active
    app._profiles.on_switch(uid)
    _frames()
    assert app._history_screen._view_mode == "bars" and app._settings_screen.audio._sinking_alert_cb.active


def test_with_no_profile_to_restore_the_gate_blocks_the_app_until_one_is_made(build_app):
    app = build_app(lambda db: db.create_user("old"))  # a profile, but none last used: a restored DB, a reinstall
    assert app._current_user_id is None and app._bottom_nav.disabled  # at once: no tap before the gate is up
    _frames_until(app._gate.shown)
    gate_form = next(w for w in app._gate._gate_popup.walk() if isinstance(w, UserPickerForm))
    _create(gate_form, "new")
    _frames()
    new = next(u["id"] for u in app._db.get_all_users() if u["name"] == "new")
    assert app._current_user_id == new and not app._gate.shown() and not app._bottom_nav.disabled
    assert app._backup_flow._user_name() == "new"  # the profile a backup is named after
