"""Reader lifecycle: no path may leave the MindWave's single RFCOMM channel connected but undrained."""
import errno
import os
import socket
import threading
import time

import pytest

from app.eeg import bt_links
from app.eeg.neurosky_stream import NeuroSkyStream, connect_error_text


class FakeSocket:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True

    def getInputStream(self):
        return None


class SlowLinks:
    """The links a stream makes (bt_links.link_for's place): each connect takes `delay` seconds, uninterruptible, then
    adopts a fake socket."""

    def __init__(self, delay: float):
        self.delay = delay
        self.sockets: list[FakeSocket] = []
        self.connect_calls = 0
        self.connected = threading.Event()

    def __call__(self, address, name, stop) -> bt_links.Link:
        return _SlowLink(address, name, stop, self)


class _SlowLink(bt_links.Link):
    def __init__(self, address, name, stop, links: SlowLinks):
        super().__init__(address, name, stop)
        self._links = links
        self._socket = None

    def connect(self) -> None:
        self._links.connect_calls += 1
        time.sleep(self._links.delay)
        sock = FakeSocket()
        self._links.sockets.append(sock)
        self._socket = sock
        self._links.connected.set()

    def read(self, max_bytes: int) -> bytes:
        time.sleep(0.01)
        return b""

    def _close_open(self) -> None:
        sock, self._socket = self._socket, None
        if sock is not None:
            sock.close()


def _links(monkeypatch, make) -> None:
    """The stream's start() makes its link with `make(address, name, stop)`."""
    monkeypatch.setattr(bt_links, "link_for", make)


@pytest.fixture
def slow(monkeypatch):
    """A stream (NeuroSkyStream, or the class given) whose links connect slowly: (stream, its links)."""
    def make(delay: float, stream_class=NeuroSkyStream) -> tuple[NeuroSkyStream, SlowLinks]:
        links = SlowLinks(delay)
        _links(monkeypatch, links)
        return stream_class(), links
    return make


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class TestReaderLifecycle:
    def test_stop_during_connect_closes_the_orphaned_socket(self, slow):
        s, links = slow(0.4)
        s._STOP_JOIN_TIMEOUT = 0.1
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        s.start()
        time.sleep(0.05)  # thread is inside connect
        s.stop()  # join times out; the thread connects afterwards

        assert links.connected.wait(2.0), "connect never completed"
        time.sleep(0.3)  # let the superseded thread run its cleanup

        assert len(links.sockets) == 1
        assert links.sockets[0].closed, "socket adopted after stop() was left open"
        assert s.is_connected is False

    def test_start_is_refused_while_a_timed_out_reader_is_still_alive(self, slow):
        """stop() whose join times out must keep the thread so start() refuses."""
        s, links = slow(0.6)
        s._STOP_JOIN_TIMEOUT = 0.1
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        assert s.start() is True
        time.sleep(0.05)
        s.stop()
        assert s._thread is not None and s._thread.is_alive()

        assert s.start() is False
        assert links.connect_calls == 1, "a second reader thread was started"
        assert "still closing" in s._last_connect_error

        s._thread.join(2.0)
        assert links.sockets[0].closed
        links.delay = 0.0
        links.connected.clear()
        assert s.start() is True
        assert links.connected.wait(2.0)
        assert links.connect_calls == 2
        s.stop()

    def test_start_without_a_device_is_refused_with_a_reason(self, slow):
        s, links = slow(0.0)
        assert s.start() is False
        assert s._last_connect_error
        assert links.connect_calls == 0

    def test_concurrent_stops_do_not_crash(self, slow):
        """The tick thread and the main thread can both be inside stop()."""
        s, links = slow(0.4)
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

    def test_reader_exit_clears_a_connected_flag_set_after_a_racing_stop(self, slow):
        """A stop() between the epoch check and `_connected = True` must not leave it stuck True."""

        class RacingStopStream(NeuroSkyStream):
            def _boost_thread_priority(self):
                # Runs right after `_connected = True`: land a stop() here.
                self._running = False
                self._connect_epoch += 1

        s, links = slow(0.0, RacingStopStream)
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        s.start()
        s._thread.join(2.0)
        assert s.is_connected is False

    def test_clean_start_stop_closes_the_socket_once(self, slow):
        s, links = slow(0.0)
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        s.start()
        assert links.connected.wait(2.0)
        time.sleep(0.05)
        assert s.is_connected is True

        s.stop()
        assert len(links.sockets) == 1
        assert links.sockets[0].closed
        assert s.is_connected is False

    def test_a_new_target_closes_the_link_to_the_old_one(self, slow):
        """The next start must reach the new headset: a kept link would carry its sessions under the new one's name."""
        s, links = slow(0.0)
        s.set_device("00:11:22:33:44:01", "MindWave Mobile")
        s.start()
        assert links.connected.wait(2.0)
        assert _wait_until(lambda: s.is_connected)

        s.set_device("00:11:22:33:44:02", "MindWave Mobile")
        assert links.sockets[0].closed
        assert s.is_connected is False
        assert s._thread is None
        assert s._device_address == "00:11:22:33:44:02"

    def test_no_target_closes_the_link(self, slow):
        """A profile without a headset gets none: a link to the last profile's must not carry its sessions (#99)."""
        s, links = slow(0.0)
        s.set_device("00:11:22:33:44:01", "MindWave Mobile")
        s.start()
        assert _wait_until(lambda: s.is_connected)

        s.set_device(None)
        assert links.sockets[0].closed
        assert s.is_connected is False
        assert s._device_address is None and s._device_name is None
        assert s.start() is False  # nothing to connect to

    def test_the_same_target_keeps_the_link(self, slow):
        s, links = slow(0.0)
        s.set_device("00:11:22:33:44:01", "MindWave Mobile")
        s.start()
        assert _wait_until(lambda: s.is_connected)
        try:
            s.set_device("00:11:22:33:44:01", "MindWave Mobile")
            assert not links.sockets[0].closed
            assert s.is_connected is True
        finally:
            s.stop()

    def test_epoch_advances_on_every_start_and_stop(self, slow):
        s, links = slow(0.0)
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        first = s._connect_epoch
        s.start()
        assert s._connect_epoch == first + 1
        s.stop()
        assert s._connect_epoch == first + 2


