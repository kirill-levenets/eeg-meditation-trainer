"""What-if scoring of a stored session: its ticks re-scored against other targets with the live accrual, so as recorded
(every tick against its own target) it gives back the recorded time above threshold and longest streak."""

import json

from app.session.manager import SessionManager
from app.session.scoring import target_steps
from app.session.what_if import Segment, Stats, line_steps, rescore, scored_ticks

VALUES = [60, 72, 75, 80, 50, 90, 91, 92, 40, 88, 95, 96, 97, 30, 99]
SEGMENT_TICKS = 120  # a one-minute program segment at 2 ticks a second


def _live(values: list[float], targets: list[float], keys: list[str] | None = None) -> tuple[dict, list[dict]]:
    """A session scored by the real SessionManager, tick by tick, with each tick's stored row: a program's segments
    when `keys` change, a moved threshold when only `targets` do."""
    sm = SessionManager()
    sm.start(threshold=targets[0])
    rows = []
    for i, (v, t) in enumerate(zip(values, targets)):
        key = keys[i] if keys else "shamatha_score"
        if keys:
            sm.set_active_goal(key, t)  # a program segment
        else:
            sm.set_active_goal(key)
            sm.set_threshold(t)
        tick = {key: v}
        rows.append({**tick, **sm.add_metric(tick)})
    return sm.compute_statistics(), rows


def _recorded(stats: dict) -> tuple[int, int]:
    return stats["time_above_threshold"], stats["longest_streak"]


def _stored(total: Stats) -> tuple[int, int]:
    return int(total.time_above), int(total.longest_streak)  # stored as whole seconds


def _as_recorded(ticks) -> tuple[Stats, list[Stats]]:
    return rescore(ticks, [None] * len(ticks.segments))


# ---- a simple session: one control for the whole session ----


def test_a_simple_session_at_its_recorded_threshold():
    stats, rows = _live(VALUES, [70] * len(VALUES))
    ticks = scored_ticks({"threshold_used": 70}, rows, {})
    assert ticks.segments == [Segment("shamatha_score", 70, 0, len(VALUES))]
    assert _stored(_as_recorded(ticks)[0]) == _recorded(stats)


def test_a_session_whose_threshold_moved_is_one_control_scored_as_recorded():
    stats, rows = _live(VALUES, [70] * 7 + [90] * 8)
    ticks = scored_ticks({"threshold_used": 70}, rows, {})
    assert ticks.segments == [Segment("shamatha_score", 70, 0, len(VALUES))]
    assert _stored(_as_recorded(ticks)[0]) == _recorded(stats)


def test_another_threshold_rescores_every_tick():
    _stats, rows = _live(VALUES, [70] * 7 + [90] * 8)
    total, per_segment = rescore(scored_ticks({"threshold_used": 70}, rows, {}), [90])
    # >= 90 on every tick: 90 91 92 | 95 96 97 | 99 -> 7 ticks, the longest run 3 ticks.
    assert total == Stats(3.5, 1.5) and per_segment == [Stats(3.5, 1.5)]


def test_exactly_the_target_counts_as_above():
    _stats, rows = _live([80, 80], [80, 80])
    total, _ = rescore(scored_ticks({"threshold_used": 80}, rows, {}), [80])
    assert total == Stats(1.0, 1.0)


def test_an_empty_session_scores_nothing():
    ticks = scored_ticks({"threshold_used": 70}, [], {})
    assert _as_recorded(ticks) == (Stats(0.0, 0.0), [Stats(0.0, 0.0)])


def test_the_whole_session_alone_skips_the_segments():
    _stats, rows = _live(VALUES, [70] * len(VALUES))
    total, per_segment = rescore(scored_ticks({"threshold_used": 70}, rows, {}), [90], per_segment=False)
    assert total == Stats(3.5, 1.5) and per_segment == []


# ---- sessions recorded before each tick stored what it was scored on ----


def _old_rows(columns: dict[str, list[float]]) -> list[dict]:
    n = len(next(iter(columns.values())))
    return [{**{k: v[i] for k, v in columns.items()}, "score_key": None, "score_value": None, "score_target": None}
            for i in range(n)]


