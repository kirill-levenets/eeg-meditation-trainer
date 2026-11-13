"""Change-callbacks persist through the settings registry; a settings save never touches the live timer."""
import pytest
from kivy.core.window import Window

from app.config import APP
from app.metrics.formula_slots import FORMULA_KEYS
from app.session.session_program import PROGRAM_FORMULA_KEYS
from app.ui.hooks import wire
from app.ui.settings_screen import SettingsScreen
from tests._app import FedSession, frames, program_mode, reload_with, setting_writes

# --- change-callback -> store.persist wiring -------------------------------------


def test_the_alert_toggles_and_the_rotation_are_applied_and_persist_via_the_store(fresh_app, monkeypatch):
    app = fresh_app
    writes = setting_writes(app, monkeypatch)
    audio = app._settings_screen.audio
    audio._disconnect_alert_cb.active = True
    audio._subtle_alert_cb.active = True
    app._settings_screen.display.on_rotate_screen(90)
    assert app._audio.disconnect_alert_enabled is True and Window.rotation == 90
    assert writes == [("disconnect_alert", "True"), ("subtle_alert", "True"), ("rotation", "90")]


def test_audio_formula_index_switch_copersists_metric(fresh_app, monkeypatch):
    # Switching the driving slot must persist BOTH audio_metric and audio_formula_index,
    # or a reload (which reconciles the index from audio_metric) reverts it.
    app = fresh_app
    app._settings_store.change("audio_metric", "custom_formula")  # a FORMULA_KEY -> this slot drives audio
    writes = setting_writes(app, monkeypatch)
    app._audio_metric.on_formula_index(1)
    assert dict(writes) == {"audio_formula_index": "1", "audio_metric": "custom_formula_2"}


def test_a_program_slot_is_never_saved_as_the_audio_metric(fresh_app, monkeypatch):
    # A program slot outside a program reads 0: constant max noise. Healed on save as well as on load.
    app = fresh_app
    app._settings_store.change("audio_metric", PROGRAM_FORMULA_KEYS[0])  # nothing writes one today; the save keeps it so
    writes = setting_writes(app, monkeypatch)
    app._settings_store.persist(app._current_user_id, "audio_metric")
    assert writes == [("audio_metric", "shamatha_score")]


# --- a settings save leaves the live timer alone --------------------------------

def test_saving_settings_mid_program_keeps_the_programs_timer(fresh_app):
    """A pause/backup flush mid-program must not reapply the simple-mode timer widgets (that killed auto-stop)."""
    app = fresh_app
    reload_with(app, timer_enabled="False", timer_minutes="20")
    program_mode(app, [{"minutes": 30, "target": 60, "formula": "shamatha_score"},
                       {"minutes": 15, "target": 60, "formula": "meditation_score"}])
    app._on_start()  # the program force-enables the timer, with the program's total
    assert (app._session.timer.enabled, app._session.timer.duration_minutes) == (True, 45)
    app._save_user_settings()
    assert (app._session.timer.enabled, app._session.timer.duration_minutes) == (True, 45)
    assert app._db.get_user_setting(app._current_user_id, "timer_enabled") == "False"  # the profile's own, as saved


def test_re_picking_the_profile_mid_program_keeps_the_programs_end(fresh_app, monkeypatch):
    # Re-picking the active profile is allowed mid-session and reloads its settings: its timer, stored off, disabled
    # the program's timer, and the program never ended.
    app = fresh_app
    reload_with(app, timer_enabled="False")
    program_mode(app, [{"minutes": 1, "target": 50, "formula": "shamatha_score"}])
    fed = FedSession(app, monkeypatch)
    app._profiles.on_switch(app._current_user_id)
    for _ in range(int(60 / APP.UPDATE_FREQUENCY)):
        fed.tick()
    frames()
    sessions = app._db.get_all_sessions(app._current_user_id)
    assert app._session.run is None and app._live_screen.summary_session_id == sessions[0]["id"]  # ended at 1 min, end card up


def test_re_picking_the_profile_keeps_a_timed_session_timed_after_the_timer_was_unticked(fresh_app, monkeypatch):
    # An untick during the session is for the next one; the re-pick saves it first, then loads it.
    app = fresh_app
    reload_with(app, timer_enabled="True", timer_minutes="5")
    FedSession(app, monkeypatch)
    app._settings_screen.timer.timer_enabled = False
    app._profiles.on_switch(app._current_user_id)
    assert (app._session.timer.enabled, app._session.timer.remaining_seconds) == (True, 300.0)


def test_re_picking_the_profile_keeps_a_running_formulas_window(fresh_app, monkeypatch):
    # Its avg() is the session's: the reload sets the formula the slot runs, and a reset scored the next ticks on less.
    app = fresh_app
    reload_with(app, {"active_formulas": [{"name": "W", "formula": "avg(alpha1, 4)"}]}, audio_metric="custom_formula")
    fed = FedSession(app, monkeypatch)
    fed.raw = {**fed.raw, "alpha1": 100.0}
    for _ in range(4):
        fed.tick()
    app._profiles.on_switch(app._current_user_id)
    fed.raw = {**fed.raw, "alpha1": 0.0}
    fed.tick()
    assert app._session.recorder._buffer[-1]["custom_formula"] == pytest.approx(75.0)


def test_the_formula_slot_switch_tells_the_app_and_shows_a_slot_set_elsewhere():
    screen = SettingsScreen()
    picked = []
    wire(screen, on_audio_formula_index=picked.append)
    screen._slot_toggle.buttons[2].dispatch("on_release")
    assert (picked, screen.audio_formula_index, screen._slot_toggle.chosen) == ([2], 2, 2)
    screen.audio_formula_index = 0  # a profile's load
    assert (picked, screen._slot_toggle.chosen) == ([2], 0)


def test_a_stored_formula_metric_loads_its_slot_and_the_load_writes_nothing(fresh_app, monkeypatch):
    app = fresh_app
    reload_with(app, {"active_formulas": [{"name": "A", "formula": "alpha1"}, {"name": "B", "formula": "beta1"},
                                          {"name": "Custom 3", "formula": ""}]}, audio_metric=FORMULA_KEYS[1])
    store = app._settings_store
    assert (store.value("audio_metric"), store.value("audio_formula_index")) == (FORMULA_KEYS[1], 1)
    assert app._settings_screen.audio_formula_index == 1  # Settings shows the slot that drives the sound
    writes = setting_writes(app, monkeypatch)
    app._activate_user(app._current_user_id)  # the load again
    assert writes == [] and store.value("audio_metric") == FORMULA_KEYS[1]  # nothing of the load's own
