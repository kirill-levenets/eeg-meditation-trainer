"""Main-thread render timing: per-graph redraw cost and the longest frame gap, one log line per window."""

import time

from kivy.clock import Clock

from app.logger import logger

# Same cadence as the reader's "BT throughput" line, so the two can be lined up.
WINDOW_S = 30.0
# A longer gap is a suspended main loop (screen lock, app in background), not a stall.
SUSPEND_GAP_S = 5.0


class RenderStats:
    def __init__(self) -> None:
        self._redraws: dict[str, list[float]] = {}  # graph_id -> [count, total_s, max_s]
        self._max_gap_s = 0.0
        self._window_start = time.monotonic()

    def record_redraw(self, graph_id: str, seconds: float) -> None:
        s = self._redraws.setdefault(graph_id or "unnamed", [0, 0.0, 0.0])
        s[0] += 1
        s[1] += seconds
        s[2] = max(s[2], seconds)

    def on_frame(self, dt: float, now: float | None = None) -> None:
        if dt < SUSPEND_GAP_S:
            self._max_gap_s = max(self._max_gap_s, dt)
        now = time.monotonic() if now is None else now
        if now - self._window_start < WINDOW_S:
            return
        if self._redraws:
            logger.info(self.summary())
        self._redraws = {}
        self._max_gap_s = 0.0
        self._window_start = now

    def summary(self) -> str:
        parts = [f"frame gap max {self._max_gap_s * 1000:.0f} ms"]
        for gid, (n, total, peak) in sorted(self._redraws.items(), key=lambda kv: -kv[1][1]):
            parts.append(f"{gid} {int(n)}x avg {total / n * 1000:.1f} max {peak * 1000:.1f} ms")
        return "Render: " + " | ".join(parts)


STATS = RenderStats()


def start() -> None:
    """Sample every frame on the main loop (Kivy passes the time since the previous frame)."""
    Clock.schedule_interval(STATS.on_frame, 0)