def test_an_older_session_is_scored_on_its_saved_metric_at_its_threshold():
    ticks = scored_ticks({"threshold_used": 70, "score_metric_key": "shamatha_score"},
                         _old_rows({"shamatha_score": VALUES}), {})
    assert ticks.values == VALUES and set(ticks.targets) == {70}
    assert ticks.segments == [Segment("shamatha_score", 70, 0, len(VALUES))]


def test_an_older_session_on_a_formula_takes_the_replayed_series():
    series = [float(v) * 2 for v in VALUES]
    ticks = scored_ticks({"threshold_used": 150, "score_metric_key": "custom_formula"},
                         _old_rows({"shamatha_score": VALUES}), {"custom_formula": series})
    assert ticks.values == series and ticks.segments[0].key == "custom_formula"


def test_a_session_from_before_the_metric_was_saved_is_scored_on_meditation():
    # What its recorded time above and streak were measured on (#51).
    ticks = scored_ticks({"threshold_used": 70, "score_metric_key": ""}, _old_rows({"meditation_score": VALUES}), {})
    assert ticks.values == VALUES and ticks.segments[0].key == "meditation_score"


def test_an_older_formula_session_the_replay_couldnt_rebuild_is_not_scored():
    # Its stored custom_formula column is stale or 0: scoring it would contradict the recorded numbers.
    assert scored_ticks({"threshold_used": 150, "score_metric_key": "custom_formula_2"},
                        _old_rows({"custom_formula_2": VALUES}), {}) is None


def test_a_record_missing_on_some_ticks_is_not_trusted():
    _stats, rows = _live(VALUES, [70] * len(VALUES))
    rows[3] = {**rows[3], "score_key": None, "score_value": None, "score_target": None}
    ticks = scored_ticks({"threshold_used": 70, "score_metric_key": "shamatha_score"}, rows, {})
    assert ticks.values == VALUES  # the saved metric's stored column, every tick


# ---- a program: one control per segment ----

# 90 91 92 end segment 1 (Shamatha, target 90); 95 96 97 start segment 2 (a formula, target 95): one unbroken run.
SEG1 = [50.0] * (SEGMENT_TICKS - 3) + [90.0, 91.0, 92.0]
SEG2 = [95.0, 96.0, 97.0] + [20.0] * (SEGMENT_TICKS - 3)
FORMULA = {"name": "Calm", "formula": "100 * s_alpha1"}
PROGRAM = [{"minutes": 1, "target": 90, "formula": "shamatha_score"}, {"minutes": 1, "target": 95, "formula": FORMULA}]


def _program_session(program=PROGRAM) -> dict:
    return {"threshold_used": 90, "score_metric_key": "program", "session_program": json.dumps(program)}


def _live_program() -> tuple[dict, list[dict]]:
    keys = ["shamatha_score"] * SEGMENT_TICKS + ["program_formula"] * SEGMENT_TICKS
    return _live(SEG1 + SEG2, [90] * SEGMENT_TICKS + [95] * SEGMENT_TICKS, keys)


def test_a_program_has_one_control_per_segment_by_its_minutes():
    _stats, rows = _live_program()
    ticks = scored_ticks(_program_session(), rows, {})
    assert ticks.segments == [Segment("shamatha_score", 90, 0, SEGMENT_TICKS),
                              Segment("program_formula", 95, SEGMENT_TICKS, 2 * SEGMENT_TICKS, "Calm", 1)]


def test_a_program_as_recorded_gives_back_its_stats_its_streak_carrying_across_a_boundary():
    stats, rows = _live_program()
    total, per_segment = _as_recorded(scored_ticks(_program_session(), rows, {}))
    assert _stored(total) == _recorded(stats)
    assert total.longest_streak == 3.0  # six ticks across the boundary
    assert per_segment == [Stats(1.5, 1.5), Stats(1.5, 1.5)]  # within each segment


def test_one_segment_moved_changes_only_it_and_the_total():
    _stats, rows = _live_program()
    total, per_segment = rescore(scored_ticks(_program_session(), rows, {}), [None, 97])
    assert per_segment[0] == Stats(1.5, 1.5)  # as recorded
    assert per_segment[1] == Stats(0.5, 0.5)  # only 97 is at or above 97
    assert total == Stats(2.0, 1.5)


