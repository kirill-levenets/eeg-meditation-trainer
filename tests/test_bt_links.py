"""The links to a MindWave: a stop seen before a socket is published gives up without connecting it; Linux waits out a
busy channel, and a stop ends that wait; a failed socket is closed; each link reads what came in."""
import errno
import sys
import threading
import types

import pytest

from app.eeg import bt_links


class RecordingSocket:
    """A socket that records its connect and close; `errors` are raised by the connects in turn."""

    def __init__(self, errors: list[Exception] | None = None):
        self.connects = 0
        self.closed = False
        self._errors = list(errors or [])

    def connect(self, *_args) -> None:
        self.connects += 1
        if self._errors:
            raise self._errors.pop(0)

    def close(self) -> None:
        self.closed = True

    def settimeout(self, _seconds) -> None:
        pass

    def getInputStream(self):
        return None


class InstantEvent(threading.Event):
    """A stop event whose waits return at once (False: no stop) unless it is set."""

    def wait(self, timeout=None) -> bool:
        return self.is_set()


def test_a_stop_before_the_socket_is_published_gives_up_without_connecting_it():
    stop = threading.Event()
    stop.set()
    sock = RecordingSocket()
    link = bt_links.AndroidRfcomm("AA:BB:CC:DD:EE:FF", "Fake", stop)
    with pytest.raises(bt_links.ConnectAborted):
        link._connect_first([("secure", lambda: sock), ("insecure", RecordingSocket)])
    assert (sock.connects, sock.closed, link._pending) == (0, True, None)


@pytest.fixture
def linux_sockets(monkeypatch):
    """Linux RFCOMM over fake sockets: each one made takes the next list of connect errors."""
    made: list[RecordingSocket] = []
    plans: list[list[Exception]] = []

    def socket(*_args):
        made.append(RecordingSocket(plans.pop(0) if plans else []))
        return made[-1]

    fake = types.SimpleNamespace(AF_BLUETOOTH=31, SOCK_STREAM=1, SHUT_RDWR=2, timeout=TimeoutError, socket=socket)
    monkeypatch.setattr(bt_links, "_socket", fake)
    return made, plans


def test_linux_waits_out_a_busy_channel_and_connects(linux_sockets):
    made, plans = linux_sockets
    plans.extend([[OSError(errno.EBUSY, "Device or resource busy")], []])
    link = bt_links.LinuxRfcomm("AA:BB:CC:DD:EE:FF", "Fake", InstantEvent())
    link.connect()
    assert [s.connects for s in made] == [1, 1] and made[0].closed and link._socket is made[1]


class StopDuringWait(threading.Event):
    """A stop event that stop() sets while the busy channel is waited out."""

    def wait(self, timeout=None) -> bool:
        self.set()
        return True


def test_a_stop_during_the_busy_wait_ends_the_connect(linux_sockets):
    made, plans = linux_sockets
    plans.append([OSError(errno.EBUSY, "Device or resource busy")])
    link = bt_links.LinuxRfcomm("AA:BB:CC:DD:EE:FF", "Fake", StopDuringWait())
    with pytest.raises(bt_links.ConnectAborted):
        link.connect()
    assert len(made) == 1 and made[0].closed


def test_linux_gives_up_on_another_error_at_once(linux_sockets):
    made, plans = linux_sockets
    plans.append([OSError(errno.EHOSTDOWN, "Host is down")])
    link = bt_links.LinuxRfcomm("AA:BB:CC:DD:EE:FF", "Fake", InstantEvent())
    with pytest.raises(RuntimeError, match="Host is down"):
        link.connect()
    assert len(made) == 1 and made[0].closed


@pytest.fixture
def pybluez(monkeypatch):
    """Linux without AF_BLUETOOTH, PyBluez in its place: the sockets it made."""
    made: list[RecordingSocket] = []
    errors: list[Exception] = []

    def bluetooth_socket(_protocol):
        made.append(RecordingSocket(list(errors)))
        return made[-1]

    monkeypatch.setattr(bt_links, "_socket", types.SimpleNamespace(SHUT_RDWR=2, timeout=TimeoutError))
    monkeypatch.setitem(sys.modules, "bluetooth", types.SimpleNamespace(RFCOMM=3, BluetoothSocket=bluetooth_socket))
    return made, errors


def test_a_failed_pybluez_connect_closes_its_socket(pybluez):
    made, errors = pybluez
    errors.append(OSError(errno.EHOSTDOWN, "Host is down"))
    link = bt_links.LinuxRfcomm("AA:BB:CC:DD:EE:FF", "Fake", InstantEvent())
    with pytest.raises(RuntimeError, match="PyBluez.*Host is down"):
        link.connect()
    assert made[0].closed and link._pending is None and link._socket is None


