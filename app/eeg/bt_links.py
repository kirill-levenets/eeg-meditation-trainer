"""The links to a MindWave, one class per kind: Android RFCOMM (pyjnius), Linux RFCOMM (a Python socket, or PyBluez),
a Windows COM port (pyserial) and a serial device path (the splitter). Each owns its handles; the platform's paired
devices are listed next to its link."""
import errno
import itertools
import os
import select
import socket as _socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from app import android_jni
from app.logger import logger

_IS_WINDOWS: bool = sys.platform == "win32"
NEUROSKY_SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"


class ConnectAborted(RuntimeError):
    """The stream's stop() came during a connect."""

    def __init__(self) -> None:
        super().__init__("connect aborted by stop()")


class Link:
    """A link's handles are its own. stop() closes them from another thread: a connect in flight aborts, a blocked read
    returns. One link at a time (the stream has at most one reader)."""

    def __init__(self, address: str, name: str, stop: threading.Event) -> None:
        self._address = address
        self._name = name
        self._stop = stop  # the stream's: set by its stop(), before it closes the link
        self._close_lock = threading.Lock()  # stop() and the exiting reader both close

    def connect(self) -> None:
        raise NotImplementedError

    def read(self, max_bytes: int) -> bytes:
        """Up to `max_bytes`, b"" when none came in time; raises when the link broke."""
        raise NotImplementedError

    def take_high_water(self) -> int:
        """The largest backlog a read found since the last call (the reader losing to the stream), 0 if unmeasured."""
        return 0

    def close(self) -> None:
        """Close every handle."""
        with self._close_lock:
            self._close_open()

    def _close_open(self) -> None:
        """Close the connected handles (under the close lock)."""
        raise NotImplementedError


class RfcommLink(Link):
    """A Bluetooth socket's link: the socket inside connect() is published, so stop() can close it mid-connect."""

    def __init__(self, address: str, name: str, stop: threading.Event) -> None:
        super().__init__(address, name, stop)
        self._pending = None  # the socket inside connect()
        self._socket = None  # the connected one

    def close(self) -> None:
        """Close every handle, a connect in flight included."""
        with self._close_lock:
            pending, self._pending = self._pending, None
            if pending is not None:
                _shutdown_before_close(pending)
                try:
                    pending.close()
                    logger.info("Aborted in-flight RFCOMM connect")
                except Exception as e:
                    logger.debug(f"closing in-flight RFCOMM socket: {e}")
            self._close_open()

    def _connect_abortable(self, sock, connect: Callable[[], None]) -> None:
        """Connect `sock`, published first: stop() then either closes it mid-connect or the check below sees the stop.
        A failed socket is closed (left open, it keeps the headset's only channel reserved); a failure during a stop is
        ConnectAborted."""
        self._pending = sock
        try:
            if self._stop.is_set():
                raise ConnectAborted
            connect()
        except Exception as e:
            self._pending = None
            _close_quietly(sock, "failed")
            if self._stop.is_set() and not isinstance(e, ConnectAborted):
                raise ConnectAborted from e
            raise
        self._pending = None


def _shutdown_before_close(sock) -> None:
    """Wake a thread blocked in connect()/recv() — on Linux a cross-thread close() alone doesn't."""
    # Python and PyBluez sockets have shutdown(); Android's Java socket doesn't (close() aborts it).
    try:
        shutdown = getattr(sock, "shutdown", None)
        if shutdown is not None:
            shutdown(_socket.SHUT_RDWR)
    except Exception as e:
        logger.debug(f"shutdown before close: {e}")


def _close_quietly(sock, label: str) -> None:
    try:
        sock.close()
    except Exception as e:
        logger.debug(f"closing {label} socket: {e}")


