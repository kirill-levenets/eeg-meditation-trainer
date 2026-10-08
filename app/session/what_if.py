"""What-if scoring of a stored session (#50): its ticks re-scored against other targets with the live accrual, so the
recorded targets give back the recorded time above threshold and longest streak. View only: nothing is written."""

from dataclasses import dataclass
from functools import cached_property

from app.session.scoring import GoalAccrual


@dataclass(frozen=True)
class Segment:
    key: str  # the metric scored
    target: float  # the target it was scored against
    start: int  # its first tick
    end: int  # one past its last


@dataclass(frozen=True)
class Stats:
    time_above: float
    longest_streak: float


@dataclass(frozen=True)
class ScoredTicks:
    """Per tick: the value scored, the metric and the target in force when it was recorded."""

    values: list[float]
    keys: list[str]
    targets: list[float]

    @cached_property
    def segments(self) -> list[Segment]:
        return segments_of(self.keys, self.targets)


def segments_of(keys: list[str], targets: list[float]) -> list[Segment]:
    """Runs of ticks scored on the same metric against the same target: a program's segments, a moved threshold."""
    segments: list[Segment] = []
    start = 0
    for i in range(1, len(keys) + 1):
        if i == len(keys) or (keys[i], targets[i]) != (keys[start], targets[start]):
            segments.append(Segment(keys[start], targets[start], start, i))
            start = i
    return segments


_FORMULA_KEYS = ("custom_formula", "program_formula")  # prefixes of series computed, not stored per tick


def scored_ticks(session: dict, rows: list[dict], formula_series: dict[str, list[float]]) -> ScoredTicks | None:
    """What each tick of a simple session was scored on: its stored record, or for an older one its saved metric
    (meditation before it was saved, #51) at its threshold. None for a program, and for a formula the replay couldn't
    rebuild (its stored column is stale)."""
    if session.get("session_program"):
        return None
    if rows and all(r.get("score_target") is not None for r in rows):
        return ScoredTicks([r["score_value"] for r in rows], [r["score_key"] for r in rows],
                           [r["score_target"] for r in rows])
    key = session.get("score_metric_key") or "meditation_score"
    if key.startswith(_FORMULA_KEYS):
        if key not in formula_series:
            return None
        values = formula_series[key]
    else:
        values = [r.get(key) or 0.0 for r in rows]
    target = float(session.get("threshold_used") or 0)
    return ScoredTicks(list(values), [key] * len(values), [target] * len(values))


def rescore(ticks: ScoredTicks, targets: list[float], per_segment: bool = True) -> tuple[Stats, list[Stats]]:
    """The whole session's stats and, unless not wanted, each segment's, each segment against its entry in `targets`:
    the whole session's streak carries across a segment boundary, as the live scoring does, a segment's stays within."""
    total = GoalAccrual()
    segments = []
    for segment, target in zip(ticks.segments, targets):
        within = GoalAccrual() if per_segment else None
        for value in ticks.values[segment.start:segment.end]:
            total.add(value, target)
            if within is not None:
                within.add(value, target)
        if within is not None:
            segments.append(Stats(within.time_above, within.longest_streak))
    return Stats(total.time_above, total.longest_streak), segments
