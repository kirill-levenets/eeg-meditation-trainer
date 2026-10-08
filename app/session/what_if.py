"""What-if scoring of a stored session (#50): its ticks re-scored against other targets with the live accrual, so as
recorded (every tick against its own target) it gives back the recorded time above threshold and longest streak. One
control for a simple session, one per segment for a program. View only: nothing is written."""

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import cached_property

from app.metrics.custom_formula import CustomFormulaEvaluator
from app.session.scoring import TICK_SECONDS, GoalAccrual, extend_steps, target_steps
from app.session.session_program import (
    SessionProgram,
    program_evaluators,
    program_plan,
    segment_target,
)

# Runs {series key: evaluator} over the session's rows, every tick from the start: {series key: value per tick}.
FormulaReplay = Callable[[dict[str, CustomFormulaEvaluator]], dict[str, list[float]]]


@dataclass(frozen=True)
class Segment:
    """The ticks one control moves: the whole of a simple session, or one segment of a program."""

    key: str  # the metric scored
    target: float  # its recorded target: where its control starts
    start: int  # its first tick
    end: int  # one past its last
    name: str = ""  # a program's custom formula's name
    index: int = 0  # its place in the program


@dataclass(frozen=True)
class Stats:
    time_above: float
    longest_streak: float


@dataclass(frozen=True)
class ScoredTicks:
    values: list[float]  # per tick: the value scored
    targets: list[float]  # per tick: the target in force when it was recorded
    segments: list[Segment]

    @cached_property
    def recorded_steps(self) -> list[tuple[int, float]]:
        return target_steps(self.targets) or []


_FORMULA_KEYS = ("custom_formula", "program_formula")  # prefixes of series computed, not stored per tick


def _has_record(rows: list[dict]) -> bool:
    """Every tick stored what it was scored on (#83); a partial record is not trusted."""
    return bool(rows) and all(r.get("score_target") is not None for r in rows)


def _values(key: str, rows: list[dict], formula_series: dict[str, list[float]]) -> list[float] | None:
    """A metric's value per tick: its stored column, or a formula's replayed series (None when it wasn't replayed)."""
    if key.startswith(_FORMULA_KEYS):
        return list(formula_series[key]) if key in formula_series else None
    return [r.get(key) or 0.0 for r in rows]


def scored_ticks(session: dict, rows: list[dict], formula_series: dict[str, list[float]],
                 replay_formulas: FormulaReplay | None = None) -> ScoredTicks | None:
    """What each tick was scored on and against: its stored record, or for an older session its saved metric
    (meditation before it was saved, #51) at its threshold, or its program's segments, their formulas run through
    `replay_formulas`. None when it can't be replayed: a formula the replay couldn't rebuild (its stored column is
    stale), a program that can't be read or has no tick."""
    if session.get("session_program"):
        return _program_ticks(session["session_program"], rows, formula_series, replay_formulas)
    target = float(session.get("threshold_used") or 0)
    if _has_record(rows):
        key = rows[0]["score_key"]
        values, targets = [r["score_value"] for r in rows], [r["score_target"] for r in rows]
    else:
        key = session.get("score_metric_key") or "meditation_score"
        values = _values(key, rows, formula_series)
        if values is None:
            return None
        targets = [target] * len(values)
    return ScoredTicks(values, targets, [Segment(key, target, 0, len(values))])


def _program_ticks(program_json: str, rows: list[dict], formula_series: dict[str, list[float]],
                   replay_formulas: FormulaReplay | None) -> ScoredTicks | None:
    """A program's ticks on its segments: where the record shows each switch, else by minutes as the graph's steps."""
    try:
        program = SessionProgram(json.loads(program_json))
    except (ValueError, TypeError):
        return None
    n = len(rows)
    _, _, keys = program_plan(program)
    scored_on = [(key, segment_target(seg)) for key, seg in zip(keys, program.segments)]
    by_minutes = [tick for tick, _ in program.threshold_steps(1 / TICK_SECONDS)]
    record = _has_record(rows)
    starts = _recorded_starts(scored_on, by_minutes, rows) if record else by_minutes
    ends = [min(end, n) for end in [*starts[1:], n]]
    segments = [Segment(key, target, start, end, _formula_name(seg), i)
                for i, ((key, target), seg, start, end) in enumerate(zip(scored_on, program.segments, starts, ends))
                if start < end]  # a segment the session never reached, or that the switch after it skipped
    if not segments:
        return None
    segments[-1] = replace(segments[-1], end=n)
    if record:
        return ScoredTicks([r["score_value"] for r in rows], [r["score_target"] for r in rows], segments)
    evaluators = program_evaluators(program)
    if evaluators and replay_formulas is not None:
        formula_series = {**formula_series, **replay_formulas(evaluators)}
    values: list[float] = []
    targets: list[float] = []
    for segment in segments:
        series = _values(segment.key, rows, formula_series)
        if series is None:
            return None
        values += series[segment.start:segment.end]
        targets += [segment.target] * (segment.end - segment.start)
    return ScoredTicks(values, targets, segments)


def _recorded_starts(scored_on: list[tuple[str, int]], by_minutes: list[int], rows: list[dict]) -> list[int]:
    """Where the record shows each switch: the live one is on elapsed time, so dropped ticks move it off minutes x 2."""
    starts, found = [0], 0  # found: the last switch read from the record
    for k in range(1, len(scored_on)):
        if scored_on[k] == scored_on[k - 1]:  # the record can't tell them apart: its minutes after the one before
            starts.append(starts[-1] + by_minutes[k] - by_minutes[k - 1])
            continue
        key, target = scored_on[k]
        found = next((t for t in range(found, len(rows))
                      if rows[t]["score_key"] == key and rows[t]["score_target"] == target), len(rows))
        starts = [*(min(s, found) for s in starts), found]
    return starts


def _formula_name(segment: dict) -> str:
    formula = segment.get("formula")
    return str(formula.get("name") or "") if isinstance(formula, dict) else ""


def rescore(ticks: ScoredTicks, overrides: list[float | None], per_segment: bool = True) -> tuple[Stats, list[Stats]]:
    """The whole session's stats and, unless not wanted, each segment's: a segment's ticks against its override, or
    with None against their own recorded targets. The whole session's streak carries across a segment boundary, as
    the live scoring does; a segment's stays within it."""
    total = GoalAccrual()
    stats = []
    for segment, override in zip(ticks.segments, overrides):
        values = ticks.values[segment.start:segment.end]
        targets = ticks.targets[segment.start:segment.end] if override is None else [override] * len(values)
        within = GoalAccrual() if per_segment else None
        for value, target in zip(values, targets):
            total.add(value, target)
            if within is not None:
                within.add(value, target)
        if within is not None:
            stats.append(Stats(within.time_above, within.longest_streak))
    return Stats(total.time_above, total.longest_streak), stats


def line_steps(ticks: ScoredTicks, overrides: list[float | None]) -> list[tuple[int, float]]:
    """The graph's threshold line: each segment's override, or its recorded targets."""
    steps: list[tuple[int, float]] = []
    recorded = ticks.recorded_steps
    for segment, override in zip(ticks.segments, overrides):
        if override is not None:
            extend_steps(steps, segment.start, override)
            continue
        for k, (tick, target) in enumerate(recorded):
            next_tick = recorded[k + 1][0] if k + 1 < len(recorded) else len(ticks.targets)
            if next_tick > segment.start and tick < segment.end:
                extend_steps(steps, max(tick, segment.start), target)
    return steps