def request_bt_permissions() -> None:
    """Request Bluetooth runtime permissions on Android 6+."""
    try:
        from jnius import autoclass  # noqa: PLC0415 - Android only (pyjnius)
    except ImportError:
        return

    try:
        activity = android_jni.activity()
        PackageManager = autoclass("android.content.pm.PackageManager")
        Build_VERSION = autoclass("android.os.Build$VERSION")

        permissions_needed = [
            "android.permission.BLUETOOTH",
            "android.permission.BLUETOOTH_ADMIN",
            "android.permission.ACCESS_FINE_LOCATION",
        ]
        # Android 12+ (API 31+) requires new BT permissions
        if Build_VERSION.SDK_INT >= 31:
            permissions_needed.extend([
                "android.permission.BLUETOOTH_CONNECT",
                "android.permission.BLUETOOTH_SCAN",
            ])

        missing = []
        for perm in permissions_needed:
            if activity.checkSelfPermission(perm) != PackageManager.PERMISSION_GRANTED:
                missing.append(perm)

        if missing:
            logger.info(f"Requesting BT permissions: {missing}")
            activity.requestPermissions(missing, 1)
            # Brief wait for user to respond to dialog
            time.sleep(2.0)
        else:
            logger.debug("All BT permissions already granted")
    except Exception as e:
        logger.warning(f"Permission request failed: {e}")


class AndroidRfcomm(RfcommLink):
    """RFCOMM through Android's Bluetooth API (pyjnius): secure, then insecure, then channel 1."""

    _numbers = itertools.count(1)  # each connected socket's number in the log, across links

    def __init__(self, address: str, name: str, stop: threading.Event) -> None:
        super().__init__(address, name, stop)
        self._input = None  # its Java InputStream
        self._number = 0
        self._high_water = 0

    def connect(self) -> None:
        try:
            from jnius import autoclass  # noqa: PLC0415 - Android only (pyjnius)
        except ImportError:
            raise RuntimeError(
                "pyjnius not available — real device connection requires Android"
            )

        request_bt_permissions()

        BluetoothAdapter = autoclass("android.bluetooth.BluetoothAdapter")
        UUID = autoclass("java.util.UUID")

        adapter = BluetoothAdapter.getDefaultAdapter()
        if adapter is None:
            raise RuntimeError("No Bluetooth adapter found")
        if not adapter.isEnabled():
            raise RuntimeError("Bluetooth is not enabled")

        device = adapter.getRemoteDevice(self._address)
        uuid = UUID.fromString(NEUROSKY_SPP_UUID)

        logger.info(f"Connecting to {self._name} ({self._address})...")
        try:
            adapter.cancelDiscovery()
        except Exception as e:
            logger.warning(f"cancelDiscovery failed (non-fatal): {e}")

        # createRfcommSocket(1) directly: via Class.getMethod() pyjnius can't resolve the varargs overload.
        self._connect_first([
            ("secure", lambda: device.createRfcommSocketToServiceRecord(uuid)),
            ("insecure", lambda: device.createInsecureRfcommSocketToServiceRecord(uuid)),
            ("reflection ch=1", lambda: device.createRfcommSocket(1)),
        ])

    def _connect_first(self, attempts: list[tuple[str, Callable[[], Any]]]) -> None:
        """Adopt the first RFCOMM socket that connects; stop() can abort the one in flight."""
        errors: list[str] = []
        for label, make_socket in attempts:
            try:
                sock = make_socket()
                self._connect_abortable(sock, sock.connect)
            except ConnectAborted:
                raise
            except Exception as e:
                errors.append(f"{label}: {e}")
                logger.warning(f"{label.capitalize()} RFCOMM failed: {e}")
                continue
            self._adopt(sock, label)
            return
        raise RuntimeError(f"All RFCOMM methods failed: {'; '.join(errors)}")

    def _adopt(self, socket, how: str) -> None:
        """Take ownership of a connected RFCOMM socket."""
        self._number = next(self._numbers)
        self._socket = socket
        self._input = socket.getInputStream()
        logger.info(f"RFCOMM socket #{self._number} connected ({how})")

    def read(self, max_bytes: int) -> bytes:
        """One JNI read per chunk (byte-at-a-time was ~4000 calls/s); the buffer is sized exactly — pyjnius copies it both ways."""
        stream = self._input
        if stream is None:
            return b""
        try:
            available = stream.available()
            if available <= 0:
                # Block for one byte (pyjnius releases the GIL), then drain what arrived with it.
                first = stream.read()
                if first < 0:
                    return b""
                head = bytes([first & 0xFF])
                available = stream.available()
                if available <= 0:
                    return head
                max_bytes -= 1
            else:
                head = b""
            to_read = min(available, max_bytes)
            self._high_water = max(self._high_water, available)
            buf = bytearray(to_read)
            n = stream.read(buf, 0, to_read)
            if n <= 0:
                return head
            return head + bytes(buf[:n])
        except Exception as e:
            logger.debug(f"Android RFCOMM read error: {e}")
            raise

    def take_high_water(self) -> int:
        high, self._high_water = self._high_water, 0
        return high

    def _close_open(self) -> None:
        self._input = None
        sock, self._socket = self._socket, None
        if sock is not None:
            try:
                sock.close()
                logger.info(f"RFCOMM socket #{self._number} closed")
            except Exception as e:
                logger.debug(f"closing RFCOMM socket: {e}")

    @staticmethod
    def scan_paired() -> list[dict[str, str]]:
        """Scan paired devices via Android Bluetooth API."""
        try:
            from jnius import autoclass  # noqa: PLC0415 - Android only (pyjnius)
        except ImportError:
            logger.debug("pyjnius not available, scan returning empty")
            return []

        try:
            request_bt_permissions()

            BluetoothAdapter = autoclass("android.bluetooth.BluetoothAdapter")
            adapter = BluetoothAdapter.getDefaultAdapter()
            if adapter is None or not adapter.isEnabled():
                return []
            paired = adapter.getBondedDevices()
            devices: list[dict[str, str]] = []
            iterator = paired.iterator()
            while iterator.hasNext():
                device = iterator.next()
                devices.append({
                    "name": device.getName() or "Unknown",
                    "address": device.getAddress(),
                })
            logger.info(f"Found {len(devices)} paired BT devices")
            return devices
        except Exception as e:
            logger.error(f"BT scan error (Android): {e}")
            return []


