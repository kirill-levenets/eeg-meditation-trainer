import json

import pytest

from app.metrics.custom_formula import CustomFormulaEvaluator
from app.metrics.formula_slots import FORMULA_KEYS, FormulaSlots, read_active
from app.session.scoring import sound_metric
from app.storage.database import DatabaseManager
from tests._app import (
    FedSession,
    frames,
    popup_message,
    popups,
    reload_with,
    start_ticked_by_hand,
    tap,
)
from tests._audio_metric import audio_metric_alone

# ---- the three formula slots ----


def test_three_independent_slots():
    slots = FormulaSlots()
    assert len(slots.evaluators) == 3
    assert tuple(FORMULA_KEYS) == ("custom_formula", "custom_formula_2", "custom_formula_3")
    slots.evaluators[0].set_formula("avg(alpha1, 3)")
    slots.evaluators[1].set_formula("avg(alpha1, 3)")
    for v in (10.0, 20.0, 30.0):
        slots.evaluators[0].push_variables({"alpha1": v})
    slots.evaluators[1].push_variables({"alpha1": 99.0})
    assert slots.evaluators[0].evaluate({"alpha1": 0.0}) != slots.evaluators[1].evaluate({"alpha1": 0.0})


def test_formula_for_key():
    slots = FormulaSlots()
    assert slots.for_key("custom_formula") is slots.evaluators[0]
    assert slots.for_key("custom_formula_3") is slots.evaluators[2]
    assert slots.for_key("shamatha_score") is None


def test_first_empty_slot():
    slots = FormulaSlots()
    assert slots.first_empty() == 0
    slots.evaluators[0].set_formula("alpha")
    assert slots.first_empty() == 1
    for ev in slots.evaluators:
        ev.set_formula("alpha")
    assert slots.first_empty() == 0  # all full → slot 0


def test_a_profile_whose_stored_formula_cant_run_loads_that_slot_empty(caplog):
    # A failed set keeps the evaluator's formula: the last profile's would run under this one's name.
    slots = FormulaSlots()
    slots.load([{"name": "A", "formula": "alpha1"}])
    slots.load([{"name": "B", "formula": "alpha1 +"}])
    assert (slots.names[0], slots.evaluators[0].formula, slots.evaluators[0].is_valid) == ("B", "", False)
    assert "'alpha1 +' can't run" in caplog.text


# ---- the profile's formulas, stored and loaded ----


def test_active_formulas_round_trip(fresh_app):
    app, uid = fresh_app, fresh_app._current_user_id
    app._formulas.load([{"name": "Ratio", "formula": "alpha + beta"}, {"name": "Med", "formula": "meditation_score"}])
    app._formula_settings.persist(uid)
    app._formulas.load([])  # whatever the slots held since
    app._activate_user(uid)  # the profile's load
    assert app._formulas.names[0] == "Ratio"
    assert app._formulas.evaluators[0].is_valid and app._formulas.evaluators[0].formula == "alpha + beta"
    assert not app._formulas.evaluators[2].is_valid


def test_legacy_single_formula_migrates_to_slot1(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "t.db"))
    try:
        uid = db.create_user("A")
        db.set_user_setting(uid, "custom_formula", "alpha / (beta + 1)")
        active = read_active(db, uid)
        assert (active[0]["formula"], active[0]["name"]) == ("alpha / (beta + 1)", "Custom 1")
    finally:
        db.close()


# ---- which metric drives the sound ----


def test_audio_falls_back_to_shamatha_when_bound_slot_invalid():
    slots = FormulaSlots()  # slot 2 bound, but slot 2 has no formula
    assert sound_metric("custom_formula_2", "", slots) == "shamatha_score"
    slots.evaluators[1].set_formula("alpha + beta")  # now valid
    assert sound_metric("custom_formula_2", "", slots) == "custom_formula_2"


def test_audio_drive_key_passthrough_for_non_formula():
    assert sound_metric("shamatha_score", "", FormulaSlots()) == "shamatha_score"


def test_index_tap_does_not_rebind_when_non_formula_active():
    # Tapping a slot button while a non-formula metric drives audio only
    # remembers the slot; it must not silently switch the live key.
    changes = []
    audio_metric_alone(change_setting=lambda key, value: changes.append((key, value))).on_formula_index(1)
    assert changes == [("audio_formula_index", 1)]


_WINDOW = {"active_formulas": [{"name": "W", "formula": "avg(alpha1, 4)"}]}


@pytest.mark.parametrize("next_profile", ["same", "another with the same formula"])
def test_a_new_session_averages_only_its_own_ticks(fresh_app, monkeypatch, next_profile):
    # The slots outlive sessions and profiles: the last session's ticks filled the next one's first averages.
    app = fresh_app
    reload_with(app, _WINDOW, audio_metric="custom_formula")
    fed = FedSession(app, monkeypatch)
    fed.raw = {**fed.raw, "alpha1": 100.0}
    for _ in range(4):
        fed.tick()
    app._stop_and_save()
    frames()
    app._shown.close(keep_notes=False)
    if next_profile != "same":
        other = app._db.create_user("other")
        app._db.set_user_json_setting(other, "active_formulas", _WINDOW["active_formulas"])
        app._db.set_user_setting(other, "audio_metric", "custom_formula")
        app._profiles.on_switch(other)
        frames()
    fed = FedSession(app, monkeypatch)
    fed.raw = {**fed.raw, "alpha1": 0.0}
    fed.tick()
    assert app._session.recorder._buffer[-1]["custom_formula"] == 0.0


