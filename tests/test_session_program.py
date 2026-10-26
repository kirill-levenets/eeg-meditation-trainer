import json

import pytest

from app.session.session_program import (
    SessionProgram,
    program_plan,
    recorded_plan,
    recorded_program,
    runnable_plan,
    segment_target,
)

BROKEN = {"name": "Broken", "formula": "alpha1 +"}
CALM = {"name": "Calm", "formula": "100 * s_alpha1"}


def _prog():
    return SessionProgram([
        {"minutes": 10, "target": 50, "formula": "shamatha_score"},
        {"minutes": 10, "target": 70, "formula": "meditation_score"},
        {"minutes": 5,  "target": 90, "formula": {"name": "X", "formula": "alpha1"}},
    ])


def test_total_seconds():
    assert _prog().total_seconds == 25 * 60


def test_segment_at_boundaries():
    p = _prog()
    assert p.segment_at(0)[0] == 0
    assert p.segment_at(599)[0] == 0
    assert p.segment_at(600)[0] == 1          # exactly at the 10-min boundary
    assert p.segment_at(1199)[0] == 1
    assert p.segment_at(1200)[0] == 2


def test_segment_at_past_total_clamps_to_last():
    p = _prog()
    idx, seg = p.segment_at(99999)
    assert idx == 2 and seg["target"] == 90


def test_boundaries():
    assert _prog().boundaries == [600, 1200, 1500]


def test_threshold_steps_tick_space():
    # sample_rate 2 Hz: 10 min = 1200 ticks, 20 min = 2400 ticks
    steps = _prog().threshold_steps(2.0)
    assert steps == [(0, 50.0), (1200, 70.0), (2400, 90.0)]


def test_empty_and_malformed():
    assert not SessionProgram([])
    assert SessionProgram([]).total_seconds == 0
    assert SessionProgram([]).segment_at(0) == (-1, None)
    # malformed entries (non-dict / zero minutes) are dropped
    p = SessionProgram([{"minutes": 0, "target": 1}, "junk", {"minutes": 5, "target": 60}])
    assert len(p.segments) == 1 and p.total_seconds == 300


def test_truthiness():
    assert bool(_prog()) is True
    assert bool(SessionProgram(None)) is False


def test_time_above_threshold_follows_active_goal():
    from app.session.manager import SessionManager, SessionState
    sm = SessionManager()
    sm._state = SessionState.RUNNING
    sm.start_segment("custom_formula", 60)
    sm.add_metric({"meditation_score": 10, "shamatha_score": 10, "custom_formula": 80})
    sm.add_metric({"meditation_score": 99, "shamatha_score": 99, "custom_formula": 20})
    # only the first tick is above the *custom_formula* goal of 60
    assert sm.compute_statistics()["time_above_threshold"] == 0  # 0.5s rounds to int 0
    sm.add_metric({"meditation_score": 0, "shamatha_score": 0, "custom_formula": 90})
    assert sm._time_above_threshold == 1.0  # two ticks @ 0.5s above goal


def test_a_program_arms_one_evaluator_per_custom_formula_that_compiles():
    prog = SessionProgram([{"minutes": 1, "target": 50, "formula": {"name": "ok", "formula": "100 * s_alpha1"}},
                           {"minutes": 1, "target": 50, "formula": {"name": "bad", "formula": "100 *"}},
                           {"minutes": 1, "target": 50, "formula": "shamatha_score"}])
    assert list(runnable_plan(prog).evaluators) == ["program_formula"]  # "bad" gets no evaluator


def test_a_formula_that_cant_run_moves_every_segment_of_it_to_shamatha_and_keeps_the_others_slots():
    prog = SessionProgram([{"minutes": 1, "formula": BROKEN}, {"minutes": 1, "formula": CALM},
                           {"minutes": 1, "formula": BROKEN}, {"minutes": 1, "formula": "meditation_score"}])
    plan = runnable_plan(prog)
    assert plan.segment_keys == ["shamatha_score", "program_formula_2", "shamatha_score", "meditation_score"]
    assert plan.planned_keys == ["program_formula", "program_formula_2", "program_formula", "meditation_score"]
    assert plan.keys == {"shamatha_score", "program_formula_2", "meditation_score"}  # no line for Broken
    assert plan.customs == [("program_formula_2", CALM)] and list(plan.evaluators) == ["program_formula_2"]
    assert plan.unrunnable == ["Broken"]  # once, though two segments use it


def test_a_program_whose_formulas_all_run_is_its_plan():
    prog = SessionProgram([{"minutes": 1, "formula": CALM}, {"minutes": 1, "formula": "shamatha_score"}])
    plan, (keys, customs, segment_keys) = runnable_plan(prog), program_plan(prog)
    assert (plan.keys, plan.customs, plan.segment_keys, plan.planned_keys) == (keys, customs, segment_keys,
                                                                            segment_keys)
    assert plan.unrunnable == []


def test_a_fourth_formula_shares_the_last_slot_and_its_fate():
    # More than three distinct formulas reuse the last slot: they drive what that slot runs.
    prog = SessionProgram([{"minutes": 1, "formula": {"name": f"F{i}", "formula": f"alpha1 * {i}"}} for i in (1, 2)]
                          + [{"minutes": 1, "formula": BROKEN}, {"minutes": 1, "formula": CALM}])
    plan = runnable_plan(prog)
    assert plan.segment_keys == ["program_formula", "program_formula_2", "shamatha_score", "shamatha_score"]
    assert plan.unrunnable == ["Broken"]


def test_a_segments_target_is_a_whole_number_50_when_missing():
    assert [segment_target(s) for s in ({"target": 72.5}, {"target": "80"}, {})] == [72, 80, 50]
    assert [segment_target({"target": t}) for t in (None, "", "high", float("inf"))] == [50] * 4  # unreadable: as missing
    assert SessionProgram([{"minutes": 1, "target": 72.5}, {"minutes": 1}]).threshold_steps(2) == [(0, 72), (120, 50)]


def test_a_segment_without_a_formula_shows_the_shamatha_line_it_drives():
    keys, _customs, segment_keys = program_plan(SessionProgram([{"minutes": 1, "target": 60}]))
    assert segment_keys == ["shamatha_score"] and keys == {"shamatha_score"}


@pytest.mark.parametrize("record", ['[{"minutes": "x"}]', '[{"minutes": 1e999}]', "not json", "", "[]"])
def test_a_record_that_cant_be_read_is_no_program(record):
    assert recorded_program(record) is None


@pytest.mark.parametrize("formula", [{"name": "X", "formula": 80}, {"name": ["X"], "formula": None}])
def test_a_formula_of_the_wrong_type_runs_as_one_that_doesnt_compile(formula):
    """A hand-edited or foreign record: every reader gets a plan, the recorded one and the live one alike."""
    record = json.dumps([{"minutes": 1, "target": 50, "formula": formula}])
    for plan in (recorded_plan(record), runnable_plan(SessionProgram(json.loads(record)))):
        assert (plan.keys, plan.segment_keys, plan.evaluators) == ({"shamatha_score"}, ["shamatha_score"], {})
        assert plan.unrunnable == [str(formula["name"])]


def test_a_session_detail_opened_on_an_unreadable_program_draws_its_plain_threshold():
    from app.ui.diary_screen import DiaryScreen
    detail = DiaryScreen()
    detail.set_program('[{"minutes": "x"}]')  # a hand-edited or corrupt record: no steps, never a crash
    assert detail._metrics_graph.threshold_steps is None
