"""What-if scoring of a stored session: its ticks re-scored against other targets with the live accrual, so at the
recorded targets it gives back the recorded time above threshold and longest streak."""

from app.session.manager import SessionManager
from app.session.what_if import Segment, Stats, rescore, scored_ticks, segments_of

VALUES = [60, 72, 75, 80, 50, 90, 91, 92, 40, 88, 95, 96, 97, 30, 99]


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


# ---- segments ----


def test_segments_are_runs_of_the_same_metric_and_target():
    keys = ["a", "a", "a", "b", "b", "b"]
    targets = [70, 70, 85, 85, 85, 60]
    assert segments_of(keys, targets) == [Segment("a", 70, 0, 2), Segment("a", 85, 2, 3), Segment("b", 85, 3, 5),
                                          Segment("b", 60, 5, 6)]
    assert segments_of([], []) == []


# ---- known answers: the recorded targets give back the recorded stats ----


def test_a_simple_session_at_its_recorded_threshold():
    stats, rows = _live(VALUES, [70] * len(VALUES))
    ticks = scored_ticks({"threshold_used": 70}, rows, {})
    total, _ = rescore(ticks, [s.target for s in ticks.segments])
    assert _stored(total) == _recorded(stats)


def test_a_session_whose_threshold_moved():
    stats, rows = _live(VALUES, [70] * 7 + [90] * 8)
    ticks = scored_ticks({"threshold_used": 70}, rows, {})
    assert [s.target for s in ticks.segments] == [70, 90]
    total, _ = rescore(ticks, [70, 90])
    assert _stored(total) == _recorded(stats)


def test_a_program_whose_streak_carries_across_a_boundary():
    # 90 91 92 (shamatha, target 90) then 95 96 97 on a formula at target 95: one unbroken run across the boundary.
    values = [50, 90, 91, 92, 95, 96, 97, 20]
    keys = ["shamatha_score"] * 4 + ["custom_formula"] * 4
    targets = [90] * 4 + [95] * 4
    stats, rows = _live(values, targets, keys)
    ticks = scored_ticks({"threshold_used": 90}, rows, {})  # the engine; the panel doesn't offer programs yet
    total, per_segment = rescore(ticks, [90, 95])
    assert _stored(total) == _recorded(stats)
    assert total.longest_streak == 3.0  # six ticks across the boundary
    assert per_segment == [Stats(1.5, 1.5), Stats(1.5, 1.5)]  # within each segment


# ---- what-if ----


def test_another_threshold_rescores_every_tick():
    _stats, rows = _live(VALUES, [70] * len(VALUES))
    total, per_segment = rescore(scored_ticks({"threshold_used": 70}, rows, {}), [90])
    # >= 90: 90 91 92 | 95 96 97 | 99 -> 7 ticks, the longest run 3 ticks.
    assert total == Stats(3.5, 1.5) and per_segment == [Stats(3.5, 1.5)]


def test_exactly_the_target_counts_as_above():
    _stats, rows = _live([80, 80], [80, 80])
    total, _ = rescore(scored_ticks({"threshold_used": 80}, rows, {}), [80])
    assert total == Stats(1.0, 1.0)


def test_one_segment_moved_changes_only_it_and_the_total():
    values = [50, 90, 91, 92, 95, 96, 97, 20]
    keys = ["shamatha_score"] * 4 + ["custom_formula"] * 4
    _stats, rows = _live(values, [90] * 4 + [95] * 4, keys)
    ticks = scored_ticks({"threshold_used": 90}, rows, {})
    total, per_segment = rescore(ticks, [90, 97])
    assert per_segment[0] == Stats(1.5, 1.5)  # unchanged
    assert per_segment[1] == Stats(0.5, 0.5)  # only 97 is at or above 97
    assert total == Stats(2.0, 1.5)


def test_an_empty_session_scores_nothing():
    total, per_segment = rescore(scored_ticks({"threshold_used": 70}, [], {}), [])
    assert total == Stats(0.0, 0.0) and per_segment == []


# ---- sessions recorded before each tick stored what it was scored on ----


def _old_rows(values: list[float], key: str) -> list[dict]:
    return [{key: v, "score_key": None, "score_value": None, "score_target": None} for v in values]


def test_an_older_session_is_scored_on_its_saved_metric_at_its_threshold():
    ticks = scored_ticks({"threshold_used": 70, "score_metric_key": "shamatha_score"},
                         _old_rows(VALUES, "shamatha_score"), {})
    assert ticks.values == VALUES and set(ticks.keys) == {"shamatha_score"} and set(ticks.targets) == {70}


def test_an_older_session_on_a_formula_takes_the_replayed_series():
    series = [float(v) * 2 for v in VALUES]
    ticks = scored_ticks({"threshold_used": 150, "score_metric_key": "custom_formula"},
                         _old_rows(VALUES, "shamatha_score"), {"custom_formula": series})
    assert ticks.values == series and set(ticks.keys) == {"custom_formula"}


def test_a_session_from_before_the_metric_was_saved_is_scored_on_meditation():
    # What its recorded time above and streak were measured on (#51).
    ticks = scored_ticks({"threshold_used": 70, "score_metric_key": ""}, _old_rows(VALUES, "meditation_score"), {})
    assert ticks.values == VALUES and set(ticks.keys) == {"meditation_score"}


def test_a_program_session_is_not_scored_here_yet():
    _stats, rows = _live(VALUES, [70] * len(VALUES))
    for record in (rows, _old_rows(VALUES, "shamatha_score")):  # with its per-tick record or without
        assert scored_ticks({"threshold_used": 70, "score_metric_key": "program", "session_program": "[{}]"},
                            record, {}) is None


def test_an_older_formula_session_the_replay_couldnt_rebuild_is_not_scored():
    # Its stored custom_formula column is stale or 0: scoring it would contradict the recorded numbers.
    assert scored_ticks({"threshold_used": 150, "score_metric_key": "custom_formula_2"},
                        _old_rows(VALUES, "custom_formula_2"), {}) is None


def test_the_whole_session_alone_skips_the_segments():
    _stats, rows = _live(VALUES, [70] * len(VALUES))
    total, per_segment = rescore(scored_ticks({"threshold_used": 70}, rows, {}), [90], per_segment=False)
    assert total == Stats(3.5, 1.5) and per_segment == []


def test_a_record_missing_on_some_ticks_is_not_trusted():
    _stats, rows = _live(VALUES, [70] * len(VALUES))
    rows[3] = {**rows[3], "score_key": None, "score_value": None, "score_target": None}
    ticks = scored_ticks({"threshold_used": 70, "score_metric_key": "shamatha_score"}, rows, {})
    assert ticks.values == VALUES  # the saved metric's stored column, every tick
