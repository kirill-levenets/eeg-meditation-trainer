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


def recorded_score(session: dict) -> tuple[str, str, float | None]:
    """(metric key, display name, average) a stored session was scored on. Rows from before #51 have no key: a simple
    one was scored on meditation, a program per segment."""
    key = session.get("score_metric_key") or ""
    if key:
        return key, session.get("score_metric_name") or key, session.get("avg_score")
    if session.get("session_program"):
        return "program", "Program", None
    return "meditation_score", "Meditation", session.get("avg_meditation")
