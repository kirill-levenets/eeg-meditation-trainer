"""While a session runs, the metric it is scored on can't change: the audio metric, the formula slot that drives it and
that slot's formula are refused with a message, and the Settings controls show the metric in force again. The other
formula slots stay editable: they are only drawn."""
import pytest

from app.metrics.formula_slots import FORMULA_KEYS
from tests._app import popup_message, popups, program_mode, reload_with, setting_writes

SLOTS = [{"name": "Custom 1", "formula": "alpha1 / beta1 * 100"}, {"name": "Custom 2", "formula": "theta / alpha1 * 100"},
         {"name": "Custom 3", "formula": ""}]


@pytest.fixture
def idle(fresh_app, monkeypatch):
    """The app, two of its formula slots filled and a formula saved; `app.writes` records its settings writes."""
    app = fresh_app
    app._db.add_saved_formula(app._current_user_id, "Calm ratio", "alpha2 / beta2 * 100")
    reload_with(app, {"active_formulas": SLOTS})
    app.writes = setting_writes(app, monkeypatch)
    return app


@pytest.fixture
def app(idle):
    """The same, in a session."""
    idle._on_start()
    return idle


def _refused(a) -> bool:
    if not popups():
        return False
    (popup,) = popups()
    assert popup.title == "Session in progress" and popup_message(popup).startswith("Stop the current session before")
    return True


def _slot_inputs(a, idx: int) -> tuple[str, str]:
    section = a._settings_screen.formulas
    return section._formula_name_inputs[idx].text, section._formula_inputs[idx].text


def _type_into_slot(a, idx: int, name: str, formula: str) -> None:
    section = a._settings_screen.formulas
    section._formula_name_inputs[idx].text, section._formula_inputs[idx].text = name, formula
    section._submit_slot(idx)


def test_the_audio_metric_cant_change_while_a_session_runs(app):
    app._audio_metric.on_change("meditation_score")
    assert _refused(app)
    assert app._settings_store.value("audio_metric") == "shamatha_score" and app.writes == []
    assert app._settings_screen.audio_metric == "shamatha_score"  # the radio shows the metric in force again


def test_the_audio_metric_changes_when_no_session_runs(idle):
    idle._audio_metric.on_change("meditation_score")
    assert not _refused(idle)
    assert idle._settings_store.value("audio_metric") == "meditation_score"
    assert ("audio_metric", "meditation_score") in idle.writes


def test_the_metric_in_force_reselected_is_not_a_change(app):
    # The radio's snap-back re-selects it, which calls the handler again.
    app._audio_metric.on_change("shamatha_score")
    assert not _refused(app)


def test_switching_to_a_formula_while_a_session_runs_is_refused(app):
    app._audio_metric.on_change("custom_formula")
    assert _refused(app)
    assert app._settings_store.value("audio_metric") == "shamatha_score"
    assert app._settings_screen.audio_metric == "shamatha_score"


def test_the_formula_slot_that_drives_the_sound_cant_change_while_a_session_runs(app):
    app._settings_store.change("audio_metric", FORMULA_KEYS[0])
    app._audio_metric.on_formula_index(1)
    assert _refused(app)
    store = app._settings_store
    assert (store.value("audio_metric"), store.value("audio_formula_index")) == (FORMULA_KEYS[0], 0)
    assert app._settings_screen.audio_formula_index == 0


def test_picking_a_slot_while_another_metric_drives_is_only_remembered(app):
    # Shamatha drives the sound: the slot choice waits for Custom Formula to be picked, so it changes no scoring.
    app._audio_metric.on_formula_index(2)
    assert not _refused(app)
    store = app._settings_store
    assert (store.value("audio_metric"), store.value("audio_formula_index")) == ("shamatha_score", 2)


def test_the_driving_slots_formula_cant_change_while_a_session_runs(app):
    app._settings_store.change("audio_metric", FORMULA_KEYS[0])
    _type_into_slot(app, 0, "Calm ratio", "alpha2 / beta2 * 100")
    assert _refused(app)
    assert app._formulas.evaluators[0].formula == "alpha1 / beta1 * 100"
    assert _slot_inputs(app, 0) == ("Custom 1", "alpha1 / beta1 * 100")  # inputs restored


def test_the_driving_slot_cant_be_cleared_either(app):
    app._settings_store.change("audio_metric", FORMULA_KEYS[0])
    _type_into_slot(app, 0, "", "")
    assert _refused(app)
    assert app._formulas.evaluators[0].is_valid


def test_other_slots_stay_editable_during_a_session(app):
    app._settings_store.change("audio_metric", FORMULA_KEYS[0])
    _type_into_slot(app, 1, "Drowsy", "theta / beta1 * 100")
    assert not _refused(app)
    assert app._formulas.evaluators[1].formula == "theta / beta1 * 100"


def test_choosing_a_saved_formula_for_the_driving_slot_is_refused(app):
    app._settings_store.change("audio_metric", FORMULA_KEYS[0])
    app._formula_settings.assign_saved(0, {"name": "Calm ratio", "formula": "alpha2 / beta2 * 100"})
    assert _refused(app)
    assert app._formulas.evaluators[0].formula == "alpha1 / beta1 * 100"


def test_loading_a_saved_formula_into_the_driving_slot_is_refused(app):
    # Load fills the first empty slot; when that slot is the one driving the sound (selected but empty, so the
    # session is scored on its shamatha fallback), filling it would switch the scored metric.
    app._settings_store.change("audio_metric", FORMULA_KEYS[2])
    app._formula_settings.on_load(0)
    assert _refused(app)
    assert not app._formulas.evaluators[2].is_valid
    assert _slot_inputs(app, 2) == ("Custom 3", "")  # inputs restored


@pytest.mark.parametrize("call, doing", [
    (lambda a: a._profiles.on_switch(a._current_user_id + 1), "switching profiles"),
    (lambda a: a._backup_flow.on_restore_pressed(), "restoring a backup"),
])
def test_the_other_session_locks_say_the_same(app, call, doing):
    call(app)
    (popup,) = popups()
    assert (popup.title, popup_message(popup)) == ("Session in progress", f"Stop the current session before {doing}.")


def test_a_program_session_leaves_the_audio_metric_free(idle):
    # A program is scored per segment, on the segments' own metrics: the audio control metric plays no part.
    program_mode(idle, [{"minutes": 5, "target": 60, "formula": "meditation_score"}])
    idle._on_start()
    idle._settings_store.change("audio_metric", FORMULA_KEYS[0])
    idle._audio_metric.on_change("meditation_score")
    _type_into_slot(idle, 1, "Drowsy", "theta / beta1 * 100")
    assert not _refused(idle)
    assert idle._settings_store.value("audio_metric") == "meditation_score"
