"""UI-callback settings writes: continuous inputs write once they settle; a DB error is never fatal."""

import sqlite3
from collections import deque
from types import SimpleNamespace
from unittest.mock import MagicMock

import app.ui.app_manager as am
from app.session.manager import SessionManager
from app.ui.app_manager import EEGMeditationApp


class _FakeTrigger:
    """Stands in for a Kivy Clock trigger so tests decide when the settle window ends."""

    def __init__(self, fn, timeout):
        self.fn, self.timeout, self.armed = fn, timeout, False

    def cancel(self):
        self.armed = False

    def __call__(self):
        self.armed = True

    def fire(self):
        if self.armed:
            self.armed = False
            self.fn(0)


def _make_app(monkeypatch):
    triggers: list[_FakeTrigger] = []

    def create_trigger(fn, timeout):
        triggers.append(_FakeTrigger(fn, timeout))
        return triggers[-1]

    monkeypatch.setattr(am, "Clock", SimpleNamespace(create_trigger=create_trigger))
    reports: list[tuple] = []
    monkeypatch.setattr(am, "report_soft_error", lambda label, detail="", **_: reports.append((label, detail)))
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._loading_settings = False
    app._settle_triggers = {}
    app._current_user_id = 7
    app._settings_store = MagicMock()
    app._metrics_engine = MagicMock()
    app._audio = MagicMock()
    app._live_screen = MagicMock()
    app._timer_state = MagicMock()
    app._session_manager = SessionManager()
    app._session_program_active = False
    app._settings_screen = MagicMock(threshold=180)
    app._ui_metrics_history, app._ui_band_history, app._ui_raw_waveform = deque(), deque(), deque()
    return app, triggers, reports


def test_a_threshold_drag_writes_once_after_it_settles(monkeypatch):
    app, triggers, _ = _make_app(monkeypatch)
    for v in range(20, 181):  # a full slider sweep
        app._on_threshold_change(v)

    app._settings_store.persist.assert_not_called()
    assert len(triggers) == 2  # one puts the settled value in force, one saves it
    for t in triggers:
        t.fire()
    app._settings_store.persist.assert_called_once_with(7, "threshold")
    app._audio.set_threshold.assert_called_once_with(180)


def test_typing_a_gong_path_writes_once_after_it_settles(monkeypatch):
    app, triggers, _ = _make_app(monkeypatch)
    path = "/home/user/sounds/my_custom_gong_sound.wav"
    for i in range(1, len(path) + 1):
        app._on_timer_sound_change(path[:i])

    app._settings_store.persist.assert_not_called()
    triggers[0].fire()
    app._settings_store.persist.assert_called_once_with(7, "timer_sound")


def test_no_write_is_scheduled_while_settings_load(monkeypatch):
    app, triggers, _ = _make_app(monkeypatch)
    app._loading_settings = True
    app._on_threshold_change(90)
    assert "threshold" not in app._settle_triggers  # the load applies the value itself; nothing saves it back


def test_a_failed_setting_write_is_reported_not_raised(monkeypatch):
    app, _, reports = _make_app(monkeypatch)
    app._settings_store.persist.side_effect = sqlite3.OperationalError("database is locked")

    app._persist_user_setting("sinking_alert")  # must not raise into the Kivy callback

    assert reports and reports[0][0] == "settings_save_failed"
    assert "database is locked" in reports[0][1]


def test_a_failed_batch_save_is_reported_not_raised(monkeypatch):
    app, _, reports = _make_app(monkeypatch)
    app._settings_store.save.side_effect = sqlite3.OperationalError("disk I/O error")

    app._save_user_settings()  # the pre-backup flush path; must not crash the app

    assert reports and reports[0][0] == "settings_save_failed"
