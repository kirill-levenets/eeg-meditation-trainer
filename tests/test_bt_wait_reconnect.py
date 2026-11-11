"""The BT connection wait gives each connection its own no-data window: a link that drops and reconnects gets the full
window on the new socket, and only packets that arrive on it count."""

from unittest.mock import MagicMock

import pytest

import app.ui.app_manager as am
from app.eeg.neurosky_stream import NeuroSkyStream
from app.session.manager import SessionState
from tests._app import frames, start_connecting


@pytest.fixture(autouse=True)
def _reports(monkeypatch):
    """A failed connect files a diagnostic report: here it is recorded (`am.report_soft_error`), not shown."""
    monkeypatch.setattr(am, "report_soft_error", MagicMock())

T0 = 1000.0


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> float:
        return self.now


class _Link:
    """The Bluetooth link as the real stream reads it, set by the test: the reader's boundary."""

    def __init__(self, clock: _Clock) -> None:
        self._clock = clock
        self.connected = False
        self.last_packet = 0.0
        self.bands = 0.0

    @property
    def seconds_since_last_packet(self) -> float:
        return 0.0 if not self.last_packet else self._clock.now - self.last_packet

    def read_sample(self) -> dict:
        return {"signal_quality": 200, "delta": self.bands}


@pytest.fixture
def wait(fresh_app, monkeypatch):
    """(app, stream, tick): the app in a Start's BT wait entered at T0, on a clock and a link the test moves;
    `tick(at, ...)` runs the wait's tick at T0 + at. `stream` is the app's own, `stream.stops` each time it was
    stopped."""
    clock = _Clock()
    monkeypatch.setattr(am.time, "time", clock)
    monkeypatch.setattr(am.time, "monotonic", clock)
    app = fresh_app
    stream, link = app._real_stream, _Link(clock)
    monkeypatch.setattr(NeuroSkyStream, "is_connected", property(lambda self: link.connected))
    monkeypatch.setattr(NeuroSkyStream, "seconds_since_last_packet", property(lambda self: link.seconds_since_last_packet))
    monkeypatch.setattr(stream, "read_sample", link.read_sample)
    stopped: list = []
    real_stop = stream.stop
    monkeypatch.setattr(stream, "stop", lambda: (stopped.append(True), real_stop())[1])
    monkeypatch.setattr(stream, "stops", stopped, raising=False)
    start_connecting(app, monkeypatch)  # the wait as Start enters it, at T0
    app._ticker.stop()  # its ticks are the test's

    def tick(at: float, *, connected: bool, bands: float = 0.0, packet: bool = False) -> None:
        clock.now = T0 + at
        link.connected = connected
        link.bands = bands
        if packet:
            link.last_packet = clock.now - 0.1  # just before the tick reads it (0.0 means none yet)
        if app._run is not None:
            app._follow_bt_wait(app._run)  # the tick reads the current run

    yield app, stream, tick
    app._db.set_json_setting("bt_device_aliases", {})  # the phone's, not a profile's: gone for the next test
    app._headset.load_aliases()


def _gave_up(stream) -> bool:
    return bool(stream.stops)


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
    assert app._session.manager.state == SessionState.RUNNING


def test_the_new_socket_still_times_out_when_it_sends_nothing(wait):
    app, stream, tick = wait
    tick(6.0, connected=True)
    tick(11.5, connected=False)
    tick(18.0, connected=True)
    tick(25.9, connected=True)
    assert not _gave_up(stream)
    tick(26.5, connected=True)  # its own 8 s, from 18 s
    assert _gave_up(stream)
    assert not app._connecting()
    assert _retry_message(app).startswith("No EEG data received.")


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
    assert app._session.manager.state == SessionState.RUNNING


def _retry_message(app) -> str:
    """The retry screen the last wait exit queued."""
    frames()
    assert app._live_screen._overlay_retry_btn.parent is not None
    return app._live_screen._overlay_status.text


