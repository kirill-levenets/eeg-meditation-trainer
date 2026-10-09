"""NeuroSky MindWave Mobile 2 stream driver.

Connects via Bluetooth Classic RFCOMM:
- Android: pyjnius wrapping Java BluetoothSocket API
- Desktop Linux: Python socket module with BTPROTO_RFCOMM
- Windows: pyserial over virtual COM port (NeuroSky SPP profile)

Parses ThinkGear serial protocol packets to extract:
- 8 EEG band powers (ASIC_EEG_POWER_INT, code 0x83)
- Attention (code 0x04) and Meditation (code 0x05) eSense values
- Signal quality (code 0x02)
- Raw wave (code 0x80, 512Hz signed 16-bit)
"""
import select
import socket as _socket
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any, Optional

from app.eeg.band_spec import BAND_KEYS
from app.logger import logger

_IS_ANDROID: bool = hasattr(sys, "getandroidapilevel")
_IS_WINDOWS: bool = sys.platform == "win32"

THINKGEAR_SYNC = 0xAA
THINKGEAR_EXCODE = 0x55

CODE_BATTERY = 0x01
CODE_POOR_SIGNAL = 0x02
CODE_ATTENTION = 0x04
CODE_MEDITATION = 0x05
CODE_RAW_WAVE = 0x80
CODE_EEG_POWER_FLOAT = 0x81
CODE_ASIC_EEG_POWER = 0x83

BAND_NAMES = BAND_KEYS  # the order ASIC_EEG_POWER sends them

NEUROSKY_SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"


class ThinkGearParser:
    """Stateful parser for ThinkGear serial protocol packets."""

    def __init__(self) -> None:
        self._buffer: bytearray = bytearray()

    def feed(self, data: bytes) -> list[dict]:
        """Feed raw bytes, return list of parsed complete packets."""
        self._buffer.extend(data)
        results: list[dict] = []
        while self._buffer:
            prev_len = len(self._buffer)
            packet = self._try_parse_packet()
            if packet is not None:
                results.append(packet)
                continue
            if len(self._buffer) == prev_len:
                break
        return results

    def _try_parse_packet(self) -> Optional[dict]:
        """Try to extract one complete ThinkGear packet from buffer."""
        # Find sync bytes 0xAA 0xAA
        while len(self._buffer) >= 2:
            if self._buffer[0] == THINKGEAR_SYNC and self._buffer[1] == THINKGEAR_SYNC:
                break
            self._buffer.pop(0)

        if len(self._buffer) < 4:
            return None

        plength = self._buffer[2]
        if plength > 169:
            self._buffer = self._buffer[3:]
            return None

        total_len = 3 + plength + 1  # header(3) + payload + checksum(1)
        if len(self._buffer) < total_len:
            return None

        payload = self._buffer[3:3 + plength]
        checksum_byte = self._buffer[3 + plength]

        # Verify checksum
        computed = (~sum(payload)) & 0xFF
        if computed != checksum_byte:
            logger.debug(f"ThinkGear checksum mismatch: expected {computed}, got {checksum_byte}")
            self._buffer = self._buffer[2:]
            return None

        # Consume the packet
        self._buffer = self._buffer[total_len:]
        return self._parse_payload(bytes(payload))

    def _parse_payload(self, payload: bytes) -> dict:
        """Parse DataRows from a valid payload."""
        result: dict = {}
        i = 0
        while i < len(payload):
            # Skip EXCODE bytes
            while i < len(payload) and payload[i] == THINKGEAR_EXCODE:
                i += 1
            if i >= len(payload):
                break

            code = payload[i]
            i += 1

            if code < 0x80:
                # Single-byte value codes
                if i >= len(payload):
                    break
                value = payload[i]
                i += 1
                if code == CODE_BATTERY:
                    result["battery"] = value  # 0-127, ~3V scale
                elif code == CODE_POOR_SIGNAL:
                    result["signal_quality"] = value
                elif code == CODE_ATTENTION:
                    result["attention"] = float(value)
                elif code == CODE_MEDITATION:
                    result["meditation"] = float(value)
            else:
                # Multi-byte value codes
                if i >= len(payload):
                    break
                vlength = payload[i]
                i += 1
                if i + vlength > len(payload):
                    break
                vdata = payload[i:i + vlength]
                i += vlength

                if code == CODE_RAW_WAVE and vlength == 2:
                    raw = (vdata[0] << 8) | vdata[1]
                    if raw >= 32768:
                        raw -= 65536
                    result["raw_wave"] = raw

                elif code == CODE_ASIC_EEG_POWER and vlength == 24:
                    bands = {}
                    for bi, name in enumerate(BAND_NAMES):
                        offset = bi * 3
                        val = (vdata[offset] << 16) | (vdata[offset + 1] << 8) | vdata[offset + 2]
                        bands[name] = float(val)
                    result["bands"] = bands

                elif code == CODE_EEG_POWER_FLOAT and vlength == 32:
                    bands = {}
                    for bi, name in enumerate(BAND_NAMES):
                        offset = bi * 4
                        val = struct.unpack(">f", vdata[offset:offset + 4])[0]
                        bands[name] = float(val)
                    result["bands"] = bands

        return result