def test_an_older_program_is_replayed_from_its_columns_and_the_formulas_over_the_whole_session():
    # Every released build evaluates a program's formulas on every tick from the start, so the replay does too.
    stats, _rows = _live_program()
    rows = _old_rows({"shamatha_score": SEG1 + [0.0] * SEGMENT_TICKS})
    asked = []

    def replay(evaluators):
        asked.append(sorted(evaluators))
        return {"program_formula": [0.0] * SEGMENT_TICKS + SEG2}

    ticks = scored_ticks(_program_session(), rows, {}, replay)
    assert asked == [["program_formula"]]  # its formulas, by their series slot
    assert ticks.values == SEG1 + SEG2
    assert ticks.targets == [90.0] * SEGMENT_TICKS + [95.0] * SEGMENT_TICKS
    assert _stored(_as_recorded(ticks)[0]) == _recorded(stats)


def test_an_older_program_whose_formula_couldnt_be_replayed_is_not_scored():
    rows = _old_rows({"shamatha_score": SEG1 + SEG2})
    assert scored_ticks(_program_session(), rows, {}) is None
    assert scored_ticks(_program_session(), rows, {}, lambda _evaluators: {}) is None


def test_a_program_whose_ticks_stored_their_scoring_replays_nothing():
    _stats, rows = _live_program()
    asked = []
    assert scored_ticks(_program_session(), rows, {}, asked.append) is not None and asked == []


def test_a_program_takes_its_switches_from_the_record_when_ticks_were_dropped():
    # The live session switches segment on elapsed time: 5 ticks dropped under load put the switch at tick 115.
    keys = ["shamatha_score"] * 115 + ["program_formula"] * 120
    values = SEG1[5:] + SEG2
    stats, rows = _live(values, [90] * 115 + [95] * 120, keys)
    ticks = scored_ticks(_program_session(), rows, {})
    assert [(s.start, s.end) for s in ticks.segments] == [(0, 115), (115, 235)]
    assert _stored(_as_recorded(ticks)[0]) == _recorded(stats)
    assert line_steps(ticks, [None, 97]) == [(0, 90), (115, 97)]


def test_a_recorded_segment_like_the_one_before_it_starts_its_minutes_after_it():
    # Same metric and target: the record can't tell where one ends, so the second starts a minute after the first.
    program = [{"minutes": 1, "target": 70, "formula": "shamatha_score"}] * 2
    _stats, rows = _live([80.0] * 230, [70] * 230)
    ticks = scored_ticks(_program_session(program), rows, {})
    assert [(s.start, s.end) for s in ticks.segments] == [(0, SEGMENT_TICKS), (SEGMENT_TICKS, 230)]


def test_a_segments_target_is_read_as_the_live_session_reads_it():
    # Whole numbers (a fraction is cut), 50 when it has none.
    program = [{"minutes": 1, "target": 72.5, "formula": "shamatha_score"}, {"minutes": 1, "formula": "shamatha_score"}]
    ticks = scored_ticks(_program_session(program), _old_rows({"shamatha_score": [60.0] * 2 * SEGMENT_TICKS}), {})
    assert [s.target for s in ticks.segments] == [72, 50]
    assert set(ticks.targets[:SEGMENT_TICKS]) == {72} and set(ticks.targets[SEGMENT_TICKS:]) == {50}


def test_a_program_with_no_ticks_is_not_scored():
    assert scored_ticks(_program_session(), [], {}) is None


def test_identical_segments_keep_a_control_each():
    program = [{"minutes": 1, "target": 70, "formula": "shamatha_score"}] * 2
    ticks = scored_ticks(_program_session(program), _old_rows({"shamatha_score": [80.0] * 2 * SEGMENT_TICKS}), {})
    assert [(s.start, s.end) for s in ticks.segments] == [(0, SEGMENT_TICKS), (SEGMENT_TICKS, 2 * SEGMENT_TICKS)]