# ---- a session records its formulas; its detail replays them ----


def _saved_with_formulas(app) -> tuple[int, dict]:
    """A one-tick session started with the formulas in the slots now, saved with its record: (its id, its row)."""
    start_ticked_by_hand(app)
    sid = app._db.save_session({"duration": 1}, user_id=app._current_user_id,
                               custom_formulas=app._session.custom_formulas_json())
    app._db.save_metrics_batch(sid, [{"timestamp": 0.5, "alpha1": 100, "alpha2": 50, "beta1": 10, "beta2": 5}])
    return sid, app._db.get_session(sid)


def test_record_includes_visible_and_drove_audio(fresh_app):
    app = fresh_app
    app._formulas.evaluators[0].set_formula("alpha + beta")
    app._formulas.names[0] = "Ratio"
    app._settings_store.change("audio_metric", "custom_formula")
    start_ticked_by_hand(app)
    app._live_screen.graph.set_visible("custom_formula", True)  # shown during the session: Start derives the series
    rec = json.loads(app._session.custom_formulas_json())
    assert (rec[0]["name"], rec[0]["formula"]) == ("Ratio", "alpha + beta")
    assert rec[0]["visible"] and rec[0]["drove_audio"]


def test_replay_recomputes_from_stored_defs(fresh_app):
    app = fresh_app
    app._formulas.evaluators[0].set_formula("alpha + beta")
    app._formulas.names[0] = "Ratio"
    sid, session = _saved_with_formulas(app)
    # Mutate today's slot — replay must ignore it and use the stored def.
    app._formulas.evaluators[0].set_formula("delta")
    series, names = app._detail.compute_session_formulas(sid, session)
    ev = CustomFormulaEvaluator()
    ev.set_formula("alpha + beta")
    expected = app._db.recompute_formula_series(sid, {FORMULA_KEYS[0]: ev})
    assert series[FORMULA_KEYS[0]] == expected[FORMULA_KEYS[0]]
    assert series[FORMULA_KEYS[0]][0] == pytest.approx(165.0, abs=1e-3)
    assert names[FORMULA_KEYS[0]] == "Ratio"


def test_replay_sparse_slots_map_to_correct_keys(fresh_app):
    # Slots 0 and 2 valid, slot 1 empty — replay must land on custom_formula
    # and custom_formula_3, NOT pack densely onto custom_formula_2.
    app = fresh_app
    app._formulas.evaluators[0].set_formula("alpha + beta")
    app._formulas.evaluators[2].set_formula("alpha1")
    series, _names = app._detail.compute_session_formulas(*_saved_with_formulas(app))
    assert set(series) == {FORMULA_KEYS[0], FORMULA_KEYS[2]}
    assert series[FORMULA_KEYS[0]][0] == pytest.approx(165.0, abs=1e-3)  # alpha+beta
    assert series[FORMULA_KEYS[2]][0] == pytest.approx(100.0, abs=1e-3)  # alpha1


def test_replay_with_no_formulas_is_empty_and_resets_the_names(fresh_app):
    app = fresh_app
    series, names = app._detail.compute_session_formulas(*_saved_with_formulas(app))  # no valid slots
    assert series == {}
    # All custom keys reset to defaults so a prior session's name can't leak.
    assert names[FORMULA_KEYS[1]] == "Custom 2"


def test_replay_tolerates_malformed_json(fresh_app):
    app = fresh_app
    sid = app._db.save_session({"duration": 1}, user_id=app._current_user_id, custom_formulas="{not json")
    series, _names = app._detail.compute_session_formulas(sid, app._db.get_session(sid))  # must not raise
    assert series == {}


# ---- saved formulas ----


def test_assign_saved_formula_to_slot(fresh_app):
    app = fresh_app
    app._formula_settings.assign_saved(0, {"name": "Ratio", "formula": "alpha + beta"})
    assert app._formulas.evaluators[0].is_valid and app._formulas.names[0] == "Ratio"
    assert app._live_screen.graph.is_visible("custom_formula")


def test_deleting_a_saved_formula_asks_first_like_a_saved_program(fresh_app):
    app, uid = fresh_app, fresh_app._current_user_id
    app._db.add_saved_formula(uid, "Ratio", "alpha / beta")
    app._formula_settings.refresh_saved()
    app._formula_settings.on_delete(0)
    (popup,) = popups()
    assert "Ratio" in popup_message(popup) and len(app._db.get_saved_formulas(uid)) == 1  # asked, nothing deleted yet
    tap(popup.content, "Delete")  # OK
    assert app._db.get_saved_formulas(uid) == []
