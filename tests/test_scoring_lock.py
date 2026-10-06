"""While a session runs, the metric it is scored on can't change: the audio metric, the formula slot that drives it and
that slot's formula are refused with a message, and the Settings controls show the metric in force again. The other
formula slots stay editable: they are only drawn."""

from unittest.mock import MagicMock

import pytest

from app.metrics.custom_formula import CustomFormulaEvaluator
from app.ui.app_manager import FORMULA_KEYS, EEGMeditationApp


@pytest.fixture
def app(monkeypatch):
    a = EEGMeditationApp.__new__(EEGMeditationApp)
    a._live = True
    monkeypatch.setattr(EEGMeditationApp, "_session_pipeline_live", lambda self: self._live)
    a._info_popup = MagicMock()
    a._settings_screen = MagicMock()
    a._live_screen = MagicMock()
    a._persist_user_setting = MagicMock()
    a._current_user_id = None  # no formula persistence in these tests
    a._formula_slots = [CustomFormulaEvaluator() for _ in FORMULA_KEYS]
    a._formula_names = [f"Custom {i + 1}" for i in range(len(FORMULA_KEYS))]
    a._formula_slots[0].set_formula("alpha1 / beta1 * 100")
    a._formula_slots[1].set_formula("theta / alpha1 * 100")
    a._audio_metric_key = "shamatha_score"
    a._audio_formula_index = 0
    a._session_program_active = False
    return a


def _refused(a) -> bool:
    if not a._info_popup.called:
        return False
    title, message = a._info_popup.call_args.args
    assert title == "Session in progress" and message.startswith("Stop the current session before")
    return True


def test_the_audio_metric_cant_change_while_a_session_runs(app):
    app._on_audio_metric_change("meditation_score")
    assert _refused(app)
    assert app._audio_metric_key == "shamatha_score"
    app._persist_user_setting.assert_not_called()
    assert app._settings_screen.audio_metric == "shamatha_score"  # the radio shows the metric in force again


def test_the_audio_metric_changes_when_no_session_runs(app):
    app._live = False
    app._on_audio_metric_change("meditation_score")
    assert not _refused(app)
    assert app._audio_metric_key == "meditation_score"


def test_the_metric_in_force_reselected_is_not_a_change(app):
    # The radio's snap-back re-selects it, which calls the handler again.
    app._on_audio_metric_change("shamatha_score")
    assert not _refused(app)


def test_switching_to_a_formula_while_a_session_runs_is_refused(app):
    app._on_audio_metric_change("custom_formula")
    assert _refused(app)
    assert app._audio_metric_key == "shamatha_score"
    assert app._settings_screen.audio_metric == "shamatha_score"


def test_the_formula_slot_that_drives_the_sound_cant_change_while_a_session_runs(app):
    app._audio_metric_key = FORMULA_KEYS[0]
    app._on_audio_formula_index(1)
    assert _refused(app)
    assert (app._audio_metric_key, app._audio_formula_index) == (FORMULA_KEYS[0], 0)
    assert app._settings_screen.audio_formula_index == 0


def test_picking_a_slot_while_another_metric_drives_is_only_remembered(app):
    # Shamatha drives the sound: the slot choice waits for Custom Formula to be picked, so it changes no scoring.
    app._on_audio_formula_index(2)
    assert not _refused(app)
    assert (app._audio_metric_key, app._audio_formula_index) == ("shamatha_score", 2)


def test_the_driving_slots_formula_cant_change_while_a_session_runs(app):
    app._audio_metric_key = FORMULA_KEYS[0]
    app._on_formula_slot_change(0, "Calm ratio", "alpha2 / beta2 * 100")
    assert _refused(app)
    assert app._formula_slots[0].formula == "alpha1 / beta1 * 100"
    app._settings_screen.set_formula_slot.assert_called_with(0, "Custom 1", "alpha1 / beta1 * 100")  # inputs restored


def test_the_driving_slot_cant_be_cleared_either(app):
    app._audio_metric_key = FORMULA_KEYS[0]
    app._on_formula_slot_change(0, "", "")
    assert _refused(app)
    assert app._formula_slots[0].is_valid


def test_other_slots_stay_editable_during_a_session(app):
    app._audio_metric_key = FORMULA_KEYS[0]
    app._on_formula_slot_change(1, "Drowsy", "theta / beta1 * 100")
    assert not _refused(app)
    assert app._formula_slots[1].formula == "theta / beta1 * 100"


def test_choosing_a_saved_formula_for_the_driving_slot_is_refused(app):
    app._audio_metric_key = FORMULA_KEYS[0]
    app._assign_saved_to_slot(0, {"name": "Calm ratio", "formula": "alpha2 / beta2 * 100"})
    assert _refused(app)
    assert app._formula_slots[0].formula == "alpha1 / beta1 * 100"


def test_loading_a_saved_formula_into_the_driving_slot_is_refused(app, monkeypatch):
    # Load fills the first empty slot; when that slot is the one driving the sound (selected but empty, so the
    # session is scored on its shamatha fallback), filling it would switch the scored metric.
    app._audio_metric_key = FORMULA_KEYS[2]
    app._current_user_id = 1
    app._require_user = lambda action: 1
    app._persist_active_formulas = MagicMock()
    app._db = MagicMock()
    app._db.get_saved_formulas.return_value = [{"name": "Calm ratio", "formula": "alpha2 / beta2 * 100"}]
    app._on_load_formula(0)
    assert _refused(app)
    assert not app._formula_slots[2].is_valid
    app._settings_screen.set_formula_slot.assert_called_with(2, "Custom 3", "")  # inputs restored


@pytest.mark.parametrize("call, doing", [
    (lambda a: a._on_user_switch(7), "switching profiles"),
    (lambda a: a._on_restore_pressed(), "restoring a backup"),
])
def test_the_other_session_locks_say_the_same(app, call, doing):
    app._current_user_id = 3
    app._refresh_profile = MagicMock()
    call(app)
    assert app._info_popup.call_args.args == ("Session in progress", f"Stop the current session before {doing}.")


def test_a_program_session_leaves_the_audio_metric_free(app):
    # A program is scored per segment, on the segments' own metrics: the audio control metric plays no part.
    app._session_program_active = True
    app._audio_metric_key = FORMULA_KEYS[0]
    app._on_audio_metric_change("meditation_score")
    app._on_formula_slot_change(1, "Drowsy", "theta / beta1 * 100")
    assert not _refused(app)
    assert app._audio_metric_key == "meditation_score"