def test_a_drop_after_the_connect_timeout_still_gets_its_reconnect(wait):
    # The headset streams but the sensor isn't on yet, so the wait stays open past the 30 s connect timeout; then the
    # link drops. The reconnect has its own connect window: the 30 s from Start used to end the wait at the drop.
    app, stream, tick = wait
    for at in (6.0, 15.0, 30.0, 34.0):
        tick(at, connected=True, packet=True)
    tick(35.0, connected=False)
    tick(38.0, connected=False)
    tick(40.0, connected=True)
    assert not _gave_up(stream)
    tick(41.0, connected=True, bands=5.0, packet=True)
    assert app._session.manager.state == SessionState.RUNNING


def test_a_late_first_connect_that_drops_gets_its_reconnect(wait):
    app, stream, tick = wait
    tick(20.0, connected=True)
    tick(25.6, connected=False)
    tick(30.5, connected=False)
    tick(32.0, connected=True)
    assert not _gave_up(stream)
    tick(32.5, connected=True, bands=5.0, packet=True)
    assert app._session.manager.state == SessionState.RUNNING


def test_a_headset_that_keeps_dropping_ends_the_wait(wait):
    # Each reconnect gets its own windows, so a headset that keeps closing the link needs its own end: the third drop.
    app, stream, tick = wait
    for connect, drop in ((6.0, 11.5), (18.0, 23.5), (30.0, 35.5)):
        assert not _gave_up(stream)
        tick(connect, connected=True)
        tick(drop, connected=False)
    assert _gave_up(stream)
    assert "keeps closing the connection" in _retry_message(app)


def test_two_drops_then_data_start_the_session(wait):
    app, stream, tick = wait
    for connect, drop in ((6.0, 11.5), (18.0, 23.5)):
        tick(connect, connected=True)
        tick(drop, connected=False)
    tick(30.0, connected=True)
    tick(30.5, connected=True, bands=5.0, packet=True)
    assert not _gave_up(stream)
    assert app._session.manager.state == SessionState.RUNNING


def test_the_next_wait_starts_with_no_drops(wait):
    app, stream, tick = wait
    for connect, drop in ((6.0, 11.5), (18.0, 23.5)):
        tick(connect, connected=True)
        tick(drop, connected=False)
    tick(30.0, connected=True)
    tick(35.5, connected=False)  # the third drop ends this wait
    assert _gave_up(stream) and "keeps closing" in _retry_message(app)
    stream.stops.clear()
    app._on_connect_retry()  # a Retry is a new Start: a run with its own drops
    app._ticker.stop()
    assert app._connecting()
    tick(40.0, connected=True)
    tick(45.5, connected=False)  # this wait's first drop, not the fourth
    assert not _gave_up(stream) and app._connecting()


def test_band_values_from_before_a_drop_dont_start_the_session_on_the_new_socket(wait):
    # The reader keeps the last band values across a reconnect: a band packet just before the drop must not start the
    # session on a new socket that hasn't sent anything yet.
    app, stream, tick = wait
    tick(6.0, connected=True)
    tick(6.5, connected=False, bands=5.0, packet=True)  # bands and a packet arrived, then the link dropped
    tick(12.0, connected=True, bands=5.0)  # reconnected: the old bands are still there, nothing new yet
    assert app._session.manager.state != SessionState.RUNNING
    tick(12.5, connected=True, bands=5.0, packet=True)  # the new socket's first data
    assert app._session.manager.state == SessionState.RUNNING


def _connect_failed(stream, tick) -> None:
    stream._running = False  # the reader ended with an error
    tick(5.0, connected=False)


def _connect_timed_out(stream, tick) -> None:
    tick(30.5, connected=False)


def _no_data(stream, tick) -> None:
    tick(6.0, connected=True)
    tick(14.5, connected=True)


def _keeps_closing(stream, tick) -> None:
    for connect, drop in ((6.0, 11.5), (18.0, 23.5), (30.0, 35.5)):
        tick(connect, connected=True)
        tick(drop, connected=False)


@pytest.mark.parametrize("ending", [_connect_failed, _connect_timed_out, _no_data, _keeps_closing])
def test_every_wait_ending_names_the_headset_on_the_session_screen(wait, ending):
    """One ending for the wait (#99): each leaves the headset's name, as its user calls it, under the retry screen."""
    app, stream, tick = wait
    app._headset.on_rename(stream._device_address, "MindWave Mobile", "Blue")
    ending(stream, tick)
    assert _gave_up(stream)
    _retry_message(app)
    assert app._live_screen._device_label.text == "[Blue]"