class TestStopWakesBlockedReads:
    def test_stop_wakes_a_reader_blocked_in_a_desktop_recv(self, monkeypatch):
        near, far = socket.socketpair()
        near.settimeout(5.0)  # the desktop read timeout; no data ever arrives

        class ConnectedLinux(bt_links.LinuxRfcomm):
            def connect(self):
                self._socket = near

        _links(monkeypatch, ConnectedLinux)
        s = NeuroSkyStream()
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

    def test_stop_wakes_a_reader_blocked_on_a_silent_serial_device(self, monkeypatch):
        r, w = os.pipe()  # a splitter that never writes

        class OpenSerial(bt_links.SerialDevice):
            def connect(self):
                self._fd = r

        _links(monkeypatch, OpenSerial)
        s = NeuroSkyStream()
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


class Sockets:
    """The fake sockets the attempts take in turn, and the ones they made."""

    def __init__(self, sockets: list[BlockingSocket]):
        self.made: list[BlockingSocket] = []
        self._queue = list(sockets)

    def make(self) -> BlockingSocket:
        sock = self._queue.pop(0)
        self.made.append(sock)
        return sock


def _attempt_link(sockets: Sockets):
    """An Android link whose connect runs the real attempt loop over `sockets`."""
    class AttemptLink(bt_links.AndroidRfcomm):
        def connect(self) -> None:
            self._connect_first([("secure", sockets.make), ("insecure", sockets.make)])
    return AttemptLink


@pytest.fixture
def attempts(monkeypatch):
    """A stream whose links connect through the real attempt loop over the given fake sockets."""
    def make(*sockets: BlockingSocket) -> tuple[NeuroSkyStream, Sockets]:
        made = Sockets(list(sockets))
        _links(monkeypatch, _attempt_link(made))
        stream = NeuroSkyStream()
        stream.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        return stream, made
    return make


class TestConnectAttempts:
    def test_stop_aborts_a_blocked_connect_without_trying_the_next_method(self, attempts):
        s, made = attempts(BlockingSocket(), BlockingSocket())
        s.start()
        time.sleep(0.1)  # reader is blocked inside connect()

        t0 = time.monotonic()
        s.stop()
        assert time.monotonic() - t0 < 1.0, "stop() waited out the connect instead of aborting it"
        assert s._thread is None, "reader outlived stop()"
        assert len(made.made) == 1, "fell through to the next connect method after the abort"
        assert made.made[0].closed
        assert s._last_connect_error == "", "a user stop was recorded as a connect failure"

    def test_successful_attempt_is_adopted_and_closed_on_stop(self, attempts):
        s, made = attempts(BlockingSocket(succeed=True))
        s.start()
        assert _wait_until(lambda: s.is_connected)
        sock = made.made[0]
        assert s._link._socket is sock
        assert s._link._pending is None
        assert not sock.closed

        s.stop()
        assert sock.closed
        assert s.is_connected is False

    def test_failed_attempts_close_every_socket(self):
        made = Sockets([BlockingSocket(fail=True), BlockingSocket(fail=True)])
        link = _attempt_link(made)("AA:BB:CC:DD:EE:FF", "Fake", threading.Event())
        try:
            link.connect()
        except RuntimeError as e:
            detail = str(e).split("All RFCOMM methods failed:", 1)[1]
            labels = [part.split(":", 1)[0].strip() for part in detail.split(";")]
            assert labels == ["secure", "insecure"]
        else:
            raise AssertionError("expected all attempts to fail")
        assert all(sock.closed for sock in made.made)
        assert link._pending is None


