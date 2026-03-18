import time
from enum import Enum
from typing import Dict, List

from app.logger import logger


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
        self._metrics_accumulator: List[Dict[str, float]] = []
        self._time_above_threshold: float = 0.0
        self._current_streak: float = 0.0
        self._longest_streak: float = 0.0
        self._threshold_used: int = 50

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def elapsed_seconds(self) -> float:
        if self._state == SessionState.RUNNING:
            return time.time() - self._start_time - self._total_paused
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

    def start(self, threshold: int = 50) -> None:
        if self._state in (SessionState.IDLE, SessionState.FINISHED):
            self._state = SessionState.RUNNING
            self._start_time = time.time()
            self._elapsed = 0.0
            self._total_paused = 0.0
            self._metrics_accumulator = []
            self._time_above_threshold = 0.0
            self._current_streak = 0.0
            self._longest_streak = 0.0
            self._threshold_used = threshold
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

    def stop(self) -> Dict:
        if self._state in (SessionState.RUNNING, SessionState.PAUSED):
            if self._state == SessionState.PAUSED:
                self._total_paused += time.time() - self._pause_start
            self._elapsed = time.time() - self._start_time - self._total_paused
            self._state = SessionState.FINISHED
            stats = self.compute_statistics()
            logger.info(f"Session stopped. Duration: {self._elapsed:.0f}s")
            return stats
        return {}

    def add_metric(self, metric: Dict[str, float]) -> None:
        """Accumulate a processed metric tick for end-of-session stats."""
        if self._state == SessionState.RUNNING:
            self._metrics_accumulator.append(metric)
            if metric.get("meditation_score", 0) >= self._threshold_used:
                self._time_above_threshold += 0.5  # 2 Hz tick = 0.5s
                self._current_streak += 0.5
                if self._current_streak > self._longest_streak:
                    self._longest_streak = self._current_streak
            else:
                self._current_streak = 0.0

    def compute_statistics(self) -> Dict:
        """Compute end-of-session statistics."""
        if not self._metrics_accumulator:
            return {
                "duration": int(self._elapsed),
                "threshold_used": self._threshold_used,
                "avg_meditation": 0.0,
                "avg_shamatha": 0.0,
                "max_meditation": 0.0,
                "time_above_threshold": int(self._time_above_threshold),
                "longest_streak": 0,
                "distraction_rate": 0.0,
                "sinking_rate": 0.0,
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
            "duration": int(self._elapsed),
            "threshold_used": self._threshold_used,
            "avg_meditation": round(avg_med, 2),
            "avg_shamatha": round(avg_sha, 2),
            "max_meditation": round(max_med, 2),
            "time_above_threshold": int(self._time_above_threshold),
            "longest_streak": int(self._longest_streak),
            "distraction_rate": round(distraction_count / n * 100, 1),
            "sinking_rate": round(sinking_count / n * 100, 1),
        }

    def reset(self) -> None:
        self._state = SessionState.IDLE
        self._metrics_accumulator = []
        self._elapsed = 0.0
        self._time_above_threshold = 0.0
        self._current_streak = 0.0
        self._longest_streak = 0.0
        self._total_paused = 0.0


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
