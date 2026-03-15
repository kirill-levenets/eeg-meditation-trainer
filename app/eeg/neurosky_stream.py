"""NeuroSky MindWave Mobile 2 stream driver.

Connects via Bluetooth Classic RFCOMM on Android using pyjnius.
Parses ThinkGear serial protocol packets to extract:
- 8 EEG band powers (ASIC_EEG_POWER_INT, code 0x83)
- Attention (code 0x04) and Meditation (code 0x05) eSense values
- Signal quality (code 0x02)
- Raw wave (code 0x80, 512Hz signed 16-bit)

Falls back gracefully on non-Android platforms.
"""
import struct
import threading
import time
from typing import Dict, List, Optional

from app.logger import logger

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
    Uses pyjnius on Android for Bluetooth access.
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

        # Android Bluetooth objects (set during connect)
        self._bt_socket = None

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

        while self._running:
            try:
                data = self._read_bytes(256)
                if not data:
                    time.sleep(0.01)
                    continue
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

    def _connect_bluetooth(self) -> None:
        """Open RFCOMM socket to the MindWave via Android Bluetooth API."""
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

        # Try standard RFCOMM first, fall back to reflection method
        # (many Android devices fail with IOException on the standard call)
        try:
            socket = device.createRfcommSocketToServiceRecord(uuid)
            socket.connect()
            self._bt_socket = socket
            logger.info("RFCOMM socket connected (standard)")
            return
        except Exception as e:
            logger.warning(f"Standard RFCOMM failed: {e}, trying reflection fallback")

        try:
            Integer = autoclass("java.lang.Integer")
            clazz = device.getClass()
            method = clazz.getMethod(
                "createRfcommSocket", Integer.TYPE,
            )
            socket = method.invoke(device, 1)
            socket.connect()
            self._bt_socket = socket
            logger.info("RFCOMM socket connected (reflection fallback)")
        except Exception as e2:
            raise RuntimeError(f"Both RFCOMM methods failed: {e2}") from e2

    def _read_bytes(self, max_bytes: int) -> bytes:
        """Read up to max_bytes from the BT socket."""
        if self._bt_socket is None:
            return b""
        try:
            input_stream = self._bt_socket.getInputStream()
            available = input_stream.available()
            if available <= 0:
                return b""
            to_read = min(available, max_bytes)
            buf = bytearray(to_read)
            for i in range(to_read):
                b = input_stream.read()
                if b < 0:
                    break
                buf[i] = b
            return bytes(buf)
        except Exception:
            return b""

    def _close_socket(self) -> None:
        """Close the Bluetooth socket if open."""
        if self._bt_socket:
            try:
                self._bt_socket.close()
            except Exception:
                pass
            self._bt_socket = None

    @staticmethod
    def scan_paired_devices() -> List[Dict[str, str]]:
        """Return list of paired Bluetooth devices.

        Returns [{'name': ..., 'address': ...}].
        Only works on Android. Returns empty list on other platforms.
        """
        try:
            from jnius import autoclass
        except ImportError:
            logger.debug("pyjnius not available, scan_paired_devices returning empty")
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
            logger.error(f"BT scan error: {e}")
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