class TestCloseWakesEverySocketKind:
    def test_close_shuts_down_a_non_native_socket_before_closing_it(self):
        """PyBluez sockets aren't socket.socket, but a blocked connect() still needs shutdown()."""
        calls: list[str] = []

        class PyBluezLike:
            def shutdown(self, how):
                calls.append(f"shutdown({how})")

            def close(self):
                calls.append("close")

        link = bt_links.LinuxRfcomm("AA:BB:CC:DD:EE:FF", "Fake", threading.Event())
        link._pending = PyBluezLike()
        link.close()
        assert calls == [f"shutdown({socket.SHUT_RDWR})", "close"]
        assert link._pending is None

    def test_close_tolerates_a_socket_without_shutdown(self):
        """Android's Java BluetoothSocket has no shutdown(); close() alone must still run."""
        fake = FakeSocket()
        link = bt_links.AndroidRfcomm("AA:BB:CC:DD:EE:FF", "Fake", threading.Event())
        link._pending = fake
        link.close()
        assert fake.closed


class FlakyLinks(SlowLinks):
    """Links whose first connect's reads fail once: the reader reconnects, then the data flows."""

    def __init__(self):
        super().__init__(0.0)
        self.reads_failed = 0

    def __call__(self, address, name, stop) -> bt_links.Link:
        return _FlakyLink(address, name, stop, self)


class _FlakyLink(_SlowLink):
    def read(self, max_bytes: int) -> bytes:
        if self._links.reads_failed == 0:
            self._links.reads_failed += 1
            raise OSError("Software caused connection abort")
        return super().read(max_bytes)


class TestReconnect:
    def test_a_read_error_reconnects_the_link_and_the_reader_goes_on(self, monkeypatch):
        links = FlakyLinks()
        _links(monkeypatch, links)
        s = NeuroSkyStream()
        s._stop_event.wait = lambda timeout=None: False  # the 2 s back-off, at once
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        s.start()
        try:
            assert _wait_until(lambda: links.connect_calls == 2 and s.is_connected)
            assert links.sockets[0].closed and not links.sockets[1].closed  # the broken link closed, the new one kept
            assert s._thread.is_alive()
        finally:
            s.stop()
        assert links.sockets[1].closed


class FailingLinks(SlowLinks):
    """Links whose connects fail with `error` from connect number `fail_from` on; the reads before that fail too."""

    def __init__(self, error: Exception, fail_from: int = 1):
        super().__init__(0.0)
        self.error = error
        self.fail_from = fail_from

    def __call__(self, address, name, stop) -> bt_links.Link:
        return _FailingLink(address, name, stop, self)


class _FailingLink(_SlowLink):
    def connect(self) -> None:
        if self._links.connect_calls + 1 >= self._links.fail_from:
            self._links.connect_calls += 1
            raise self._links.error
        super().connect()

    def read(self, max_bytes: int) -> bytes:
        raise OSError("Software caused connection abort")


@pytest.mark.parametrize(("error", "text"), [
    (OSError(errno.EHOSTDOWN, "Host is down"), "Headset is asleep or off.\nTurn it on and retry."),
    (OSError(errno.EBUSY, "Device or resource busy"), "Bluetooth busy.\nWait 15 seconds and retry."),
    (TimeoutError("timed out"), "Connection timed out.\nCheck headset is on and in range."),
    (RuntimeError("Desktop RFCOMM connect failed: Connection Timed Out"),
     "Connection timed out.\nCheck headset is on and in range."),
    (RuntimeError("All RFCOMM methods failed: secure: read failed"), "Check headset is on and paired."),
])
def test_a_failed_connect_tells_the_screen_why(error, text):
    assert connect_error_text(error) == text


class TestConnectFailure:
    def test_a_failed_first_connect_says_why_and_ends_the_reader(self, monkeypatch):
        links = FailingLinks(OSError(errno.EHOSTDOWN, "Host is down"))
        _links(monkeypatch, links)
        s = NeuroSkyStream()
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        assert s.start() is True
        s._thread.join(2.0)
        assert not s._thread.is_alive()
        assert s._last_connect_error == "Headset is asleep or off.\nTurn it on and retry."
        assert (s._running, s.is_connected, links.connect_calls) == (False, False, 1)

    def test_a_failed_reconnect_ends_the_reader(self, monkeypatch):
        links = FailingLinks(OSError(errno.EHOSTDOWN, "Host is down"), fail_from=2)
        _links(monkeypatch, links)
        s = NeuroSkyStream()
        s._stop_event.wait = lambda timeout=None: False  # the 2 s back-off, at once
        s.set_device("AA:BB:CC:DD:EE:FF", "Fake")
        s.start()
        s._thread.join(2.0)
        assert not s._thread.is_alive()
        assert (s._running, s.is_connected, links.connect_calls) == (False, False, 2)
        assert links.sockets[0].closed, "the broken link was left open"