class NeuroSkyStream:
    """Bluetooth RFCOMM stream to NeuroSky MindWave Mobile 2.

    Interface matches MockEEGStream: start(), stop(), is_connected, read_sample().
    Uses pyjnius on Android, Python socket on desktop Linux.
    """

    _STOP_JOIN_TIMEOUT: float = 5.0

    def __init__(self) -> None:
        self._running: bool = False
        self._connected: bool = False
        self._start_time: float = 0.0
        self._sample_count: int = 0
        self._parser: ThinkGearParser = ThinkGearParser()
        self._thread: Optional[threading.Thread] = None
        self._lock: threading.Lock = threading.Lock()
        self._device_address: Optional[str] = None
        self._device_name: Optional[str] = None

        # Latest consolidated sample (updated by reader thread)
        self._latest_bands: dict[str, float] = dict.fromkeys(BAND_NAMES, 0.0)
        self._latest_attention: float = 0.0
        self._latest_meditation: float = 0.0
        self._latest_signal_quality: int = 200
        self._raw_wave_buffer: list[int] = []
        self._last_packet_time: float = 0.0  # monotonic time of last parsed packet
        self._last_connect_error: str = ""  # human-readable error from last failed connect
        self._battery_level: int = -1  # 0-127 from ThinkGear, -1 = unknown

        # Bluetooth objects (set during connect)
        self._bt_socket = None
        self._bt_input_stream = None  # Android only (Java InputStream)
        self._desktop_socket: Optional[_socket.socket] = None  # Desktop only
        self._windows_serial = None  # Windows only (pyserial Serial object)
        self._serial_fd: Optional[int] = None  # Serial device mode (splitter)
        self._read_count: int = 0
        # Backlog telemetry: a rising high-water mark means the reader is losing to the stream.
        self._avail_high_water: int = 0
        self._bytes_read: int = 0
        self._rate_window_start: float = 0.0
        # Connect generation: a reader that outlives its stop() closes its socket, never adopts it.
        self._connect_epoch: int = 0
        self._socket_seq: int = 0
        # Socket inside connect(); stop() closes it to abort the connect.
        self._pending_socket = None
        # Set by stop() so the reader's back-off sleeps end immediately.
        self._stop_event = threading.Event()
        self._close_lock = threading.Lock()

    def set_device(self, address: str, name: str = "") -> None:
        """Set the target Bluetooth device address; a link to another one closes, so the next start reaches this one."""
        if self._running and address != self._device_address:
            self.stop()
        self._device_address = address
        self._device_name = name or address
        logger.info(f"NeuroSky device set: {self._device_name} ({address})")

    def start(self) -> bool:
        """Start the reader thread; False (with _last_connect_error set) if it was refused."""
        if self._running:
            return True
        if self._thread is not None and self._thread.is_alive():
            # A second reader would race the closing one for the headset's only channel.
            logger.warning("NeuroSky start ignored: previous reader thread still alive")
            self._last_connect_error = "Previous connection is still closing.\nRetry in a few seconds."
            return False
        if not self._device_address:
            logger.warning("NeuroSky start failed: no device address set")
            self._last_connect_error = "No device selected.\nPick one in Settings > Device."
            return False
        self._stop_event.clear()
        self._running = True
        self._start_time = time.time()
        self._sample_count = 0
        self._parser = ThinkGearParser()
        # Reset sample state so stale data from a previous session
        # doesn't trick the signal-wait check into thinking data is flowing.
        self._latest_bands = dict.fromkeys(BAND_NAMES, 0.0)
        self._latest_attention = 0.0
        self._latest_meditation = 0.0
        self._latest_signal_quality = 200
        self._raw_wave_buffer.clear()
        self._last_packet_time = 0.0
        self._connect_epoch += 1
        self._thread = threading.Thread(
            target=self._read_loop, args=(self._connect_epoch,), daemon=True
        )
        self._thread.start()
        logger.info(f"NeuroSky stream started (epoch {self._connect_epoch})")
        return True

    def stop(self) -> None:
        """Stop the reader thread and close the socket."""
        self._running = False
        self._connected = False
        self._stop_event.set()
        # Close before the join so the reader's blocked connect()/read() aborts (see _close_socket).
        self._connect_epoch += 1
        self._close_socket()
        # Local copy: the tick thread and the main thread can both be in stop().
        t = self._thread
        if t is not None:
            t.join(timeout=self._STOP_JOIN_TIMEOUT)
            if t.is_alive():
                # Keep the reference: start() must refuse until this reader exits.
                logger.warning(
                    f"NeuroSky reader thread did not exit within {self._STOP_JOIN_TIMEOUT:.0f}s"
                )
            elif self._thread is t:
                self._thread = None
        self._close_socket()
        logger.info("NeuroSky stream stopped")

    def reset_sample_state(self) -> None:
        """Clear cached sample data between sessions (connection stays alive)."""
        with self._lock:
            self._latest_bands = dict.fromkeys(BAND_NAMES, 0.0)
            self._latest_attention = 0.0
            self._latest_meditation = 0.0
            self._latest_signal_quality = 200
            self._raw_wave_buffer.clear()
            self._last_packet_time = 0.0
            self._sample_count = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def seconds_since_last_packet(self) -> float:
        """Seconds elapsed since last parsed EEG packet (monotonic)."""
        if self._last_packet_time == 0.0:
            return 0.0
        return time.monotonic() - self._last_packet_time

    def read_sample(self) -> dict:
        """Return the latest consolidated EEG sample.

        Returns a dict matching MockEEGStream format:
        delta, theta, alpha1, alpha2, beta1, beta2, gamma1, gamma2,
        attention, meditation, timestamp, signal_quality
        """
        with self._lock:
            sample: dict = {}
            sample["timestamp"] = time.time() - self._start_time
            for name in BAND_NAMES:
                sample[name] = self._latest_bands.get(name, 0.0)
            sample["attention"] = self._latest_attention
            sample["meditation"] = self._latest_meditation
            sample["signal_quality"] = self._latest_signal_quality
            sample["battery"] = self._battery_level
            # Drain raw wave buffer for waveform graph
            if self._raw_wave_buffer:
                sample["raw_eeg_waveform"] = list(self._raw_wave_buffer)
                self._raw_wave_buffer.clear()
            self._sample_count += 1
            return sample

    def _read_loop(self, epoch: int) -> None:
        """Reader thread for connect generation `epoch`; once superseded it closes its socket, never adopts it."""
        try:
            self._connect_bluetooth()
        except Exception as e:
            if epoch != self._connect_epoch:
                logger.info(f"NeuroSky connect aborted (epoch {epoch} superseded)")
                self._close_socket()
                return
            logger.error(f"NeuroSky BT connect failed: {e}")
            err = str(e)
            if "Host is down" in err:
                self._last_connect_error = "Headset is asleep or off.\nTurn it on and retry."
            elif "Device or resource busy" in err:
                self._last_connect_error = "Bluetooth busy.\nWait 15 seconds and retry."
            elif "timed out" in err.lower():
                self._last_connect_error = "Connection timed out.\nCheck headset is on and in range."
            else:
                self._last_connect_error = "Check headset is on and paired."
            self._running = False
            self._connected = False
            return

        if epoch != self._connect_epoch or not self._running:
            logger.warning(
                f"NeuroSky connect superseded (epoch {epoch} != {self._connect_epoch}); "
                "closing the orphaned socket"
            )
            self._close_socket()
            return

        self._last_connect_error = ""
        self._connected = True
        logger.info("NeuroSky BT connected, reading packets...")
        self._read_count = 0
        self._bytes_read = 0
        self._avail_high_water = 0
        self._rate_window_start = time.monotonic()
        self._boost_thread_priority()
        first_read_logged = False

        while self._running and epoch == self._connect_epoch:
            try:
                data = self._read_bytes(512)
                if not data:
                    time.sleep(0.01)
                    continue
                if not first_read_logged:
                    logger.debug(f"BT first read: {len(data)} bytes")
                    first_read_logged = True
                self._read_count += 1
                self._bytes_read += len(data)
                self._log_throughput()
                packets = self._parser.feed(data)
                for pkt in packets:
                    self._apply_packet(pkt)
            except Exception as e:
                if not self._running or epoch != self._connect_epoch:
                    break  # socket closed by stop(), not a real error
                logger.error(f"NeuroSky read error: {e}")
                self._connected = False
                self._stop_event.wait(2.0)
                if self._running and epoch == self._connect_epoch:
                    try:
                        self._close_socket()
                        self._connect_bluetooth()
                        if epoch != self._connect_epoch:
                            self._close_socket()
                            break
                        self._connected = True
                        logger.info("NeuroSky reconnected")
                    except Exception as re:
                        if epoch != self._connect_epoch:
                            break
                        logger.error(f"NeuroSky reconnect failed: {re}")
                        self._running = False
        self._close_socket()
        # Also covers a stop() that landed between the epoch check and `_connected = True`.
        self._connected = False

    @staticmethod
    def _boost_thread_priority() -> None:
        """Run the reader at Android priority -8, like the NeuroSky SDK's, so Kivy's renderer can't starve it."""
        if not _IS_ANDROID:
            return
        try:
            from jnius import autoclass
            autoclass("android.os.Process").setThreadPriority(-8)
        except Exception as e:
            logger.debug(f"Thread priority boost skipped: {e}")

    def _log_throughput(self) -> None:
        """Log read throughput and the RFCOMM backlog high-water mark."""
        now = time.monotonic()
        window = now - self._rate_window_start
        if window < 30.0:
            return
        logger.info(
            f"BT throughput: {self._bytes_read / window:.0f} B/s, "
            f"{self._bytes_read / max(1, self._read_count):.0f} B/read, "
            f"backlog high-water {self._avail_high_water} B"
        )
        self._rate_window_start = now
        self._bytes_read = 0
        self._read_count = 0
        self._avail_high_water = 0

    def _apply_packet(self, pkt: dict) -> None:
        """Update internal state from a parsed packet."""
        with self._lock:
            if "bands" in pkt:
                self._latest_bands.update(pkt["bands"])
            if "attention" in pkt:
                self._latest_attention = pkt["attention"]
            if "meditation" in pkt:
                self._latest_meditation = pkt["meditation"]
            if "signal_quality" in pkt:
                self._latest_signal_quality = pkt["signal_quality"]
            if "battery" in pkt:
                self._battery_level = pkt["battery"]
            self._last_packet_time = time.monotonic()
            if "raw_wave" in pkt:
                self._raw_wave_buffer.append(pkt["raw_wave"])
                if len(self._raw_wave_buffer) > 1024:
                    self._raw_wave_buffer = self._raw_wave_buffer[-1024:]

    @staticmethod
    def _request_bt_permissions() -> None:
        """Request Bluetooth runtime permissions on Android 6+."""
        try:
            from jnius import autoclass
        except ImportError:
            return

        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
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

    @property
    def _is_serial_device(self) -> bool:
        """True if address is a serial device path (e.g. /tmp/mindwave_b from splitter)."""
        return bool(self._device_address and self._device_address.startswith("/"))

    def _connect_bluetooth(self) -> None:
        """Open RFCOMM socket to the MindWave (or serial device from splitter)."""
        if self._is_serial_device:
            self._connect_serial()
        elif _IS_ANDROID:
            self._connect_android()
        elif _IS_WINDOWS:
            self._connect_windows()
        else:
            self._connect_desktop()

    # ---- Android backend ----

    def _adopt_socket(self, socket, how: str) -> None:
        """Take ownership of a connected Android RFCOMM socket."""
        self._socket_seq += 1
        self._bt_socket = socket
        self._bt_input_stream = socket.getInputStream()
        logger.info(f"RFCOMM socket #{self._socket_seq} connected ({how})")

    def _connect_android(self) -> None:
        """Open RFCOMM socket via Android Bluetooth API (pyjnius)."""
        try:
            from jnius import autoclass
        except ImportError:
            raise RuntimeError(
                "pyjnius not available — real device connection requires Android"
            )

        self._request_bt_permissions()

        BluetoothAdapter = autoclass("android.bluetooth.BluetoothAdapter")
        UUID = autoclass("java.util.UUID")

        adapter = BluetoothAdapter.getDefaultAdapter()
        if adapter is None:
            raise RuntimeError("No Bluetooth adapter found")
        if not adapter.isEnabled():
            raise RuntimeError("Bluetooth is not enabled")

        device = adapter.getRemoteDevice(self._device_address)
        uuid = UUID.fromString(NEUROSKY_SPP_UUID)

        logger.info(f"Connecting to {self._device_name} ({self._device_address})...")
        try:
            adapter.cancelDiscovery()
        except Exception as e:
            logger.warning(f"cancelDiscovery failed (non-fatal): {e}")

        # createRfcommSocket(1) directly: via Class.getMethod() pyjnius can't resolve the varargs overload.
        self._run_connect_attempts([
            ("secure", lambda: device.createRfcommSocketToServiceRecord(uuid)),
            ("insecure", lambda: device.createInsecureRfcommSocketToServiceRecord(uuid)),
            ("reflection ch=1", lambda: device.createRfcommSocket(1)),
        ])

    def _run_connect_attempts(self, attempts: list[tuple[str, Callable[[], Any]]]) -> None:
        """Adopt the first RFCOMM socket that connects; stop() can abort the one in flight."""
        errors: list[str] = []
        for label, make_socket in attempts:
            sock = None
            try:
                sock = make_socket()
                # Publish before checking _running: stop() then either closes it or we see the stop.
                self._pending_socket = sock
                if not self._running:
                    raise RuntimeError("connect aborted by stop()")
                sock.connect()
            except Exception as e:
                self._pending_socket = None
                # An unclosed failed socket keeps the headset's only channel reserved.
                if sock is not None:
                    try:
                        sock.close()
                    except Exception as ce:
                        logger.debug(f"closing failed {label} socket: {ce}")
                if not self._running:
                    raise RuntimeError("connect aborted by stop()") from e
                errors.append(f"{label}: {e}")
                logger.warning(f"{label.capitalize()} RFCOMM failed: {e}")
                continue
            self._pending_socket = None
            self._adopt_socket(sock, label)
            return
        raise RuntimeError(f"All RFCOMM methods failed: {'; '.join(errors)}")

    # ---- Serial device backend (splitter) ----

    def _connect_serial(self) -> None:
        """Open a serial device path (e.g. /tmp/mindwave_b from splitter)."""
        import os as _os
        path = self._device_address
        logger.info(f"Connecting to serial device {path}...")
        try:
            fd = _os.open(path, _os.O_RDONLY | _os.O_NOCTTY)
            self._serial_fd = fd
            logger.info(f"Serial device connected: {path}")
        except Exception as e:
            raise RuntimeError(f"Serial device connect failed: {e}")

    # ---- Desktop Linux backend ----

    @staticmethod
    def _bluez_disconnect(address: str) -> None:
        """Ask BlueZ to drop any existing connection to this device.

        Clears stale RFCOMM state that causes EBUSY / silent connection
        failures even after the headset has been power-cycled.
        """
        try:
            result = subprocess.run(
                ["bluetoothctl", "disconnect", address],
                capture_output=True, text=True, timeout=5,
            )
            out = (result.stdout + result.stderr).strip()
            if out:
                logger.info(f"bluetoothctl disconnect: {out}")
        except Exception as e:
            logger.debug(f"bluetoothctl disconnect skipped: {e}")

    def _connect_desktop(self) -> None:
        """Open RFCOMM socket via Python socket module (Linux desktop).

        Falls back to PyBluez if the Python build lacks socket.AF_BLUETOOTH
        (common in PyInstaller bundles built without libbluetooth-dev headers).
        """
        logger.info(f"Connecting to {self._device_name} ({self._device_address}) via desktop RFCOMM...")

        # Try native socket.AF_BLUETOOTH first (available when Python was
        # compiled with libbluetooth-dev headers)
        if hasattr(_socket, "AF_BLUETOOTH"):
            BTPROTO_RFCOMM = 3
            last_err = None
            # Retry loop: BlueZ may hold the RFCOMM channel as EBUSY for a
            # few seconds after a previous connection attempt timed out.
            for attempt in range(4):
                try:
                    sock = _socket.socket(
                        _socket.AF_BLUETOOTH, _socket.SOCK_STREAM, BTPROTO_RFCOMM
                    )
                    # Blocking + timeout so EINPROGRESS is handled internally.
                    sock.settimeout(30.0)
                    # Publish before the check, as in _run_connect_attempts.
                    self._pending_socket = sock
                    if not self._running:
                        self._pending_socket = None
                        sock.close()
                        raise RuntimeError("Stopped during connect")
                    sock.connect((self._device_address, 1))  # channel 1 for SPP
                    self._pending_socket = None
                    sock.settimeout(5.0)  # read timeout after connected
                    self._desktop_socket = sock
                    logger.info("Desktop RFCOMM socket connected (native)")
                    return
                except OSError as e:
                    self._pending_socket = None
                    last_err = e
                    sock.close()
                    # errno 16 = EBUSY: BlueZ still holding the channel
                    if e.errno == 16 and attempt < 3:
                        logger.info(f"RFCOMM busy, waiting 5s (attempt {attempt + 1}/4)")
                        # Just wait — bluetoothctl disconnect makes it worse
                        # by killing the ACL link and sending the headset dark.
                        if self._stop_event.wait(5.0):
                            raise RuntimeError("Stopped during connect")
                        continue
                    break
            raise RuntimeError(f"Desktop RFCOMM connect failed: {last_err}")

        # Fallback: PyBluez BluetoothSocket (works independently of
        # CPython's socket module BT support)
        try:
            import bluetooth
        except ImportError:
            raise RuntimeError(
                "Desktop RFCOMM connect failed: module 'socket' has no attribute "
                "'AF_BLUETOOTH' and PyBluez is not installed. "
                "Install PyBluez: pip install pybluez"
            )

        try:
            sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            sock.settimeout(30.0)
            self._pending_socket = sock
            if not self._running:
                sock.close()
                raise RuntimeError("Stopped during connect")
            sock.connect((self._device_address, 1))
            self._pending_socket = None
            sock.settimeout(5.0)  # read timeout after connected
            self._desktop_socket = sock
            logger.info("Desktop RFCOMM socket connected (PyBluez)")
        except Exception as e:
            self._pending_socket = None
            raise RuntimeError(f"Desktop RFCOMM connect failed (PyBluez): {e}")

    # ---- Windows backend ----

    def _connect_windows(self) -> None:
        """Open serial COM port via pyserial (Windows).

        On Windows, NeuroSky MindWave pairs as a virtual COM port via SPP.
        The device address can be either:
        - A COM port name (e.g. "COM5") — used directly
        - A Bluetooth MAC address — we search for the matching COM port
        """
        try:
            import serial
        except ImportError:
            raise RuntimeError(
                "pyserial is required for Windows Bluetooth. Install it: pip install pyserial"
            )

        port = self._device_address
        # If address looks like a MAC, resolve it to a COM port
        if port and ":" in port:
            resolved = self._find_com_port_for_mac(port)
            if resolved:
                port = resolved
                logger.info(f"Resolved MAC {self._device_address} to {port}")
            else:
                raise RuntimeError(
                    f"Could not find COM port for device {self._device_address}. "
                    "Pair the device in Windows Bluetooth settings and check Device Manager for the COM port."
                )

        logger.info(f"Connecting to {self._device_name} via {port}...")
        try:
            ser = serial.Serial(
                port=port,
                baudrate=57600,
                timeout=5.0,
            )
            self._windows_serial = ser
            logger.info(f"Windows serial port connected: {port}")
        except Exception as e:
            raise RuntimeError(f"Windows serial connect failed ({port}): {e}")

    @staticmethod
    def _find_com_port_for_mac(mac_address: str) -> Optional[str]:
        """Search Windows registry for COM port associated with a BT MAC address."""
        try:
            import winreg
            # Normalize MAC: remove colons for registry lookup
            mac_clean = mac_address.replace(":", "").replace("-", "").upper()
            # BT COM ports are under HKLM\SYSTEM\CurrentControlSet\Enum\BTHENUM
            key_path = r"SYSTEM\CurrentControlSet\Enum\BTHENUM"
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
            except FileNotFoundError:
                return None
            # Walk subkeys looking for our MAC and an associated COM port
            import serial.tools.list_ports as list_ports
            for port_info in list_ports.comports():
                if port_info.hwid and mac_clean in port_info.hwid.upper():
                    winreg.CloseKey(key)
                    return port_info.device
            winreg.CloseKey(key)
        except Exception as e:
            logger.debug(f"COM port registry lookup failed: {e}")
        return None

    def _read_bytes(self, max_bytes: int) -> bytes:
        """Read bytes from the BT socket or serial device (platform-aware)."""
        if self._serial_fd is not None:
            return self._read_bytes_serial(max_bytes)
        if _IS_ANDROID:
            return self._read_bytes_android(max_bytes)
        if _IS_WINDOWS and self._windows_serial is not None:
            return self._read_bytes_windows(max_bytes)
        return self._read_bytes_desktop(max_bytes)

    def _read_bytes_serial(self, max_bytes: int) -> bytes:
        """Read bytes from a serial device file descriptor (splitter)."""
        import os as _os
        fd = self._serial_fd
        if fd is None:
            return b""
        try:
            # Poll: a cross-thread os.close() doesn't wake a blocked os.read().
            if not select.select([fd], [], [], 0.5)[0]:
                return b""
            return _os.read(fd, max_bytes)
        except BlockingIOError:
            return b""
        except Exception as e:
            logger.debug(f"_read_bytes_serial error: {e}")
            raise

    def _read_bytes_android(self, max_bytes: int) -> bytes:
        """One JNI read per chunk (byte-at-a-time was ~4000 calls/s); the buffer is sized exactly — pyjnius copies it both ways."""
        stream = self._bt_input_stream
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
            self._avail_high_water = max(self._avail_high_water, available)
            buf = bytearray(to_read)
            n = stream.read(buf, 0, to_read)
            if n <= 0:
                return head
            return head + bytes(buf[:n])
        except Exception as e:
            logger.debug(f"_read_bytes_android error: {e}")
            raise

    def _read_bytes_desktop(self, max_bytes: int) -> bytes:
        """Read bytes using Python socket (desktop Linux)."""
        if self._desktop_socket is None or not self._running:
            return b""
        try:
            return self._desktop_socket.recv(max_bytes)
        except _socket.timeout:
            return b""
        except Exception as e:
            if self._running:
                logger.debug(f"_read_bytes_desktop error: {e}")
            raise

    def _read_bytes_windows(self, max_bytes: int) -> bytes:
        """Read bytes using pyserial (Windows)."""
        if self._windows_serial is None:
            return b""
        try:
            waiting = self._windows_serial.in_waiting
            if waiting > 0:
                return self._windows_serial.read(min(waiting, max_bytes))
            return self._windows_serial.read(1)
        except Exception as e:
            logger.debug(f"_read_bytes_windows error: {e}")
            raise

    def _close_socket(self) -> None:
        """Close every open handle; locked because stop() and the exiting reader both call it."""
        import os as _os
        with self._close_lock:
            self._bt_input_stream = None
            serial, self._windows_serial = self._windows_serial, None
            if serial is not None:
                try:
                    serial.close()
                except Exception as e:
                    logger.debug(f"closing serial port: {e}")
            fd, self._serial_fd = self._serial_fd, None
            if fd is not None:
                try:
                    _os.close(fd)
                except OSError as e:
                    logger.debug(f"closing serial fd: {e}")
            pending, self._pending_socket = self._pending_socket, None
            if pending is not None:
                self._shutdown_before_close(pending)
                try:
                    pending.close()
                    logger.info("Aborted in-flight RFCOMM connect")
                except Exception as e:
                    logger.debug(f"closing in-flight RFCOMM socket: {e}")
            bt, self._bt_socket = self._bt_socket, None
            if bt is not None:
                try:
                    bt.close()
                    logger.info(f"RFCOMM socket #{self._socket_seq} closed")
                except Exception as e:
                    logger.debug(f"closing RFCOMM socket: {e}")
            desk, self._desktop_socket = self._desktop_socket, None
            if desk is not None:
                self._shutdown_before_close(desk)
                try:
                    desk.close()
                except Exception as e:
                    logger.debug(f"closing desktop socket: {e}")

    @staticmethod
    def _shutdown_before_close(sock) -> None:
        """Wake a thread blocked in connect()/recv() — on Linux a cross-thread close() alone doesn't."""
        # Python and PyBluez sockets have shutdown(); Android's Java socket doesn't (close() aborts it).
        try:
            shutdown = getattr(sock, "shutdown", None)
            if shutdown is not None:
                shutdown(_socket.SHUT_RDWR)
        except Exception as e:
            logger.debug(f"shutdown before close: {e}")

    @staticmethod
    def scan_paired_devices() -> list[dict[str, str]]:
        """Return list of paired Bluetooth devices.

        Returns [{'name': ..., 'address': ...}].
        Works on Android (pyjnius) and desktop Linux (bluetoothctl).
        """
        if _IS_ANDROID:
            return NeuroSkyStream._scan_paired_android()
        if _IS_WINDOWS:
            return NeuroSkyStream._scan_paired_windows()
        return NeuroSkyStream._scan_paired_desktop()

    @staticmethod
    def _scan_paired_android() -> list[dict[str, str]]:
        """Scan paired devices via Android Bluetooth API."""
        try:
            from jnius import autoclass
        except ImportError:
            logger.debug("pyjnius not available, scan returning empty")
            return []

        try:
            NeuroSkyStream._request_bt_permissions()

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

    @staticmethod
    def _scan_paired_desktop() -> list[dict[str, str]]:
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

    @staticmethod
    def _scan_paired_windows() -> list[dict[str, str]]:
        """Scan for Bluetooth serial (COM) ports on Windows.

        Lists COM ports that are associated with Bluetooth devices.
        Falls back to listing all available COM ports if BT filtering fails.
        """
        try:
            import serial.tools.list_ports as list_ports
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


