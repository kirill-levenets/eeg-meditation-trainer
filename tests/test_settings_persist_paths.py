"""UI-callback settings writes: continuous inputs write once they settle; a DB error is never fatal."""
import sqlite3

import pytest

import app.ui.app_manager as am
from tests._app import frames, frames_until, setting_writes

SETTLE_S = 0.05


@pytest.fixture
def app(build_app, monkeypatch):
    """The built app with a short settle window; `app.writes` records its settings writes, `app.reports` its soft
    errors."""
    monkeypatch.setattr(am.EEGMeditationApp, "_PERSIST_SETTLE_S", SETTLE_S)  # read when a trigger is first made
    app = build_app()
    frames_until(lambda: False, 2 * SETTLE_S)  # what the profile's load queued has run
    app.writes = setting_writes(app, monkeypatch)
    app.reports = []
    monkeypatch.setattr(am, "report_soft_error", lambda label, detail="", **_: app.reports.append((label, detail)))
    return app


def _settled(app, key: str) -> list[str]:
    """The values written for `key` once the settle window has passed."""
    frames_until(lambda: any(k == key for k, _ in app.writes), 1.0)
    frames_until(lambda: False, 2 * SETTLE_S)  # a second write would come by now
    return [v for k, v in app.writes if k == key]


def test_a_threshold_drag_writes_once_after_it_settles(app):
    for v in range(20, 181):  # a full slider sweep
        app._settings_screen.threshold = v
    assert app.writes == [] and app._session_manager.threshold != 180
    assert _settled(app, "threshold") == ["180"]
    assert app._session_manager.threshold == 180  # put in force once too, at the value it settled on


def test_typing_a_gong_path_writes_once_after_it_settles(app):
    path = "/home/user/sounds/my_custom_gong_sound.wav"
    for i in range(1, len(path) + 1):
        app._sounds.on_timer_sound_change(path[:i])
    assert app.writes == []
    assert _settled(app, "timer_sound") == [path]


def test_a_line_width_drag_writes_once_after_it_settles(app):
    # It was written only by the batch save (leaving the app, a profile switch), so a crash before one lost it.
    for width in (1.3, 1.6, 2.0):
        app._settings_screen.display._line_width_slider.value = width
    assert app.writes == [] and app._settings_store.value("line_width") == 2.0  # held at once, written later
    assert _settled(app, "line_width") == ["2.0"]


def test_a_toggle_writes_at_once(app):
    app._settings_screen.audio._sinking_alert_cb.active = True
    assert app.writes == [("sinking_alert", "True")]


def test_no_write_is_scheduled_while_settings_load(app):
    app._db.set_user_setting(app._current_user_id, "threshold", "90")
    app.writes.clear()
    app._activate_user(app._current_user_id)  # the load applies the value itself; nothing saves it back
    frames_until(lambda: False, 4 * SETTLE_S)
    assert app._settings_screen.threshold == 90 and app.writes == []


def _locked(*_args):
    raise sqlite3.OperationalError("database is locked")


def test_a_failed_setting_write_is_reported_not_raised(app, monkeypatch):
    monkeypatch.setattr(app._db, "set_user_setting", _locked)
    app._settings_screen.audio._sinking_alert_cb.active = True  # must not raise into the Kivy callback
    assert app.reports and app.reports[0][0] == "settings_save_failed"
    assert "database is locked" in app.reports[0][1]
    assert app._settings_store.value("sinking_alert") is True  # applied in memory: the next batch save retries it


def test_a_failed_batch_save_is_reported_not_raised(app, monkeypatch):
    monkeypatch.setattr(app._db, "set_user_settings", _locked)
    app._save_user_settings()  # the pre-backup flush path; must not crash the app
    frames()
    assert app.reports and app.reports[0][0] == "settings_save_failed"