def test_a_pybluez_connect_failing_under_a_stop_is_an_abort(pybluez):
    made, errors = pybluez
    errors.append(OSError(errno.EBADF, "Bad file descriptor"))  # stop() closed it mid-connect
    stop = threading.Event()
    stop.set()
    link = bt_links.LinuxRfcomm("AA:BB:CC:DD:EE:FF", "Fake", stop)
    with pytest.raises(bt_links.ConnectAborted):
        link.connect()
    assert made[0].closed


def test_pybluez_adopts_a_connected_socket(pybluez):
    made, _errors = pybluez
    link = bt_links.LinuxRfcomm("AA:BB:CC:DD:EE:FF", "Fake", InstantEvent())
    link.connect()
    assert link._socket is made[0] and not made[0].closed


class JavaInputStream:
    """Android's InputStream over `waiting` bytes: available(), a blocking one-byte read() and a sized read."""

    def __init__(self, waiting: bytes = b"", arriving: bytes = b""):
        self._waiting = bytearray(waiting)
        self._arriving = bytearray(arriving)  # what a blocking read() waits for: its first byte, then the rest
        self.sized_reads: list[int] = []

    def available(self) -> int:
        return len(self._waiting)

    def read(self, buf=None, offset=0, length=0) -> int:
        if buf is None:
            if not self._arriving:
                return -1
            first = self._arriving.pop(0)
            self._waiting += self._arriving
            self._arriving.clear()
            return first
        self.sized_reads.append(length)
        n = min(length, len(self._waiting))
        buf[offset:offset + n] = self._waiting[:n]
        del self._waiting[:n]
        return n


def _android_reading(stream: JavaInputStream) -> bt_links.AndroidRfcomm:
    link = bt_links.AndroidRfcomm("AA:BB:CC:DD:EE:FF", "Fake", threading.Event())
    link._adopt(types.SimpleNamespace(getInputStream=lambda: stream, close=lambda: None), "secure")
    return link


def test_android_reads_what_is_waiting_in_one_read_of_its_size():
    stream = JavaInputStream(waiting=bytes(range(5)))
    link = _android_reading(stream)
    assert link.read(512) == bytes(range(5))
    assert stream.sized_reads == [5]
    assert (link.take_high_water(), link.take_high_water()) == (5, 0)


def test_android_waits_for_a_byte_then_drains_what_came_with_it_within_the_limit():
    stream = JavaInputStream(arriving=b"\xaa\xaa\x04\x80")
    link = _android_reading(stream)
    assert link.read(2) == b"\xaa\xaa"  # the first byte, then one more: the limit counts both
    assert stream.sized_reads == [1]
    assert link.read(512) == b"\x04\x80"


def test_android_reads_nothing_at_the_end_of_the_stream():
    assert _android_reading(JavaInputStream()).read(512) == b""


class FakeSerialPort:
    def __init__(self, port: str, baudrate: int, timeout: float):
        self.opened = (port, baudrate, timeout)
        self.waiting = bytearray()
        self.closed = False

    @property
    def in_waiting(self) -> int:
        return len(self.waiting)

    def read(self, n: int) -> bytes:
        out = bytes(self.waiting[:n])
        del self.waiting[:n]
        return out

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def pyserial(monkeypatch):
    """pyserial over fake ports: the ports opened."""
    opened: list[FakeSerialPort] = []

    def open_port(**kwargs):
        opened.append(FakeSerialPort(**kwargs))
        return opened[-1]

    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=open_port))
    return opened


def test_windows_opens_the_com_port_reads_what_waits_and_closes_it(pyserial):
    link = bt_links.WindowsSerial("COM5", "MindWave", threading.Event())
    link.connect()
    port = pyserial[0]
    assert port.opened == ("COM5", 57600, 5.0)
    port.waiting += b"\xaa\xaa\x02"
    assert link.read(2) == b"\xaa\xaa"
    assert link.read(512) == b"\x02"
    assert link.read(512) == b""  # nothing waiting: a one-byte read that timed out
    link.close()
    assert port.closed and link.read(512) == b""


def test_windows_refuses_a_mac_address_with_no_com_port(pyserial):
    link = bt_links.WindowsSerial("AA:BB:CC:DD:EE:FF", "MindWave", threading.Event())
    with pytest.raises(RuntimeError, match="Could not find COM port"):
        link.connect()
    assert pyserial == []
