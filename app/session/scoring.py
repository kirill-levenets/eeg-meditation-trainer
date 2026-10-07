"""Session scoring: time at/above the goal and the longest run, and which metric a stored session was scored on (#51)."""

from collections.abc import Iterable

TICK_SECONDS = 0.5  # the 2 Hz session tick


class GoalAccrual:
    """Time at/above a goal and the longest unbroken run, one tick at a time (the live session and recomputes share it)."""

    def __init__(self) -> None:
        self.time_above = 0.0
        self.longest_streak = 0.0
        self.current_streak = 0.0

    def add(self, value: float, goal: float) -> None:
        if value >= goal:
            self.time_above += TICK_SECONDS
            self.current_streak += TICK_SECONDS
            self.longest_streak = max(self.longest_streak, self.current_streak)
        else:
            self.current_streak = 0.0


def goal_stats(values: Iterable[float], goal: float) -> tuple[float, float]:
    """(time above, longest streak) in seconds for a series of per-tick values, e.g. a session's stored ticks."""
    acc = GoalAccrual()
    for value in values:
        acc.add(value, goal)
    return acc.time_above, acc.longest_streak


def extend_steps(steps: list[tuple[int, float]], tick: int, target: float) -> None:
    """Add tick `tick`'s target to `steps`: a new (tick, target) step only where the target changes."""
    if not steps or steps[-1][1] != target:
        steps.append((tick, target))


def target_steps(targets: Iterable[float | None]) -> list[tuple[int, float]] | None:
    """[(first tick, target), ...] of a per-tick target series; None unless every tick has one (nothing is deduced)."""
    steps: list[tuple[int, float]] = []
    for tick, target in enumerate(targets):
        if target is None:
            return None
        extend_steps(steps, tick, target)
    return steps or None


def recorded_score(session: dict) -> tuple[str, str, float | None] | None:
    """(metric key, display name, average) a stored session was scored on, or None for a row from before #51, which
    saved none: nothing is deduced for it."""
    key = session.get("score_metric_key") or ""
    if not key:
        return None
    return key, session.get("score_metric_name") or key, session.get("avg_score")
