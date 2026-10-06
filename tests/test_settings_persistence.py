"""Change-callbacks persist through the settings registry; a settings save never touches the live timer."""
from unittest.mock import MagicMock

from app.session.manager import SessionManager
from app.session.timer_state import TimerState
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
    app._session_manager = SessionManager()  # idle: nothing running owns the settings
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
    stored = {k: v for _, k, v in app._db.writes}
    assert stored == {"audio_formula_index": "1", "audio_metric": "custom_formula_2"}


def test_persist_noop_without_store():
    # __new__ instances (many unit tests) have no _settings_store -> persist is a no-op.
    app = _app()
    app._audio = type("A", (), {})()
    # no _settings_store attribute set
    app._on_disconnect_alert_toggle(True)   # must not raise


# --- a settings save leaves the live timer alone --------------------------------

def test_saving_settings_mid_program_keeps_the_programs_timer():
    """A pause/backup flush mid-program must not reapply the simple-mode timer widgets (that killed auto-stop)."""
    app = _app()
    app._timer_state = TimerState()
    app._timer_state.set_enabled(True)   # program force-enables the timer...
    app._timer_state.set_duration(45)    # ...with the program's total
    app._settings_screen = MagicMock(timer_enabled=False, timer_minutes=20)
    app._settings_store = MagicMock()
    app._persist_active_formulas = MagicMock()
    app._persist_session_program = MagicMock()
    app._all_graphs = lambda: []

    app._save_user_settings()

    assert app._timer_state.enabled is True
    assert app._timer_state.duration_minutes == 45
    app._settings_store.save.assert_called_once_with(7)
