"""The ThinkGear protocol the MindWave speaks: its packet codes, and a parser that turns a byte stream into
packets."""
import struct

from app.eeg.band_spec import BAND_KEYS
from app.logger import logger

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

    def _try_parse_packet(self) -> dict | None:
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
