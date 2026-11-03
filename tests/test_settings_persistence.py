"""Change-callbacks persist through the settings registry; a settings save never touches the live timer."""
from unittest.mock import MagicMock

from app.metrics.formula_slots import FORMULA_KEYS
from app.session.manager import SessionManager
from app.session.session_program import PROGRAM_FORMULA_KEYS
from app.session.timer_state import TimerState
from app.settings.registry import BOOL, INT, Setting, SettingsStore
from app.ui.app_manager import EEGMeditationApp
from app.ui.hooks import wire
from app.ui.settings_screen import SettingsScreen
from tests._audio_metric import make_audio_metric
from tests._program_run import make_run


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
    app._ticker = MagicMock(running=False)  # no session's tick running
    app._current_user_id = uid
    app._loading_settings = False
    app._db = _FakeDB()
    app._session_manager = SessionManager()  # idle: nothing running owns the settings
    app._program_run = make_run(app)
    return app


# --- change-callback -> store.persist wiring -------------------------------------

def test_disconnect_alert_toggle_persists_via_store():
    app = _app()
    app._audio = type("A", (), {})()
    s = Setting("disconnect_alert", False, BOOL[0], BOOL[1], None,  # the store holds it
                lambda v: setattr(app._audio, "disconnect_alert_enabled", v))
    app._settings_store = SettingsStore(app._db, [s])
    app._on_disconnect_alert_toggle(True)
    assert app._audio.disconnect_alert_enabled is True
    assert (7, "disconnect_alert", "True") in app._db.writes


def test_the_subtle_alert_and_the_rotation_persist_via_store():
    app = _app()
    applied = {}
    held = [Setting(key, default, codec[0], codec[1], None, lambda v, k=key: applied.__setitem__(k, v))
            for key, default, codec in (("subtle_alert", False, BOOL), ("rotation", 0, INT))]
    app._settings_store = SettingsStore(app._db, held)
    app._on_subtle_alert_toggle(True)
    app._on_rotate_screen(90)
    assert applied == {"subtle_alert": True, "rotation": 90}
    assert {(7, "subtle_alert", "True"), (7, "rotation", "90")} <= set(app._db.writes)


def test_audio_formula_index_switch_copersists_metric():
    # Switching the driving slot must persist BOTH audio_metric and audio_formula_index,
    # or a reload (which reconciles the index from audio_metric) reverts it.
    app = _app()
    app._settings_screen = MagicMock()
    app._audio_metric = make_audio_metric(app)
    store = app._settings_store = SettingsStore(app._db, app._audio_metric.settings())
    store.change("audio_metric", "custom_formula")  # a FORMULA_KEY -> this slot drives audio
    app._audio_metric.on_formula_index(1)
    stored = {k: v for _, k, v in app._db.writes}
    assert stored == {"audio_formula_index": "1", "audio_metric": "custom_formula_2"}


def test_a_program_slot_is_never_saved_as_the_audio_metric():
    # A program slot outside a program reads 0: constant max noise. Healed on save as well as on load.
    app = _app()
    app._settings_screen = MagicMock()
    store = app._settings_store = SettingsStore(app._db, make_audio_metric(app).settings())
    store.change("audio_metric", PROGRAM_FORMULA_KEYS[0])  # nothing writes one today; the save keeps it so
    store.persist(7, "audio_metric")
    assert app._db.writes == [(7, "audio_metric", "shamatha_score")]


def test_persist_noop_without_store():
    # __new__ instances (many unit tests) have no _settings_store -> persist is a no-op.
    app = _app()
    app._audio = type("A", (), {})()
    # no _settings_store attribute set
    app._persist_user_setting("disconnect_alert")   # must not raise


# --- a settings save leaves the live timer alone --------------------------------

def test_saving_settings_mid_program_keeps_the_programs_timer():
    """A pause/backup flush mid-program must not reapply the simple-mode timer widgets (that killed auto-stop)."""
    app = _app()
    app._timer_state = TimerState()
    app._timer_state.set_enabled(True)   # program force-enables the timer...
    app._timer_state.set_duration(45)    # ...with the program's total
    app._settings_screen = MagicMock(**{"timer.timer_enabled": False, "timer.timer_minutes": 20})
    app._settings_store = MagicMock()
    app._formula_settings = MagicMock()
    app._program_settings = MagicMock()
    app._graph_series = MagicMock()

    app._save_user_settings()

    assert app._timer_state.enabled is True
    assert app._timer_state.duration_minutes == 45
    app._settings_store.save.assert_called_once_with(7)


def test_the_formula_slot_switch_tells_the_app_and_shows_a_slot_set_elsewhere():
    screen = SettingsScreen()
    picked = []
    wire(screen, on_audio_formula_index=picked.append)
    screen._slot_toggle.buttons[2].dispatch("on_release")
    assert (picked, screen.audio_formula_index, screen._slot_toggle.chosen) == ([2], 2, 2)
    screen.audio_formula_index = 0  # a profile's load
    assert (picked, screen._slot_toggle.chosen) == ([2], 0)


def test_a_stored_formula_metric_loads_its_slot_and_the_load_writes_nothing():
    app = _app()
    app._loading_settings = True  # as _load_user_settings holds it
    app._db.writes.append((7, "audio_metric", FORMULA_KEYS[1]))
    app._settings_screen = MagicMock()
    app._audio_metric = make_audio_metric(app)
    store = app._settings_store = SettingsStore(app._db, app._audio_metric.settings())
    store.load(7)
    assert (store.value("audio_metric"), store.value("audio_formula_index")) == (FORMULA_KEYS[1], 1)
    assert app._db.writes == [(7, "audio_metric", FORMULA_KEYS[1])]  # nothing of the load's own
    assert app._settings_screen.audio_formula_index == 1  # Settings shows the slot that drives the sound