class LinuxRfcomm(RfcommLink):
    """RFCOMM channel 1 through a Python socket (AF_BLUETOOTH), or PyBluez where Python was built without it (common in
    PyInstaller bundles built without libbluetooth-dev headers)."""

    def connect(self) -> None:
        logger.info(f"Connecting to {self._name} ({self._address}) via desktop RFCOMM...")
        if hasattr(_socket, "AF_BLUETOOTH"):
            self._connect_native()
        else:
            self._connect_pybluez()

    def _connect_native(self) -> None:
        BTPROTO_RFCOMM = 3
        last_err = None
        # Retry loop: BlueZ may hold the RFCOMM channel as EBUSY for a
        # few seconds after a previous connection attempt timed out.
        for attempt in range(4):
            sock = _socket.socket(_socket.AF_BLUETOOTH, _socket.SOCK_STREAM, BTPROTO_RFCOMM)
            # Blocking + timeout so EINPROGRESS is handled internally.
            sock.settimeout(30.0)
            try:
                self._connect_abortable(sock, lambda s=sock: s.connect((self._address, 1)))  # channel 1 for SPP
            except OSError as e:
                last_err = e
                if e.errno == errno.EBUSY and attempt < 3:
                    logger.info(f"RFCOMM busy, waiting 5s (attempt {attempt + 1}/4)")
                    # Just wait — bluetoothctl disconnect makes it worse
                    # by killing the ACL link and sending the headset dark.
                    if self._stop.wait(5.0):
                        raise ConnectAborted from e
                    continue
                break
            sock.settimeout(5.0)  # read timeout after connected
            self._socket = sock
            logger.info("Desktop RFCOMM socket connected (native)")
            return
        raise RuntimeError(f"Desktop RFCOMM connect failed: {last_err}")

    def _connect_pybluez(self) -> None:
        try:
            import bluetooth  # noqa: PLC0415 - PyBluez: Linux desktop only
        except ImportError:
            raise RuntimeError(
                "Desktop RFCOMM connect failed: module 'socket' has no attribute "
                "'AF_BLUETOOTH' and PyBluez is not installed. "
                "Install PyBluez: pip install pybluez"
            )

        try:
            sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            sock.settimeout(30.0)
            self._connect_abortable(sock, lambda: sock.connect((self._address, 1)))
        except ConnectAborted:
            raise
        except Exception as e:
            raise RuntimeError(f"Desktop RFCOMM connect failed (PyBluez): {e}") from e
        sock.settimeout(5.0)  # read timeout after connected
        self._socket = sock
        logger.info("Desktop RFCOMM socket connected (PyBluez)")

    def read(self, max_bytes: int) -> bytes:
        if self._socket is None or self._stop.is_set():
            return b""
        try:
            return self._socket.recv(max_bytes)
        except _socket.timeout:
            return b""
        except Exception as e:
            if not self._stop.is_set():
                logger.debug(f"Desktop RFCOMM read error: {e}")
            raise

    def _close_open(self) -> None:
        sock, self._socket = self._socket, None
        if sock is not None:
            _shutdown_before_close(sock)
            _close_quietly(sock, "desktop")

    @staticmethod
    def scan_paired() -> list[dict[str, str]]:
        """Scan paired devices via bluetoothctl on Linux desktop."""
        commands = [
            ["bluetoothctl", "paired-devices"],
            ["bluetoothctl", "devices", "Paired"],
        ]
        for cmd in commands:
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=5
                )
                if result.returncode != 0:
                    continue
                devices: list[dict[str, str]] = []
                for line in result.stdout.strip().splitlines():
                    # Format: "Device XX:XX:XX:XX:XX:XX DeviceName"
                    parts = line.strip().split(" ", 2)
                    if len(parts) >= 3 and parts[0] == "Device":
                        devices.append({
                            "address": parts[1],
                            "name": parts[2],
                        })
                logger.info(f"Found {len(devices)} paired BT devices (desktop)")
                return devices
            except FileNotFoundError:
                logger.warning("bluetoothctl not found")
                return []
            except Exception as e:
                logger.debug(f"BT scan cmd {cmd} failed: {e}")
                continue
        logger.error("All bluetoothctl scan methods failed")
        return []


