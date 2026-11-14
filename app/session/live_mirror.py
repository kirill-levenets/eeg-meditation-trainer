"""What the Session screen's graphs would have been given this session, kept by the session's runner whatever the screen
does."""
import threading
from collections import deque
from typing import NamedTuple

from app.config import APP
from app.eeg.band_spec import group_powers
from app.session.recorder import RecordedTick


class MirrorView(NamedTuple):
    """A snapshot of the mirror, whole ticks: its buffers, with the markers as indices into them (the metrics and bands
    keep the same ticks)."""

    metrics: list[dict]
    bands: list[dict]
    waveform: list[float]
    tick_marks: list[int]
    sample_marks: list[int]


class LiveMirror:
    """A locked screen skips the per-tick graph updates (N minutes at 2 Hz queued ~120·N Clock callbacks, each a full
    redraw, which froze the screen on resume); the runner records here instead, with no Kivy, and the graphs
    reload from its snapshot in one batch on resume and at the session's end (`LiveSessionScreen.load_mirror`).
    Bounded by the graphs' capacity."""

    def __init__(self) -> None:
        self.metrics: deque[dict] = deque(maxlen=APP.GRAPH_POINTS_MAX)
        self.bands: deque[dict] = deque(maxlen=APP.GRAPH_POINTS_MAX)
        self.waveform: deque[float] = deque(maxlen=APP.RAW_WAVEFORM_MAX)  # the raw graph's: its marker indices agree
        self.last_metrics: dict = {}
        self.last_state: str = "Neutral"
        self.marks: list[tuple[int, int]] = []  # (tick, raw sample) counts since the start: buffers drop their oldest
        self._ticks = 0
        self._samples = 0
        self._lock = threading.Lock()  # a reload's snapshot sees whole ticks: its counts match its buffers

    def record(self, tick: RecordedTick) -> None:
        """Tick thread: one tick's metrics with what it was scored on (score_key, score_target), its bands and waveform,
        and its marker."""
        score, raw_sample = tick.score, tick.raw_sample
        bands = group_powers(lambda k: raw_sample.get(k, 0.0))
        waveform = raw_sample.get("raw_eeg_waveform")
        with self._lock:
            self.metrics.append({**tick.metrics, "score_target": score["score_target"],
                                 "score_key": score["score_key"]})
            self.bands.append(bands)
            if waveform:
                self.waveform.extend(waveform)
            else:
                self.waveform.append(sum(bands.values()))
            self._ticks += 1
            self._samples += len(waveform) if waveform else 1
            if tick.marked:  # where the live graphs put it: on this tick, and on its last raw sample
                self.marks.append((self._ticks - 1, self._samples - 1))
        self.last_metrics = tick.metrics
        self.last_state = tick.metrics.get("state", "Neutral")

    def clear(self) -> None:
        with self._lock:
            self.metrics.clear()
            self.bands.clear()
            self.waveform.clear()
            self.marks = []
            self._ticks = self._samples = 0
        self.last_metrics = {}
        self.last_state = "Neutral"

    def snapshot(self) -> MirrorView:
        """What the live graphs reload from (main thread: on resume and at the session's end)."""
        with self._lock:
            metrics, bands, waveform = list(self.metrics), list(self.bands), list(self.waveform)
            marks, ticks, samples = list(self.marks), self._ticks, self._samples
        tick_marks, sample_marks = [t for t, _s in marks], [s for _t, s in marks]
        return MirrorView(metrics, bands, waveform, _kept(tick_marks, ticks - len(metrics)),
                          _kept(sample_marks, samples - len(waveform)))


def _kept(positions: list[int], dropped: int) -> list[int]:
    """Marker positions counted from the session's start, as indices into a buffer that dropped its first `dropped`."""
    return [p - dropped for p in positions if p >= dropped]
