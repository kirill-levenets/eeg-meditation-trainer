"""What the Session screen's graphs would have been given this session, kept by the tick thread whatever the screen
does."""
from collections import deque

from app.config import APP
from app.eeg.band_spec import GROUP_KEYS, group_powers
from app.session.scoring import target_steps
from app.ui.live_session import METRICS_COLORS


class LiveMirror:
    """A locked screen skips the per-tick graph updates (N minutes at 2 Hz queued ~120·N Clock callbacks, each a full
    redraw, which froze the screen on resume); the tick thread records here instead, with no Kivy, and the graphs
    reload from it in one batch on resume and at the session's end. Bounded by the graphs' capacity."""

    def __init__(self) -> None:
        self.metrics: deque[dict] = deque(maxlen=APP.GRAPH_POINTS_MAX)
        self.bands: deque[dict] = deque(maxlen=APP.GRAPH_POINTS_MAX)
        self.waveform: deque[float] = deque(maxlen=512 * 60)
        self.last_metrics: dict = {}
        self.last_state: str = "Neutral"

    def record(self, metrics: dict, target: float, raw_sample: dict) -> None:
        """Tick thread: one tick's metrics with its target, its band groups and its raw waveform."""
        self.metrics.append({**metrics, "score_target": target})
        bands = group_powers(lambda k: raw_sample.get(k, 0.0))
        self.bands.append(bands)
        waveform = raw_sample.get("raw_eeg_waveform")
        if waveform:
            self.waveform.extend(waveform)
        else:
            self.waveform.append(sum(bands.values()))
        self.last_metrics = metrics
        self.last_state = metrics.get("state", "Neutral")

    def clear(self) -> None:
        self.metrics.clear()
        self.bands.clear()
        self.waveform.clear()
        self.last_metrics = {}
        self.last_state = "Neutral"

    def reload_into(self, live_screen) -> None:
        """Main thread: batch-reload the 3 live graphs (one load_static_data per graph), the threshold steps with them."""
        metrics = list(self.metrics)
        bands = list(self.bands)
        waveform = list(self.waveform)
        if metrics:
            live_screen.graph.load_static_data({key: [d.get(key, 0.0) for d in metrics] for key in METRICS_COLORS},
                                               new_session=False)
            live_screen.graph.set_threshold_steps(target_steps(d.get("score_target") for d in metrics))
        if bands:
            live_screen.band_graph.load_static_data({key: [d.get(key, 0.0) for d in bands] for key in GROUP_KEYS},
                                                    new_session=False)
        if waveform:
            live_screen.raw_graph.load_static_data({"eeg": waveform}, new_session=False)