class WindowsSerial(Link):
    """The virtual COM port Windows pairs the MindWave as (SPP), through pyserial. The address is a COM port name
    ("COM5") or a Bluetooth MAC address, resolved to its COM port."""

    def __init__(self, address: str, name: str, stop: threading.Event) -> None:
        super().__init__(address, name, stop)
        self._serial = None

    def connect(self) -> None:
        try:
            import serial  # noqa: PLC0415 - pyserial: desktop serial devices only
        except ImportError:
            raise RuntimeError(
                "pyserial is required for Windows Bluetooth. Install it: pip install pyserial"
            )

        port = self._address
        # If address looks like a MAC, resolve it to a COM port
        if port and ":" in port:
            resolved = self._find_com_port_for_mac(port)
            if resolved:
                port = resolved
                logger.info(f"Resolved MAC {self._address} to {port}")
            else:
                raise RuntimeError(
                    f"Could not find COM port for device {self._address}. "
                    "Pair the device in Windows Bluetooth settings and check Device Manager for the COM port."
                )

        logger.info(f"Connecting to {self._name} via {port}...")
        try:
            self._serial = serial.Serial(port=port, baudrate=57600, timeout=5.0)
            logger.info(f"Windows serial port connected: {port}")
        except Exception as e:
            raise RuntimeError(f"Windows serial connect failed ({port}): {e}")

    @staticmethod
    def _find_com_port_for_mac(mac_address: str) -> str | None:
        """Search Windows registry for COM port associated with a BT MAC address."""
        try:
            import winreg  # noqa: PLC0415 - Windows only
            # Normalize MAC: remove colons for registry lookup
            mac_clean = mac_address.replace(":", "").replace("-", "").upper()
            # BT COM ports are under HKLM\SYSTEM\CurrentControlSet\Enum\BTHENUM
            key_path = r"SYSTEM\CurrentControlSet\Enum\BTHENUM"
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
            except FileNotFoundError:
                return None
            # Walk subkeys looking for our MAC and an associated COM port
            import serial.tools.list_ports as list_ports  # noqa: PLC0415 - pyserial: desktop serial devices only
            for port_info in list_ports.comports():
                if port_info.hwid and mac_clean in port_info.hwid.upper():
                    winreg.CloseKey(key)
                    return port_info.device
            winreg.CloseKey(key)
        except Exception as e:
            logger.debug(f"COM port registry lookup failed: {e}")
        return None

    def read(self, max_bytes: int) -> bytes:
        if self._serial is None:
            return b""
        try:
            waiting = self._serial.in_waiting
            if waiting > 0:
                return self._serial.read(min(waiting, max_bytes))
            return self._serial.read(1)
        except Exception as e:
            logger.debug(f"Windows serial read error: {e}")
            raise

    def _close_open(self) -> None:
        port, self._serial = self._serial, None
        if port is not None:
            try:
                port.close()
            except Exception as e:
                logger.debug(f"closing serial port: {e}")

    @staticmethod
    def scan_paired() -> list[dict[str, str]]:
        """Scan for Bluetooth serial (COM) ports on Windows.

        Lists COM ports that are associated with Bluetooth devices.
        Falls back to listing all available COM ports if BT filtering fails.
        """
        try:
            import serial.tools.list_ports as list_ports  # noqa: PLC0415 - pyserial: desktop serial devices only
        except ImportError:
            logger.warning("pyserial not installed — cannot scan COM ports")
            return []

        try:
            devices: list[dict[str, str]] = []
            for port_info in list_ports.comports():
                # Filter for Bluetooth COM ports (BTHENUM in hardware ID)
                hwid = (port_info.hwid or "").upper()
                is_bt = "BTHENUM" in hwid or "BLUETOOTH" in hwid
                if is_bt:
                    name = port_info.description or port_info.device
                    devices.append({
                        "address": port_info.device,  # e.g. "COM5"
                        "name": f"{name} ({port_info.device})",
                    })
            if not devices:
                # Fallback: show all COM ports so user can pick manually
                for port_info in list_ports.comports():
                    name = port_info.description or port_info.device
                    devices.append({
                        "address": port_info.device,
                        "name": f"{name} ({port_info.device})",
                    })
            logger.info(f"Found {len(devices)} COM ports (Windows)")
            return devices
        except Exception as e:
            logger.error(f"COM port scan error (Windows): {e}")
            return []


