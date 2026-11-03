"""The live graphs' mirror: the markers a reload puts back where the live graphs put them, its raw buffer as big as the
raw graph's, and its buffers read and changed only under its lock."""
import threading
from collections import deque
from unittest.mock import MagicMock

from app.config import APP
from app.session.recorder import RecordedTick
from app.ui.live_mirror import LiveMirror
from app.ui.live_session import LiveSessionScreen
from tests._shown_session import make_shown
from tests.test_resume_mirror import _drive_tick, _make_tick_app, _metrics, _raw_sample


def _marked_mirror(ticks: int, marked: set, waveform: int = 3) -> LiveMirror:
    mirror = LiveMirror()
    for i in range(ticks):
        raw = _raw_sample(seed=float(i), with_waveform=False)
        if waveform:
            raw["raw_eeg_waveform"] = [float(i)] * waveform
        mirror.record(RecordedTick(_metrics(seed=float(i)), raw, {"score_target": 50, "score_key": "shamatha_score"},
                                   i in marked))
    return mirror


def _markers(screen) -> list:
    return [list(g._markers) for g in (screen.graph, screen.band_graph, screen.raw_graph)]


def test_a_reload_keeps_the_markers_where_the_live_graphs_put_them():
    screen = LiveSessionScreen()
    _marked_mirror(3, {1}).reload_into(screen)
    assert _markers(screen) == [[1], [1], [5]]  # its tick, and its tick's last raw sample (3 per tick)


def test_a_full_buffer_shifts_the_markers_and_drops_the_ones_it_dropped(monkeypatch):
    monkeypatch.setattr(APP, "GRAPH_POINTS_MAX", 3)  # the metrics and bands keep the last 3 ticks
    screen = LiveSessionScreen()
    _marked_mirror(5, {0, 3}, waveform=0).reload_into(screen)
    assert _markers(screen) == [[1], [1], [0, 3]]  # the raw buffer still holds every sample


def test_a_cleared_mirror_forgets_its_markers():
    mirror = _marked_mirror(3, {1})
    mirror.clear()
    mirror.record(RecordedTick(_metrics(), _raw_sample(), {"score_target": 50, "score_key": "shamatha_score"}, False))
    screen = LiveSessionScreen()
    mirror.reload_into(screen)
    assert _markers(screen) == [[], [], []]


def test_a_marked_tick_is_mirrored_with_its_marker():
    app = _make_tick_app()
    app._run.pending_marker = True
    _drive_tick(app, _raw_sample(), _metrics())
    _drive_tick(app, _raw_sample(), _metrics())
    assert app._shown.mirror.marks == [(0, 2)]  # the first tick, its third raw sample


def test_the_live_graphs_and_a_reload_put_a_marker_in_the_same_places():
    app = _make_tick_app()
    app._live_screen = LiveSessionScreen()
    app._shown = make_shown(app)  # over the real screen, as build() wires it
    app._live_screen.update_stats = MagicMock()  # the stub session manager has no score to show
    app._recorder.record = lambda metrics, row: {"score_target": 50, "score_key": "shamatha_score"}
    app._on_main = lambda fn: fn()  # the tick's UI update runs, as the main thread would run it
    for i in range(3):
        app._run.pending_marker = i == 1
        _drive_tick(app, _raw_sample(seed=float(i)), _metrics(seed=float(i)))
    reloaded = LiveSessionScreen()
    app._shown.mirror.reload_into(reloaded)
    assert _markers(app._live_screen) == _markers(reloaded) == [[1], [1], [5]]


def test_the_mirror_keeps_as_many_raw_samples_as_the_raw_graph():
    # A reload's raw marker indices count back from the mirror's buffer: it must hold what the graph holds.
    assert LiveMirror().waveform.maxlen == LiveSessionScreen().raw_graph._data["eeg"].maxlen


class _NotedLock:
    """The mirror's lock, noting whether it is held."""

    def __init__(self) -> None:
        self._lock, self.held = threading.Lock(), False

    def __enter__(self) -> None:
        self._lock.acquire()
        self.held = True

    def __exit__(self, *exc) -> None:
        self.held = False
        self._lock.release()


def _guarded(lock: _NotedLock, base: type) -> type:
    """`base` that fails a read or change made while the mirror's lock is not held."""
    class Guarded(base):
        def __iter__(self):
            assert lock.held
            return super().__iter__()

        def append(self, item):
            assert lock.held
            super().append(item)

        def extend(self, items):
            assert lock.held
            super().extend(items)

        def clear(self):
            assert lock.held
            super().clear()
    return Guarded


def test_the_mirror_is_read_and_changed_only_under_its_lock():
    # So a reload's snapshot sees whole ticks: the counts it reads match the buffers it copies.
    mirror = LiveMirror()
    lock = mirror._lock = _NotedLock()
    for name in ("metrics", "bands", "waveform"):
        setattr(mirror, name, _guarded(lock, deque)(maxlen=getattr(mirror, name).maxlen))
    mirror.marks = _guarded(lock, list)()
    mirror.record(RecordedTick({"shamatha_score": 1.0}, {"raw_eeg_waveform": [1.0, 2.0]},
                               {"score_target": 50, "score_key": "shamatha_score"}, True))
    mirror.reload_into(MagicMock())
    mirror.clear()
