"""What the Session screen's graphs would have been given this session, kept by the session's runner whatever the screen
does."""
import threading
from collections import deque

from app.config import APP
from app.eeg.band_spec import GROUP_KEYS, group_powers
from app.session.recorder import RecordedTick
from app.session.scoring import scored_steps, target_steps
from app.ui.live_session import METRICS_COLORS, RAW_WAVEFORM_MAX


class LiveMirror:
    """A locked screen skips the per-tick graph updates (N minutes at 2 Hz queued ~120·N Clock callbacks, each a full
    redraw, which froze the screen on resume); the runner records here instead, with no Kivy, and the graphs
    reload from it in one batch on resume and at the session's end. Bounded by the graphs' capacity."""

    def __init__(self) -> None:
        self.metrics: deque[dict] = deque(maxlen=APP.GRAPH_POINTS_MAX)
        self.bands: deque[dict] = deque(maxlen=APP.GRAPH_POINTS_MAX)
        self.waveform: deque[float] = deque(maxlen=RAW_WAVEFORM_MAX)  # the raw graph's: its marker indices agree
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

    def reload_into(self, live_screen) -> None:
        """Main thread: batch-reload the 3 live graphs (one load_static_data per graph) with their markers, the
        threshold steps with them."""
        with self._lock:
            metrics, bands, waveform = list(self.metrics), list(self.bands), list(self.waveform)
            marks, ticks, samples = list(self.marks), self._ticks, self._samples
        tick_marks, sample_marks = [t for t, _s in marks], [s for _t, s in marks]
        if metrics:
            live_screen.graph.load_static_data({key: [d.get(key, 0.0) for d in metrics] for key in METRICS_COLORS},
                                               new_session=False, markers=_kept(tick_marks, ticks - len(metrics)))
            live_screen.graph.set_threshold_steps(target_steps(d.get("score_target") for d in metrics))
            live_screen.graph.set_gradient_steps(scored_steps(d.get("score_key") for d in metrics))
        if bands:
            live_screen.band_graph.load_static_data({key: [d.get(key, 0.0) for d in bands] for key in GROUP_KEYS},
                                                    new_session=False, markers=_kept(tick_marks, ticks - len(bands)))
        if waveform:
            live_screen.raw_graph.load_static_data({"eeg": waveform}, new_session=False,
                                                   markers=_kept(sample_marks, samples - len(waveform)))


def _kept(positions: list[int], dropped: int) -> list[int]:
    """Marker positions counted from the session's start, as indices into a buffer that dropped its first `dropped`."""
    return [p - dropped for p in positions if p >= dropped]