class SerialDevice(Link):
    """A serial device path (e.g. /tmp/mindwave_b from mindwave-splitter), read through its file descriptor."""

    def __init__(self, address: str, name: str, stop: threading.Event) -> None:
        super().__init__(address, name, stop)
        self._fd: int | None = None

    def connect(self) -> None:
        logger.info(f"Connecting to serial device {self._address}...")
        try:
            self._fd = os.open(self._address, os.O_RDONLY | os.O_NOCTTY)
            logger.info(f"Serial device connected: {self._address}")
        except Exception as e:
            raise RuntimeError(f"Serial device connect failed: {e}")

    def read(self, max_bytes: int) -> bytes:
        fd = self._fd
        if fd is None:
            return b""
        try:
            # Poll: a cross-thread os.close() doesn't wake a blocked os.read().
            if not select.select([fd], [], [], 0.5)[0]:
                return b""
            return os.read(fd, max_bytes)
        except BlockingIOError:
            return b""
        except Exception as e:
            logger.debug(f"Serial device read error: {e}")
            raise

    def _close_open(self) -> None:
        fd, self._fd = self._fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError as e:
                logger.debug(f"closing serial fd: {e}")


def _platform_link() -> type[AndroidRfcomm | LinuxRfcomm | WindowsSerial]:
    """The platform's Bluetooth link: the one place the platform is told apart."""
    if android_jni.on_android():
        return AndroidRfcomm
    if _IS_WINDOWS:
        return WindowsSerial
    return LinuxRfcomm


def link_for(address: str, name: str, stop: threading.Event) -> Link:
    """The link to `address`: a serial device path (it starts with "/"), else the platform's Bluetooth link."""
    link = SerialDevice if address.startswith("/") else _platform_link()
    return link(address, name, stop)


def scan_paired() -> list[dict[str, str]]:
    """The paired Bluetooth devices the platform knows ([{'name': ..., 'address': ...}])."""
    return _platform_link().scan_paired()
