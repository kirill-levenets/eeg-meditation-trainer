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

# A single-byte row's code: the packet key its value goes under, and its type there.
_SINGLE_BYTE_FIELDS = {
    CODE_BATTERY: ("battery", int),  # 0-127, ~3V scale
    CODE_POOR_SIGNAL: ("signal_quality", int),
    CODE_ATTENTION: ("attention", float),
    CODE_MEDITATION: ("meditation", float),
}

# A band row's code: the bytes per band and how they decode (big-endian, as the headset sends them).
_BAND_ENCODINGS = {
    CODE_ASIC_EEG_POWER: (3, lambda data: int.from_bytes(data, "big")),
    CODE_EEG_POWER_FLOAT: (4, lambda data: struct.unpack(">f", data)[0]),
}


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
        """The values of a valid payload's data rows; a code it doesn't know, or a row of the wrong length, is skipped."""
        result: dict = {}
        for code, value in _rows(payload):
            if code in _SINGLE_BYTE_FIELDS:
                key, kind = _SINGLE_BYTE_FIELDS[code]
                result[key] = kind(value[0])
            elif code == CODE_RAW_WAVE and len(value) == 2:
                result["raw_wave"] = int.from_bytes(value, "big", signed=True)
            elif code in _BAND_ENCODINGS:
                bands = _bands(value, *_BAND_ENCODINGS[code])
                if bands is not None:
                    result["bands"] = bands
        return result


def _rows(payload: bytes):
    """(code, value bytes) of each data row: a code under 0x80 has one value byte, a higher one a length byte first;
    the EXCODE bytes before a code are skipped, and a row cut short ends the payload."""
    i = 0
    while i < len(payload):
        while i < len(payload) and payload[i] == THINKGEAR_EXCODE:
            i += 1
        if i + 1 >= len(payload):
            return
        code = payload[i]
        start, length = (i + 1, 1) if code < 0x80 else (i + 2, payload[i + 1])
        if start + length > len(payload):
            return
        yield code, payload[start:start + length]
        i = start + length


def _bands(data: bytes, width: int, decode) -> dict[str, float] | None:
    """Each band's power from `width` bytes per band in BAND_NAMES order; None unless the row holds all of them."""
    if len(data) != width * len(BAND_NAMES):
        return None
    return {name: float(decode(data[i * width:(i + 1) * width])) for i, name in enumerate(BAND_NAMES)}
