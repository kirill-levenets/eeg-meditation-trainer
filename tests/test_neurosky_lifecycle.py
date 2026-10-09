"""Reader lifecycle: no path may leave the MindWave's single RFCOMM channel connected but undrained."""
import os
import socket
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
    """Stream whose connect takes `delay` seconds (uninterruptible), then adopts a fake socket."""

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


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


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
        assert s.start() is True
        time.sleep(0.05)
        s.stop()
        assert s._thread is not None and s._thread.is_alive()

        assert s.start() is False
        assert s.connect_calls == 1, "a second reader thread was started"
        assert "still closing" in s._last_connect_error

        s._thread.join(2.0)
        assert s.sockets[0].closed
        s._delay = 0.0
        s._connected_event.clear()
        assert s.start() is True
        assert s._connected_event.wait(2.0)
        assert s.connect_calls == 2
        s.stop()

    def test_start_without_a_device_is_refused_with_a_reason(self):
        s = SlowConnectStream(delay=0.0)
        assert s.start() is False
        assert s._last_connect_error
        assert s.connect_calls == 0

    def test_concurrent_stops_do_not_crash(self):
        """The tick thread and the main thread can both be inside stop()."""
        s = SlowConnectStream(delay=0.4)
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        s.start()
        time.sleep(0.05)
        errors: list[BaseException] = []

        def stop():
            try:
                s.stop()
            except BaseException as e:
                errors.append(e)

        threads = [threading.Thread(target=stop) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(3.0)
        assert errors == []
        assert s._thread is None

    def test_reader_exit_clears_a_connected_flag_set_after_a_racing_stop(self):
        """A stop() between the epoch check and `_connected = True` must not leave it stuck True."""

        class RacingStopStream(SlowConnectStream):
            def _boost_thread_priority(self):
                # Runs right after `_connected = True`: land a stop() here.
                self._running = False
                self._connect_epoch += 1

        s = RacingStopStream(delay=0.0)
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        s.start()
        s._thread.join(2.0)
        assert s.is_connected is False

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

    def test_a_new_target_closes_the_link_to_the_old_one(self):
        """The next start must reach the new headset: a kept link would carry its sessions under the new one's name."""
        s = SlowConnectStream(delay=0.0)
        s.set_device("00:11:22:33:44:01", "MindWave Mobile")
        s.start()
        assert s._connected_event.wait(2.0)
        assert _wait_until(lambda: s.is_connected)

        s.set_device("00:11:22:33:44:02", "MindWave Mobile")
        assert s.sockets[0].closed
        assert s.is_connected is False
        assert s._thread is None
        assert s._device_address == "00:11:22:33:44:02"

    def test_the_same_target_keeps_the_link(self):
        s = SlowConnectStream(delay=0.0)
        s.set_device("00:11:22:33:44:01", "MindWave Mobile")
        s.start()
        assert _wait_until(lambda: s.is_connected)
        try:
            s.set_device("00:11:22:33:44:01", "MindWave Mobile")
            assert not s.sockets[0].closed
            assert s.is_connected is True
        finally:
            s.stop()

    def test_epoch_advances_on_every_start_and_stop(self):
        s = SlowConnectStream(delay=0.0)
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        first = s._connect_epoch
        s.start()
        assert s._connect_epoch == first + 1
        s.stop()
        assert s._connect_epoch == first + 2


class TestStopWakesBlockedReads:
    def test_stop_wakes_a_reader_blocked_in_a_desktop_recv(self):
        near, far = socket.socketpair()
        near.settimeout(5.0)  # the desktop read timeout; no data ever arrives

        class DesktopStream(NeuroSkyStream):
            def _connect_bluetooth(self):
                self._desktop_socket = near

        s = DesktopStream()
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        try:
            s.start()
            assert _wait_until(lambda: s.is_connected)
            time.sleep(0.1)  # reader is blocked in recv()
            t0 = time.monotonic()
            s.stop()
            assert time.monotonic() - t0 < 1.0, "stop() waited out the recv timeout"
            assert s._thread is None
        finally:
            far.close()

    def test_stop_wakes_a_reader_blocked_on_a_silent_serial_device(self):
        r, w = os.pipe()  # a splitter that never writes

        class SerialStream(NeuroSkyStream):
            def _connect_bluetooth(self):
                self._serial_fd = r

        s = SerialStream()
        s.set_device("/tmp/fake_splitter", "Fake")
        try:
            s.start()
            assert _wait_until(lambda: s.is_connected)
            time.sleep(0.1)
            t0 = time.monotonic()
            s.stop()
            assert time.monotonic() - t0 < 1.5, "stop() waited on a blocked os.read()"
            assert s._thread is None, "reader outlived stop(); start() would refuse"
        finally:
            os.close(w)


class BlockingSocket:
    """Android-like socket: connect() blocks until close() aborts it."""

    def __init__(self, fail: bool = False, succeed: bool = False):
        self.closed = False
        self.fail = fail
        self.succeed = succeed
        self._closed_event = threading.Event()

    def connect(self):
        if self.fail:
            raise OSError("host is down")
        if self.succeed:
            return
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


class TestConnectAttempts:
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

    def test_successful_attempt_is_adopted_and_closed_on_stop(self):
        s = AttemptStream([BlockingSocket(succeed=True)])
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        s.start()
        assert _wait_until(lambda: s.is_connected)
        sock = s.made[0]
        assert s._bt_socket is sock
        assert s._pending_socket is None
        assert not sock.closed

        s.stop()
        assert sock.closed
        assert s.is_connected is False

    def test_failed_attempts_close_every_socket(self):
        s = AttemptStream([BlockingSocket(fail=True), BlockingSocket(fail=True)])
        s._running = True
        try:
            s._connect_bluetooth()
        except RuntimeError as e:
            detail = str(e).split("All RFCOMM methods failed:", 1)[1]
            labels = [part.split(":", 1)[0].strip() for part in detail.split(";")]
            assert labels == ["secure", "insecure"]
        else:
            raise AssertionError("expected all attempts to fail")
        assert all(sock.closed for sock in s.made)
        assert s._pending_socket is None


class TestCloseWakesEverySocketKind:
    def test_close_shuts_down_a_non_native_socket_before_closing_it(self):
        """PyBluez sockets aren't socket.socket, but a blocked connect() still needs shutdown()."""
        calls: list[str] = []

        class PyBluezLike:
            def shutdown(self, how):
                calls.append(f"shutdown({how})")

            def close(self):
                calls.append("close")

        s = NeuroSkyStream()
        s._pending_socket = PyBluezLike()
        s._close_socket()
        assert calls == [f"shutdown({socket.SHUT_RDWR})", "close"]
        assert s._pending_socket is None

    def test_close_tolerates_a_socket_without_shutdown(self):
        """Android's Java BluetoothSocket has no shutdown(); close() alone must still run."""
        fake = FakeSocket()
        s = NeuroSkyStream()
        s._pending_socket = fake
        s._close_socket()
        assert fake.closed
