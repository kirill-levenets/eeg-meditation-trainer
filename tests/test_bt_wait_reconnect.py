"""The BT connection wait gives each connection its own no-data window: a link that drops and reconnects gets the full
window on the new socket, and only packets that arrive on it count."""

from unittest.mock import MagicMock

import pytest

import app.ui.app_manager as am
from app.session.manager import SessionManager, SessionState
from app.ui.app_manager import EEGMeditationApp

T0 = 1000.0


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> float:
        return self.now


class _Stream:
    """The headset link as the wait reads it."""

    def __init__(self, clock: _Clock) -> None:
        self._clock = clock
        self.is_connected = False
        self._running = True
        self._device_name = "MindWave Mobile"
        self._last_connect_error = ""
        self.last_packet = 0.0
        self.bands = 0.0
        self.stop = MagicMock()

    @property
    def seconds_since_last_packet(self) -> float:
        return 0.0 if not self.last_packet else self._clock.now - self.last_packet

    def read_sample(self) -> dict:
        return {"signal_quality": 200, "delta": self.bands}


@pytest.fixture
def wait(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(am.time, "time", clock)
    monkeypatch.setattr(am.time, "monotonic", clock)
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    stream = _Stream(clock)
    app._real_stream = app._eeg_stream = stream
    app._tick_thread = None
    app._stop_tick_thread = MagicMock()
    app._release_wake_lock = MagicMock()
    app._stop_session_keep_alive_service = MagicMock()
    app._session_manager = SessionManager()
    app._timer_state = MagicMock()
    app._live_screen = MagicMock()
    app._on_main_for_wait = MagicMock()
    app._report_bt_connect_failure = MagicMock()
    app._start_attempt = 1
    stream.start = MagicMock(return_value=True)
    app._bt_connect_start = clock.now  # set by the session start that precedes the wait
    assert app._begin_bt_wait(70)  # the wait as Start enters it, at T0

    def tick(at: float, *, connected: bool, bands: float = 0.0, packet: bool = False) -> None:
        clock.now = T0 + at
        stream.is_connected = connected
        stream.bands = bands
        if packet:
            stream.last_packet = clock.now - 0.1  # just before the tick reads it (0.0 means none yet)
        app._handle_bt_wait()

    return app, stream, tick


def _gave_up(stream: _Stream) -> bool:
    return stream.stop.called


def test_a_link_that_drops_and_reconnects_gets_the_full_window_on_the_new_socket(wait):
    # The phone log of 2026-10-06: socket #1 connected 6 s after Start and the headset closed it 5.6 s later without
    # a byte; the reader's reconnect connected socket #2 at 18 s, and the wait gave up 0.4 s later, on socket #1's
    # elapsed time. A retry's socket #3 sent data 0.56 s after connecting.
    app, stream, tick = wait
    for at in (6.0, 8.0, 10.0, 11.0):
        tick(at, connected=True)
    tick(11.5, connected=False)  # the headset closed it; the reader reconnects
    tick(15.0, connected=False)
    tick(18.0, connected=True)
    tick(18.5, connected=True)
    assert not _gave_up(stream)
    tick(19.0, connected=True, bands=5.0, packet=True)
    assert app._session_manager.state == SessionState.RUNNING


def test_the_new_socket_still_times_out_when_it_sends_nothing(wait):
    app, stream, tick = wait
    tick(6.0, connected=True)
    tick(11.5, connected=False)
    tick(18.0, connected=True)
    tick(25.9, connected=True)
    assert not _gave_up(stream)
    tick(26.5, connected=True)  # its own 8 s, from 18 s
    assert _gave_up(stream)
    assert app._waiting_for_bt is False


def test_packets_from_before_a_drop_do_not_count_for_the_new_socket(wait):
    # Packets on socket #1 (sensor off, so no session yet), then a drop: a silent socket #2 must still time out.
    # Before, the old packets read as "headset streaming" and the wait never ended.
    _app, stream, tick = wait
    tick(6.0, connected=True, packet=True)
    tick(8.0, connected=True, packet=True)
    tick(10.0, connected=False)
    tick(12.0, connected=True)
    tick(19.9, connected=True)
    assert not _gave_up(stream)
    tick(20.5, connected=True)
    assert _gave_up(stream)


def test_a_link_that_never_drops_keeps_its_window(wait):
    _app, stream, tick = wait
    tick(6.0, connected=True)
    tick(13.9, connected=True)
    assert not _gave_up(stream)
    tick(14.5, connected=True)
    assert _gave_up(stream)


def test_packets_without_contact_keep_the_wait_open(wait):
    # The headset streams but the sensor isn't on the forehead yet: no timeout, the user is placing it.
    app, stream, tick = wait
    for at in (6.0, 10.0, 20.0, 29.0):
        tick(at, connected=True, packet=True)
    assert not _gave_up(stream)
    tick(29.5, connected=True, bands=5.0, packet=True)
    assert app._session_manager.state == SessionState.RUNNING
