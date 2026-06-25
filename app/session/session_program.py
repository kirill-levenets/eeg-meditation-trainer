"""Headless session-program model: ordered timed segments with per-segment
target + driving formula. Pure logic (no Kivy), mirrors timer_state.py."""


def _minutes(seg: dict) -> int:
    return max(1, int(seg.get("minutes", 0)))


# Segment dict: {minutes:int, target:int, formula:str|{"name","formula"},
# end_sound:str|None, feedback_sound:str|None}
class SessionProgram:
    """An ordered list of timed segments driving per-segment target + formula."""

    def __init__(self, segments) -> None:
        self._segments = [
            s for s in (segments or [])
            if isinstance(s, dict) and int(s.get("minutes", 0)) > 0
        ]

    def __bool__(self) -> bool:
        return bool(self._segments)

    @property
    def segments(self) -> list[dict]:
        return self._segments

    @property
    def total_seconds(self) -> float:
        return sum(_minutes(s) * 60 for s in self._segments)

    def segment_at(self, elapsed_seconds: float) -> tuple[int, dict | None]:
        """(index, segment) active at elapsed; clamps to the last segment past total."""
        if not self._segments:
            return (-1, None)
        t = 0.0
        for i, s in enumerate(self._segments):
            t += _minutes(s) * 60
            if elapsed_seconds < t:
                return (i, s)
        return (len(self._segments) - 1, self._segments[-1])

    @property
    def boundaries(self) -> list[float]:
        out, t = [], 0.0
        for s in self._segments:
            t += _minutes(s) * 60
            out.append(t)
        return out

    def threshold_steps(self, sample_rate: float) -> list[tuple[int, float]]:
        """[(start_tick, target), ...] in tick-index space, for the graph."""
        steps, tick = [], 0
        for s in self._segments:
            steps.append((tick, float(s.get("target", 0))))
            tick += int(_minutes(s) * 60 * sample_rate)
        return steps
