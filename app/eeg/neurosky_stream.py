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
import socket as _socket
import struct
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional

from app.logger import logger

_IS_ANDROID: bool = hasattr(sys, "getandroidapilevel")
_IS_WINDOWS: bool = sys.platform == "win32"

THINKGEAR_SYNC = 0xAA
THINKGEAR_EXCODE = 0x55

CODE_POOR_SIGNAL = 0x02
CODE_ATTENTION = 0x04
CODE_MEDITATION = 0x05
CODE_RAW_WAVE = 0x80
CODE_EEG_POWER_FLOAT = 0x81
CODE_ASIC_EEG_POWER = 0x83

BAND_NAMES = ("delta", "theta", "alpha1", "alpha2", "beta1", "beta2", "gamma1", "gamma2")

NEUROSKY_SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"


class ThinkGearParser:
    """Stateful parser for ThinkGear serial protocol packets."""

    def __init__(self) -> None:
        self._buffer: bytearray = bytearray()

    def feed(self, data: bytes) -> List[Dict]:
        """Feed raw bytes, return list of parsed complete packets."""
        self._buffer.extend(data)
        results: List[Dict] = []
        while self._buffer:
            prev_len = len(self._buffer)
            packet = self._try_parse_packet()
            if packet is not None:
                results.append(packet)
                continue
            if len(self._buffer) == prev_len:
                break
        return results

    def _try_parse_packet(self) -> Optional[Dict]:
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

    def _parse_payload(self, payload: bytes) -> Dict:
        """Parse DataRows from a valid payload."""
        result: Dict = {}
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
                if code == CODE_POOR_SIGNAL:
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
        self._latest_bands: Dict[str, float] = {name: 0.0 for name in BAND_NAMES}
        self._latest_attention: float = 0.0
        self._latest_meditation: float = 0.0
        self._latest_signal_quality: int = 200
        self._raw_wave_buffer: List[int] = []

        # Bluetooth objects (set during connect)
        self._bt_socket = None
        self._bt_input_stream = None  # Android only (Java InputStream)
        self._desktop_socket: Optional[_socket.socket] = None  # Desktop only
        self._windows_serial = None  # Windows only (pyserial Serial object)
        self._serial_fd: Optional[int] = None  # Serial device mode (splitter)
        self._read_count: int = 0

    def set_device(self, address: str, name: str = "") -> None:
        """Set the target Bluetooth device address."""
        self._device_address = address
        self._device_name = name or address
        logger.info(f"NeuroSky device set: {self._device_name} ({address})")

    def start(self) -> None:
        """Start reading from the device in a background thread."""
        if self._running:
            return
        if not self._device_address:
            logger.warning("NeuroSky start failed: no device address set")
            return
        self._running = True
        self._start_time = time.time()
        self._sample_count = 0
        self._parser = ThinkGearParser()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        logger.info("NeuroSky stream started")

    def stop(self) -> None:
        """Stop the reader thread and close the socket."""
        self._running = False
        self._connected = False
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._close_socket()
        logger.info("NeuroSky stream stopped")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def read_sample(self) -> Dict:
        """Return the latest consolidated EEG sample.

        Returns a dict matching MockEEGStream format:
        delta, theta, alpha1, alpha2, beta1, beta2, gamma1, gamma2,
        attention, meditation, timestamp, signal_quality
        """
        with self._lock:
            sample: Dict = {}
            sample["timestamp"] = time.time() - self._start_time
            for name in BAND_NAMES:
                sample[name] = self._latest_bands.get(name, 0.0)
            sample["attention"] = self._latest_attention
            sample["meditation"] = self._latest_meditation
            sample["signal_quality"] = self._latest_signal_quality
            # Drain raw wave buffer for waveform graph
            if self._raw_wave_buffer:
                sample["raw_eeg_waveform"] = list(self._raw_wave_buffer)
                self._raw_wave_buffer.clear()
            self._sample_count += 1
            return sample

    def _read_loop(self) -> None:
        """Background thread: connect and read ThinkGear packets."""
        try:
            self._connect_bluetooth()
        except Exception as e:
            logger.error(f"NeuroSky BT connect failed: {e}")
            self._running = False
            self._connected = False
            return

        logger.info("NeuroSky BT connected, reading packets...")
        self._connected = True
        self._read_count = 0

        while self._running:
            try:
                data = self._read_bytes(512)
                if not data:
                    time.sleep(0.01)
                    continue
                self._read_count += 1
                if self._read_count == 1 or self._read_count % 1000 == 0:
                    logger.debug(f"BT read #{self._read_count}: {len(data)} bytes")
                packets = self._parser.feed(data)
                for pkt in packets:
                    self._apply_packet(pkt)
            except Exception as e:
                logger.error(f"NeuroSky read error: {e}")
                self._connected = False
                time.sleep(2.0)
                if self._running:
                    try:
                        self._close_socket()
                        self._connect_bluetooth()
                        self._connected = True
                        logger.info("NeuroSky reconnected")
                    except Exception as re:
                        logger.error(f"NeuroSky reconnect failed: {re}")
                        self._running = False

    def _apply_packet(self, pkt: Dict) -> None:
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

        errors: List[str] = []

        # Method 1: Standard secure RFCOMM
        try:
            socket = device.createRfcommSocketToServiceRecord(uuid)
            socket.connect()
            self._bt_socket = socket
            self._bt_input_stream = socket.getInputStream()
            logger.info("RFCOMM socket connected (secure)")
            return
        except Exception as e:
            errors.append(f"secure: {e}")
            logger.warning(f"Secure RFCOMM failed: {e}")

        # Method 2: Insecure RFCOMM
        try:
            socket = device.createInsecureRfcommSocketToServiceRecord(uuid)
            socket.connect()
            self._bt_socket = socket
            self._bt_input_stream = socket.getInputStream()
            logger.info("RFCOMM socket connected (insecure)")
            return
        except Exception as e:
            errors.append(f"insecure: {e}")
            logger.warning(f"Insecure RFCOMM failed: {e}")

        # Method 3: Reflection-based createRfcommSocket(channel=1)
        try:
            from jnius import cast
            Integer = autoclass("java.lang.Integer")
            clazz = device.getClass()
            intclass = Integer.TYPE
            method = clazz.getMethod("createRfcommSocket", [intclass])
            raw_socket = method.invoke(device, [Integer.valueOf(1)])
            socket = cast("android.bluetooth.BluetoothSocket", raw_socket)
            socket.connect()
            self._bt_socket = socket
            self._bt_input_stream = socket.getInputStream()
            logger.info("RFCOMM socket connected (reflection ch=1)")
            return
        except Exception as e:
            errors.append(f"reflection: {e}")
            logger.warning(f"Reflection RFCOMM failed: {e}")

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

    def _connect_desktop(self) -> None:
        """Open RFCOMM socket via Python socket module (Linux desktop).

        Falls back to PyBluez if the Python build lacks socket.AF_BLUETOOTH
        (common in PyInstaller bundles built without libbluetooth-dev headers).
        """
        logger.info(f"Connecting to {self._device_name} ({self._device_address}) via desktop RFCOMM...")

        # Try native socket.AF_BLUETOOTH first (available when Python was
        # compiled with libbluetooth-dev headers)
        if hasattr(_socket, "AF_BLUETOOTH"):
            try:
                BTPROTO_RFCOMM = 3
                sock = _socket.socket(
                    _socket.AF_BLUETOOTH, _socket.SOCK_STREAM, BTPROTO_RFCOMM
                )
                sock.connect((self._device_address, 1))  # channel 1 for SPP
                sock.settimeout(5.0)
                self._desktop_socket = sock
                logger.info("Desktop RFCOMM socket connected (native)")
                return
            except Exception as e:
                raise RuntimeError(f"Desktop RFCOMM connect failed: {e}")

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
            sock.connect((self._device_address, 1))
            sock.settimeout(5.0)
            self._desktop_socket = sock
            logger.info("Desktop RFCOMM socket connected (PyBluez)")
        except Exception as e:
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
        if self._serial_fd is None:
            return b""
        try:
            return _os.read(self._serial_fd, max_bytes)
        except BlockingIOError:
            return b""
        except Exception as e:
            logger.debug(f"_read_bytes_serial error: {e}")
            raise

    def _read_bytes_android(self, max_bytes: int) -> bytes:
        """Read bytes using Java InputStream (Android)."""
        if self._bt_input_stream is None:
            return b""
        try:
            available = self._bt_input_stream.available()
            if available <= 0:
                first = self._bt_input_stream.read()
                if first < 0:
                    return b""
                result = bytearray([first])
                available = self._bt_input_stream.available()
                if available > 0:
                    to_read = min(available, max_bytes - 1)
                    for _ in range(to_read):
                        b = self._bt_input_stream.read()
                        if b < 0:
                            break
                        result.append(b)
                return bytes(result)
            else:
                to_read = min(available, max_bytes)
                result = bytearray()
                for _ in range(to_read):
                    b = self._bt_input_stream.read()
                    if b < 0:
                        break
                    result.append(b)
                return bytes(result)
        except Exception as e:
            logger.debug(f"_read_bytes_android error: {e}")
            raise

    def _read_bytes_desktop(self, max_bytes: int) -> bytes:
        """Read bytes using Python socket (desktop Linux)."""
        if self._desktop_socket is None:
            return b""
        try:
            return self._desktop_socket.recv(max_bytes)
        except _socket.timeout:
            return b""
        except Exception as e:
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
        """Close the Bluetooth socket or serial device if open."""
        import os as _os
        self._bt_input_stream = None
        if self._windows_serial is not None:
            try:
                self._windows_serial.close()
            except Exception:
                pass
            self._windows_serial = None
        if self._serial_fd is not None:
            try:
                _os.close(self._serial_fd)
            except Exception:
                pass
            self._serial_fd = None
        if self._bt_socket:
            try:
                self._bt_socket.close()
            except Exception:
                pass
            self._bt_socket = None
        if self._desktop_socket:
            try:
                self._desktop_socket.close()
            except Exception:
                pass
            self._desktop_socket = None

    @staticmethod
    def scan_paired_devices() -> List[Dict[str, str]]:
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
    def _scan_paired_android() -> List[Dict[str, str]]:
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
            devices: List[Dict[str, str]] = []
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
    def _scan_paired_desktop() -> List[Dict[str, str]]:
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
                devices: List[Dict[str, str]] = []
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
    def _scan_paired_windows() -> List[Dict[str, str]]:
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
            devices: List[Dict[str, str]] = []
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
