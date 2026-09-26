"""Reader-thread lifecycle: a stopped connect must never leave a live socket.

The MindWave serves one RFCOMM channel. A second connected-but-undrained
channel stalls its transmitter until the headset is power-cycled, so an
abandoned connect is not a leak of memory but a hardware failure.
"""
import threading
import time

from app.eeg.neurosky_stream import NeuroSkyStream


class FakeSocket:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True

    def getInputStream(self):
        return None


class SlowConnectStream(NeuroSkyStream):
    """Stream whose connect takes `delay` seconds, then adopts a fake socket."""

    def __init__(self, delay: float):
        super().__init__()
        self._delay = delay
        self.sockets: list[FakeSocket] = []
        self.connect_calls = 0
        self._connected_event = threading.Event()

    def _connect_bluetooth(self) -> None:
        self.connect_calls += 1
        time.sleep(self._delay)
        sock = FakeSocket()
        self.sockets.append(sock)
        self._bt_socket = sock
        self._connected_event.set()


class TestReaderLifecycle:
    def test_stop_during_connect_closes_the_orphaned_socket(self):
        s = SlowConnectStream(delay=0.4)
        s._STOP_JOIN_TIMEOUT = 0.1
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        s.start()
        time.sleep(0.05)  # thread is inside connect
        s.stop()  # join times out; the thread connects afterwards

        assert s._connected_event.wait(2.0), "connect never completed"
        time.sleep(0.3)  # let the superseded thread run its cleanup

        assert len(s.sockets) == 1
        assert s.sockets[0].closed, "socket adopted after stop() was left open"
        assert s.is_connected is False

    def test_start_is_refused_while_a_timed_out_reader_is_still_alive(self):
        """stop() whose join times out must keep the thread so start() refuses."""
        s = SlowConnectStream(delay=0.6)
        s._STOP_JOIN_TIMEOUT = 0.1
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        s.start()
        time.sleep(0.05)
        s.stop()
        assert s._thread is not None and s._thread.is_alive()

        s.start()
        assert s.connect_calls == 1, "a second reader thread was started"
        assert "still closing" in s._last_connect_error

        s._thread.join(2.0)
        assert s.sockets[0].closed
        s._delay = 0.0
        s._connected_event.clear()
        s.start()
        assert s._connected_event.wait(2.0)
        assert s.connect_calls == 2
        s.stop()

    def test_clean_start_stop_closes_the_socket_once(self):
        s = SlowConnectStream(delay=0.0)
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        s.start()
        assert s._connected_event.wait(2.0)
        time.sleep(0.05)
        assert s.is_connected is True

        s.stop()
        assert len(s.sockets) == 1
        assert s.sockets[0].closed
        assert s.is_connected is False

    def test_superseded_reader_does_not_adopt_a_second_channel(self):
        """The pre-fix failure: stop() abandons a connecting thread, start()
        launches another, and both end up holding a live RFCOMM channel."""
        s = SlowConnectStream(delay=0.5)
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        s.start()
        time.sleep(0.05)
        s.stop()
        s._thread = None  # drop the guard: reproduce the old start() path
        s._delay = 0.0
        s._connected_event.clear()
        s.start()
        assert s._connected_event.wait(2.0)
        time.sleep(0.7)  # first thread finishes connecting well after

        assert len(s.sockets) == 2, "expected both connects to have completed"
        live = [i for i, sock in enumerate(s.sockets) if not sock.closed]
        assert len(live) <= 1, f"{len(live)} RFCOMM channels left open: {live}"
        assert s.sockets[0].closed, "the superseded thread kept its channel open"

    def test_epoch_advances_on_every_start_and_stop(self):
        s = SlowConnectStream(delay=0.0)
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        first = s._connect_epoch
        s.start()
        assert s._connect_epoch == first + 1
        s.stop()
        assert s._connect_epoch == first + 2


class BlockingSocket:
    """Android-like socket: connect() blocks until close() aborts it."""

    def __init__(self, fail: bool = False):
        self.closed = False
        self.fail = fail
        self._closed_event = threading.Event()

    def connect(self):
        if self.fail:
            raise OSError("host is down")
        if self._closed_event.wait(5.0):
            raise OSError("socket closed")

    def close(self):
        self.closed = True
        self._closed_event.set()

    def getInputStream(self):
        return None


class AttemptStream(NeuroSkyStream):
    """Stream whose connect runs the real attempt loop over fake socket factories."""

    def __init__(self, sockets: list[BlockingSocket]):
        super().__init__()
        self.made: list[BlockingSocket] = []
        self._queue = list(sockets)

    def _make(self) -> BlockingSocket:
        sock = self._queue.pop(0)
        self.made.append(sock)
        return sock

    def _connect_bluetooth(self) -> None:
        self._run_connect_attempts([("secure", self._make), ("insecure", self._make)])


class TestConnectAbort:
    def test_stop_aborts_a_blocked_connect_without_trying_the_next_method(self):
        s = AttemptStream([BlockingSocket(), BlockingSocket()])
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        s.start()
        time.sleep(0.1)  # reader is blocked inside connect()

        t0 = time.monotonic()
        s.stop()
        assert time.monotonic() - t0 < 1.0, "stop() waited out the connect instead of aborting it"
        assert s._thread is None, "reader outlived stop()"
        assert len(s.made) == 1, "fell through to the next connect method after the abort"
        assert s.made[0].closed
        assert s._last_connect_error == "", "a user stop was recorded as a connect failure"

    def test_failed_attempts_close_every_socket(self):
        s = AttemptStream([BlockingSocket(fail=True), BlockingSocket(fail=True)])
        s._running = True
        try:
            s._connect_bluetooth()
        except RuntimeError as e:
            assert "secure" in str(e) and "insecure" in str(e)
        else:
            raise AssertionError("expected all attempts to fail")
        assert all(sock.closed for sock in s.made)
        assert s._pending_socket is None