def test_a_program_stopped_early_has_controls_for_the_segments_it_reached():
    program = PROGRAM + [{"minutes": 5, "target": 50, "formula": "shamatha_score"}]
    rows = _old_rows({"shamatha_score": [80.0] * 150})
    ticks = scored_ticks(_program_session(program), rows, {"program_formula": [80.0] * 150})
    assert [(s.start, s.end) for s in ticks.segments] == [(0, SEGMENT_TICKS), (SEGMENT_TICKS, 150)]


def test_a_program_that_cant_be_read_is_not_scored():
    session = {**_program_session(), "session_program": "{not json"}
    assert scored_ticks(session, _old_rows({"shamatha_score": [80.0] * 10}), {}) is None


# ---- the graph's threshold line ----


def test_the_line_as_recorded_follows_each_ticks_target():
    _stats, rows = _live(VALUES, [70] * 7 + [90] * 8)
    ticks = scored_ticks({"threshold_used": 70}, rows, {})
    assert line_steps(ticks, [None]) == target_steps(ticks.targets) == [(0, 70), (7, 90)]
    assert line_steps(ticks, [80]) == [(0, 80)]


def test_the_line_of_a_program_moves_only_the_moved_segment():
    _stats, rows = _live_program()
    ticks = scored_ticks(_program_session(), rows, {})
    assert line_steps(ticks, [None, None]) == [(0, 90), (SEGMENT_TICKS, 95)]
    assert line_steps(ticks, [None, 97]) == [(0, 90), (SEGMENT_TICKS, 97)]
    assert line_steps(ticks, [95, None]) == [(0, 95)]  # the same target on both sides is one step


def test_a_program_with_no_segment_is_not_scored():
    session = {**_program_session(), "session_program": json.dumps([{"minutes": 0, "target": 70}])}
    assert scored_ticks(session, _old_rows({"shamatha_score": [80.0] * 10}), {}) is None


def test_an_untouched_segment_keeps_its_own_line_from_its_own_start():
    # Both segments recorded 70: one step over the session, which the untouched second segment must start at 120.
    program = [{"minutes": 1, "target": 70, "formula": "shamatha_score"}] * 2
    ticks = scored_ticks(_program_session(program), _old_rows({"shamatha_score": [80.0] * 2 * SEGMENT_TICKS}), {})
    assert line_steps(ticks, [80, None]) == [(0, 80), (SEGMENT_TICKS, 70)]


def test_a_switch_to_the_same_metric_at_another_target_is_found_by_its_target():
    program = [{"minutes": 1, "target": 90, "formula": "shamatha_score"},
               {"minutes": 1, "target": 95, "formula": "shamatha_score"}]
    _stats, rows = _live([80.0] * 235, [90] * 115 + [95] * 120)  # 5 ticks dropped before the switch
    ticks = scored_ticks(_program_session(program), rows, {})
    assert [(s.start, s.end) for s in ticks.segments] == [(0, 115), (115, 235)]


def test_a_switch_after_like_segments_is_searched_from_the_last_switch_found():
    # Meditation 60 twice, then Shamatha 70: two ticks dropped put the live switch to Shamatha at 238, not 240.
    program = [{"minutes": 1, "target": 60, "formula": "meditation_score"}] * 2 + [
        {"minutes": 1, "target": 70, "formula": "shamatha_score"}]
    keys = ["meditation_score"] * 238 + ["shamatha_score"] * 120
    _stats, rows = _live([80.0] * 358, [60] * 238 + [70] * 120, keys)
    ticks = scored_ticks(_program_session(program), rows, {})
    assert [(s.start, s.end) for s in ticks.segments] == [(0, 120), (120, 238), (238, 358)]


def test_a_segment_left_with_no_ticks_is_dropped_and_the_rest_keep_their_numbers():
    # The switch to Shamatha came before the second Meditation segment's minute began: it never ran.
    program = [{"minutes": 1, "target": 60, "formula": "meditation_score"}] * 2 + [
        {"minutes": 1, "target": 70, "formula": "shamatha_score"}]
    keys = ["meditation_score"] * 100 + ["shamatha_score"] * 120
    _stats, rows = _live([80.0] * 220, [60] * 100 + [70] * 120, keys)
    ticks = scored_ticks(_program_session(program), rows, {})
    assert [(s.index, s.start, s.end) for s in ticks.segments] == [(0, 0, 100), (2, 100, 220)]