if __name__ == "__main__":
    # Desktop test: just test the parser with sample ThinkGear data
    parser = ThinkGearParser()

    # Build a test packet: sync(2) + plength(1) + payload + checksum(1)
    payload = bytes([
        CODE_POOR_SIGNAL, 0,
        CODE_ATTENTION, 75,
        CODE_MEDITATION, 82,
    ])
    checksum = (~sum(payload)) & 0xFF
    packet = bytes([0xAA, 0xAA, len(payload)]) + payload + bytes([checksum])

    results = parser.feed(packet)
    print(f"Parsed {len(results)} packet(s)")
    for r in results:
        print(f"  signal_quality={r.get('signal_quality')}, "
              f"attention={r.get('attention')}, meditation={r.get('meditation')}")

    # Test ASIC_EEG_POWER packet
    band_data = bytearray()
    for i in range(8):
        val = (i + 1) * 1000
        band_data.append((val >> 16) & 0xFF)
        band_data.append((val >> 8) & 0xFF)
        band_data.append(val & 0xFF)
    payload2 = bytes([CODE_ASIC_EEG_POWER, 24]) + bytes(band_data)
    checksum2 = (~sum(payload2)) & 0xFF
    packet2 = bytes([0xAA, 0xAA, len(payload2)]) + payload2 + bytes([checksum2])

    results2 = parser.feed(packet2)
    print(f"Parsed {len(results2)} EEG power packet(s)")
    for r in results2:
        if "bands" in r:
            for name, val in r["bands"].items():
                print(f"  {name}: {val:.0f}")
