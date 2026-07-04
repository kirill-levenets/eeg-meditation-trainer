"""Change-callbacks persist immediately through the settings registry, and the
timer→model sync is skipped while a session is live (issue #30)."""
from app.settings.registry import BOOL, INT, STR, Setting, SettingsStore
from app.ui.app_manager import EEGMeditationApp


class _FakeDB:
    def __init__(self):
        self.writes = []

    def get_user_setting(self, uid, key):
        for u, k, v in reversed(self.writes):
            if (u, k) == (uid, key):
                return v
        return None

    def set_user_setting(self, uid, key, value):
        self.writes.append((uid, key, value))


def _app(uid=7):
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._current_user_id = uid
    app._loading_settings = False
    app._db = _FakeDB()
    return app


# --- change-callback -> store.persist wiring -------------------------------------

def test_disconnect_alert_toggle_persists_via_store():
    app = _app()
    app._audio = type("A", (), {})()
    s = Setting("disconnect_alert", False, BOOL[0], BOOL[1],
                lambda: app._audio.disconnect_alert_enabled,
                lambda v: setattr(app._audio, "disconnect_alert_enabled", v))
    app._settings_store = SettingsStore(app._db, [s])
    app._on_disconnect_alert_toggle(True)
    assert app._audio.disconnect_alert_enabled is True
    assert (7, "disconnect_alert", "True") in app._db.writes


def test_audio_formula_index_switch_copersists_metric():
    # Switching the driving slot must persist BOTH audio_metric and audio_formula_index,
    # or a reload (which reconciles the index from audio_metric) reverts it.
    app = _app()
    app._audio_metric_key = "custom_formula"     # a FORMULA_KEY -> this slot drives audio
    app._audio_formula_index = 0
    idx_s = Setting("audio_formula_index", 0, INT[0], INT[1],
                    lambda: app._audio_formula_index, lambda v: None)
    met_s = Setting("audio_metric", "shamatha_score", STR[0], STR[1],
                    lambda: app._baseline_audio_metric(app._audio_metric_key), lambda v: None)
    app._settings_store = SettingsStore(app._db, [idx_s, met_s])
    app._on_audio_formula_index(1)
    keys = [k for _, k, _ in app._db.writes]
    assert "audio_formula_index" in keys and "audio_metric" in keys


def test_persist_noop_without_store():
    # __new__ instances (many unit tests) have no _settings_store -> persist is a no-op.
    app = _app()
    app._audio = type("A", (), {})()
    # no _settings_store attribute set
    app._on_disconnect_alert_toggle(True)   # must not raise


# --- timer->model sync guard (issue #30) ----------------------------------------

def _spy_timer_app(live):
    app = _app()
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
    app, calls = _spy_timer_app(live=True)
    app._sync_timer_state_from_ui()
    assert calls == []


def test_timer_sync_applies_when_idle():
    app, calls = _spy_timer_app(live=False)
    app._sync_timer_state_from_ui()
    assert ("enabled", True) in calls and ("duration", 20) in calls
