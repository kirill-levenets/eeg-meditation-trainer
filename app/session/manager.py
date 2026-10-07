import json
import time
from enum import Enum

from app.logger import logger
from app.session.scoring import GoalAccrual, extend_steps


class SessionState(Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    FINISHED = "FINISHED"


class SessionManager:
    """Manages session lifecycle: Start, Pause, Resume, Stop."""

    def __init__(self) -> None:
        self._state: SessionState = SessionState.IDLE
        self._start_time: float = 0.0
        self._elapsed: float = 0.0
        self._pause_start: float = 0.0
        self._total_paused: float = 0.0
        self._metrics_accumulator: list[dict[str, float]] = []
        self._goal = GoalAccrual()  # time above / longest streak on the scored metric
        self._score_sum: float = 0.0  # the scored metric's per-tick values, for avg_score
        self._score_ticks: int = 0
        self._time_shamatha_90: float = 0.0
        self._threshold_used: int = 50  # at Start: the session row's threshold_used
        self._threshold: float = 50  # in force: the Settings threshold, which can change mid-session
        self._target_steps: list[tuple[int, float]] = []  # (first tick, target) of each target the ticks were scored on
        self._active_metric: str = "meditation_score"
        self._active_target: float | None = None
        self._audio = None

    def set_audio(self, audio) -> None:
        """Attach the audio engine so non-user stops can play the alert."""
        self._audio = audio

    def set_active_goal(self, metric_key: str, target: float | None = None) -> None:
        """Score the session on this metric from now on: against `target` (a program segment), else the threshold."""
        self._active_metric = metric_key
        self._active_target = target

    def set_threshold(self, value: float) -> None:
        """The threshold in force from the next tick: the target, unless a program segment sets its own."""
        self._threshold = value

    @property
    def _time_above_threshold(self) -> float:
        return self._goal.time_above

    @property
    def _longest_streak(self) -> float:
        return self._goal.longest_streak

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def started_at(self) -> float:
        """Wall-clock time the session started (0.0 before start): its date and name, not the first save's."""
        return self._start_time

    @property
    def elapsed_seconds(self) -> float:
        if self._state == SessionState.RUNNING:
            return time.time() - self._start_time - self._total_paused
        if self._state == SessionState.PAUSED:  # frozen at the pause (a checkpoint while paused wrote 0)
            return self._pause_start - self._start_time - self._total_paused
        return self._elapsed

    @property
    def elapsed_formatted(self) -> str:
        secs = int(self.elapsed_seconds)
        minutes = secs // 60
        seconds = secs % 60
        return f"{minutes:02d}:{seconds:02d}"

    @property
    def metrics_count(self) -> int:
        return len(self._metrics_accumulator)

    def start(self, threshold: float | None = None) -> None:
        """Start scored against `threshold`, or without one against the threshold in force (set_threshold)."""
        if self._state in (SessionState.IDLE, SessionState.FINISHED):
            if threshold is not None:
                self._threshold = threshold
            self._state = SessionState.RUNNING
            self._start_time = time.time()
            self._elapsed = 0.0
            self._total_paused = 0.0
            self._metrics_accumulator = []
            self._reset_scoring()
            self._time_shamatha_90 = 0.0
            self._threshold_used = self._threshold
            self._active_metric = "meditation_score"
            self._active_target = None
            logger.info("Session started")

    def pause(self) -> None:
        if self._state == SessionState.RUNNING:
            self._state = SessionState.PAUSED
            self._pause_start = time.time()
            logger.info("Session paused")

    def resume(self) -> None:
        if self._state == SessionState.PAUSED:
            self._total_paused += time.time() - self._pause_start
            self._state = SessionState.RUNNING
            logger.info("Session resumed")

    def stop(self, reason: str = "user") -> dict:
        """Stop the session. reason ∈ {'user', 'stale_data', 'bt_lost', 'error'}."""
        if self._state in (SessionState.RUNNING, SessionState.PAUSED):
            if self._state == SessionState.PAUSED:
                self._total_paused += time.time() - self._pause_start
            self._elapsed = time.time() - self._start_time - self._total_paused
            self._state = SessionState.FINISHED
            # Only failure terminations warble. "user" and "timer" are planned
            # stops (timer plays its own gong), and timer-end persistence runs
            # on the daemon tick thread where SoundLoader playback is unsafe.
            if reason in ("stale_data", "bt_lost", "error") and self._audio is not None:
                try:
                    self._audio.play_alert()
                except Exception:
                    logger.exception("play_alert on session stop failed")
            stats = self.compute_statistics()
            logger.info(f"Session stopped. Duration: {self._elapsed:.0f}s, reason={reason}")
            return stats
        return {}

    def add_metric(self, metric: dict[str, float]) -> dict:
        """Score a tick; what it was scored on (metric, value, target) for its stored row, or {} if not running."""
        if self._state != SessionState.RUNNING:
            return {}
        self._metrics_accumulator.append(metric)
        goal = self._active_target if self._active_target is not None else self._threshold
        value = metric.get(self._active_metric, 0)
        self._goal.add(value, goal)
        extend_steps(self._target_steps, self._score_ticks, goal)
        self._score_sum += value
        self._score_ticks += 1
        if metric.get("shamatha_score", 0) >= 90:
            self._time_shamatha_90 += 0.5
        return {"score_key": self._active_metric, "score_value": value, "score_target": goal}

    def compute_statistics(self) -> dict:
        """Compute end-of-session statistics."""
        if not self._metrics_accumulator:
            return {
                "duration": int(self.elapsed_seconds),
                "threshold_used": self._threshold_used,
                "avg_meditation": 0.0,
                "avg_shamatha": 0.0,
                "max_meditation": 0.0,
                "time_above_threshold": int(self._time_above_threshold),
                "time_shamatha_90": 0,
                "longest_streak": 0,
                "distraction_rate": 0.0,
                "sinking_rate": 0.0,
                "score_metric_key": None,  # nothing scored yet
                "avg_score": None,
                "score_targets": "",
            }

        n = len(self._metrics_accumulator)
        avg_med = sum(m.get("meditation_score", 0) for m in self._metrics_accumulator) / n
        avg_sha = sum(m.get("shamatha_score", 0) for m in self._metrics_accumulator) / n
        max_med = max(m.get("meditation_score", 0) for m in self._metrics_accumulator)
        distraction_count = sum(
            1 for m in self._metrics_accumulator if m.get("state") == "Gross Distraction"
        )
        sinking_count = sum(
            1 for m in self._metrics_accumulator if m.get("state") == "Sinking"
        )

        return {
            "duration": int(self.elapsed_seconds),
            "threshold_used": self._threshold_used,
            "avg_meditation": round(avg_med, 2),
            "avg_shamatha": round(avg_sha, 2),
            "max_meditation": round(max_med, 2),
            "time_above_threshold": int(self._time_above_threshold),
            "time_shamatha_90": int(self._time_shamatha_90),
            "longest_streak": int(self._longest_streak),
            "distraction_rate": round(distraction_count / n * 100, 1),
            "sinking_rate": round(sinking_count / n * 100, 1),
            "score_metric_key": self._active_metric if self._score_ticks else None,
            "avg_score": round(self._score_sum / self._score_ticks, 2) if self._score_ticks else None,
            "score_targets": json.dumps([target for _tick, target in self._target_steps]) if self._target_steps else "",
        }

    def _reset_scoring(self) -> None:
        self._goal = GoalAccrual()
        self._score_sum = 0.0
        self._score_ticks = 0
        self._target_steps = []

    def reset(self) -> None:
        self._state = SessionState.IDLE
        self._start_time = 0.0
        self._metrics_accumulator = []
        self._elapsed = 0.0
        self._reset_scoring()
        self._time_shamatha_90 = 0.0
        self._total_paused = 0.0
        self._active_metric = "meditation_score"
        self._active_target = None


if __name__ == "__main__":
    sm = SessionManager()
    sm.start(threshold=50)
    print(f"State: {sm.state.value}, Elapsed: {sm.elapsed_formatted}")

    sm.add_metric({"meditation_score": 60, "shamatha_score": 40, "state": "Stable Focus"})
    sm.add_metric({"meditation_score": 70, "shamatha_score": 55, "state": "Stable Focus"})
    sm.add_metric({"meditation_score": 30, "shamatha_score": 20, "state": "Gross Distraction"})
    sm.add_metric({"meditation_score": 80, "shamatha_score": 60, "state": "Stable Focus"})
    sm.add_metric({"meditation_score": 65, "shamatha_score": 50, "state": "Stable Focus"})
    sm.add_metric({"meditation_score": 55, "shamatha_score": 45, "state": "Stable Focus"})

    stats = sm.stop()
    print(f"State: {sm.state.value}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    assert stats["longest_streak"] == 1, f"Expected longest_streak=1, got {stats['longest_streak']}"
    assert stats["time_above_threshold"] == 2, f"Expected time_above_threshold=2, got {stats['time_above_threshold']}"
    print("All assertions passed.")
