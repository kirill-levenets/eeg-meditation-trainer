"""Immediate per-setting persistence (issue #30 Phase 2): discrete settings write to
the DB on change so a mid-session backup / force-kill keeps them, without waiting for
the batched _save_user_settings on pause/stop."""
from app.ui.app_manager import EEGMeditationApp


class _FakeDB:
    def __init__(self):
        self.writes = []

    def set_user_setting(self, uid, key, value):
        self.writes.append((uid, key, value))


def _app(uid=7, loading=False):
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._current_user_id = uid
    app._loading_settings = loading
    app._db = _FakeDB()
    return app


def test_persist_user_setting_writes_when_user_active():
    app = _app(uid=7)
    app._persist_user_setting("threshold", "80")
    assert app._db.writes == [(7, "threshold", "80")]


def test_persist_user_setting_skips_without_user():
    app = _app(uid=None)
    app._persist_user_setting("threshold", "80")
    assert app._db.writes == []


def test_persist_user_setting_skips_while_loading():
    # Callbacks fire while _load_user_settings applies restored values; re-persisting
    # them is redundant, so the flag suppresses those write-backs.
    app = _app(uid=7, loading=True)
    app._persist_user_setting("threshold", "80")
    assert app._db.writes == []


def test_alert_toggle_persists_immediately():
    app = _app(uid=7)
    app._audio = type("A", (), {})()
    app._on_disconnect_alert_toggle(True)
    assert (7, "disconnect_alert", "True") in app._db.writes


def _spy_timer_app(live):
    app = _app(uid=7)
    calls = []
    app._timer_state = type("T", (), {
        "set_enabled": lambda self, v: calls.append(("enabled", v)),
        "set_duration": lambda self, v: calls.append(("duration", v)),
        "set_custom_sound_path": lambda self, v: calls.append(("sound", v)),
    })()
    app._settings_screen = type("S", (), {
        "timer_enabled": True, "timer_minutes": 20, "timer_sound_path": "/x.wav",
    })()
    app._session_pipeline_live = lambda: live
    return app, calls


def test_timer_sync_skipped_during_live_session():
    # A live (esp. program) session owns _timer_state; a persist flush must not
    # re-apply the simple-mode Enable-Timer checkbox over it (#30 review regression).
    app, calls = _spy_timer_app(live=True)
    app._sync_timer_state_from_ui()
    assert calls == []


def test_timer_sync_applies_when_idle():
    app, calls = _spy_timer_app(live=False)
    app._sync_timer_state_from_ui()
    assert ("enabled", True) in calls and ("duration", 20) in calls


def test_audio_formula_index_switch_copersists_metric():
    # load reconciles the index FROM audio_metric, so switching the driving slot must
    # persist both keys or a reload reverts it (#30 review).
    app = _app(uid=7)
    app._audio_metric_key = "custom_formula"   # a FORMULA_KEY -> this slot drives audio
    app._audio_formula_index = 0
    app._on_audio_formula_index(1)
    keys = [k for _, k, _ in app._db.writes]
    assert "audio_formula_index" in keys and "audio_metric" in keys
