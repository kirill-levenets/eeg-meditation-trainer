"""Tests for NeuroSky ThinkGear parser and stream interface."""
import struct
import unittest

from app.eeg import bt_links
from app.eeg.neurosky_stream import NeuroSkyStream
from app.eeg.thinkgear import (
    BAND_NAMES,
    CODE_ASIC_EEG_POWER,
    CODE_ATTENTION,
    CODE_BATTERY,
    CODE_EEG_POWER_FLOAT,
    CODE_MEDITATION,
    CODE_POOR_SIGNAL,
    CODE_RAW_WAVE,
    ThinkGearParser,
)


def _build_packet(payload: bytes) -> bytes:
    """Build a valid ThinkGear packet from a payload."""
    checksum = (~sum(payload)) & 0xFF
    return bytes([0xAA, 0xAA, len(payload)]) + payload + bytes([checksum])


class TestThinkGearParser(unittest.TestCase):
    """Test ThinkGear packet parsing."""

    def setUp(self):
        self.parser = ThinkGearParser()

    def test_parse_single_byte_codes(self):
        payload = bytes([
            CODE_POOR_SIGNAL, 0,
            CODE_ATTENTION, 75,
            CODE_MEDITATION, 82,
        ])
        results = self.parser.feed(_build_packet(payload))
        self.assertEqual(len(results), 1)
        pkt = results[0]
        self.assertEqual(pkt["signal_quality"], 0)
        self.assertEqual(pkt["attention"], 75.0)
        self.assertEqual(pkt["meditation"], 82.0)

    def test_parse_poor_signal_200(self):
        payload = bytes([CODE_POOR_SIGNAL, 200])
        results = self.parser.feed(_build_packet(payload))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["signal_quality"], 200)

    def test_parse_raw_wave(self):
        # Raw wave: signed 16-bit, value = -100
        val = -100
        high = (val + 65536) >> 8
        low = (val + 65536) & 0xFF
        payload = bytes([CODE_RAW_WAVE, 2, high, low])
        results = self.parser.feed(_build_packet(payload))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["raw_wave"], -100)

    def test_parse_raw_wave_positive(self):
        val = 500
        high = val >> 8
        low = val & 0xFF
        payload = bytes([CODE_RAW_WAVE, 2, high, low])
        results = self.parser.feed(_build_packet(payload))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["raw_wave"], 500)

    def test_parse_asic_eeg_power(self):
        band_data = bytearray()
        expected = {}
        for i, name in enumerate(BAND_NAMES):
            val = (i + 1) * 1000
            expected[name] = float(val)
            band_data.append((val >> 16) & 0xFF)
            band_data.append((val >> 8) & 0xFF)
            band_data.append(val & 0xFF)
        payload = bytes([CODE_ASIC_EEG_POWER, 24]) + bytes(band_data)
        results = self.parser.feed(_build_packet(payload))
        self.assertEqual(len(results), 1)
        bands = results[0]["bands"]
        for name in BAND_NAMES:
            self.assertEqual(bands[name], expected[name])

    def test_bands_decode_from_either_width_and_a_row_of_another_length_is_skipped(self):
        powers = [1.5, 2.25, 1e5, 0.0, 7.0, 123456.0, -3.0, 9.75]
        floats = bytes([CODE_EEG_POWER_FLOAT, 32]) + b"".join(struct.pack(">f", v) for v in powers)
        ints = bytes([CODE_ASIC_EEG_POWER, 24]) + b"".join((i * 70000).to_bytes(3, "big") for i in range(8))
        short = bytes([CODE_ASIC_EEG_POWER, 21]) + bytes(21)
        float_pkt, int_pkt, both, short_pkt = self.parser.feed(
            _build_packet(floats) + _build_packet(ints) + _build_packet(floats + ints) + _build_packet(short))
        self.assertEqual(float_pkt["bands"], dict(zip(BAND_NAMES, powers)))
        self.assertEqual(int_pkt["bands"], {name: float(i * 70000) for i, name in enumerate(BAND_NAMES)})
        self.assertEqual(both["bands"], int_pkt["bands"])  # the later row
        self.assertEqual(short_pkt, {})

    def test_battery_excode_and_a_row_cut_short(self):
        payload = bytes([0x55, CODE_BATTERY, 90, 0x16, 7, CODE_ATTENTION, 40, CODE_RAW_WAVE, 4, 1])
        (pkt,) = self.parser.feed(_build_packet(payload))
        # EXCODE bytes skipped, an unknown code's row skipped, the raw row longer than what is left ends it
        self.assertEqual(pkt, {"battery": 90, "attention": 40.0})
        self.assertIs(type(pkt["battery"]), int)

    def test_a_payload_ending_in_a_code_without_its_length(self):
        (pkt,) = self.parser.feed(_build_packet(bytes([CODE_ATTENTION, 40, CODE_RAW_WAVE])))
        self.assertEqual(pkt, {"attention": 40.0})

    def test_checksum_mismatch_skipped(self):
        payload = bytes([CODE_ATTENTION, 50])
        good_packet = _build_packet(payload)
        # Corrupt checksum
        bad_packet = good_packet[:-1] + bytes([good_packet[-1] ^ 0xFF])
        results = self.parser.feed(bad_packet)
        self.assertEqual(len(results), 0)

    def test_multiple_packets_in_stream(self):
        pkt1 = _build_packet(bytes([CODE_ATTENTION, 60]))
        pkt2 = _build_packet(bytes([CODE_MEDITATION, 70]))
        results = self.parser.feed(pkt1 + pkt2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["attention"], 60.0)
        self.assertEqual(results[1]["meditation"], 70.0)

    def test_partial_packet_buffered(self):
        payload = bytes([CODE_ATTENTION, 88])
        full = _build_packet(payload)
        # Feed first half
        results1 = self.parser.feed(full[:3])
        self.assertEqual(len(results1), 0)
        # Feed second half
        results2 = self.parser.feed(full[3:])
        self.assertEqual(len(results2), 1)
        self.assertEqual(results2[0]["attention"], 88.0)

    def test_garbage_before_sync_skipped(self):
        garbage = bytes([0x01, 0x02, 0x03, 0x55])
        payload = bytes([CODE_MEDITATION, 45])
        data = garbage + _build_packet(payload)
        results = self.parser.feed(data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["meditation"], 45.0)

    def test_payload_too_long_skipped(self):
        # plength > 169 is invalid
        bad = bytes([0xAA, 0xAA, 200])
        payload = bytes([CODE_ATTENTION, 50])
        good = _build_packet(payload)
        results = self.parser.feed(bad + good)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["attention"], 50.0)

    def test_empty_payload(self):
        pkt = _build_packet(b"")
        results = self.parser.feed(pkt)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], {})


class TestNeuroSkyStreamInterface(unittest.TestCase):
    """Test NeuroSkyStream has the same interface as MockEEGStream."""

    def test_initial_state(self):
        stream = NeuroSkyStream()
        self.assertFalse(stream.is_connected)
        self.assertFalse(stream._running)

    def test_set_device(self):
        stream = NeuroSkyStream()
        stream.set_device("AA:BB:CC:DD:EE:FF", "MindWave")
        self.assertEqual(stream._device_address, "AA:BB:CC:DD:EE:FF")
        self.assertEqual(stream._device_name, "MindWave")

    def test_start_without_device_does_nothing(self):
        stream = NeuroSkyStream()
        stream.start()
        self.assertFalse(stream._running)

    def test_read_sample_returns_all_bands(self):
        stream = NeuroSkyStream()
        stream._start_time = 0.0
        sample = stream.read_sample()
        for name in BAND_NAMES:
            self.assertIn(name, sample)
        self.assertIn("attention", sample)
        self.assertIn("meditation", sample)
        self.assertIn("signal_quality", sample)
        self.assertIn("timestamp", sample)

    def test_apply_packet_updates_state(self):
        stream = NeuroSkyStream()
        stream._apply_packet({
            "bands": {"delta": 5000.0, "theta": 3000.0},
            "attention": 80.0,
            "meditation": 65.0,
            "signal_quality": 0,
        })
        self.assertEqual(stream._latest_bands["delta"], 5000.0)
        self.assertEqual(stream._latest_bands["theta"], 3000.0)
        self.assertEqual(stream._latest_attention, 80.0)
        self.assertEqual(stream._latest_meditation, 65.0)
        self.assertEqual(stream._latest_signal_quality, 0)

    def test_raw_wave_buffer_capped(self):
        stream = NeuroSkyStream()
        for i in range(1100):
            stream._apply_packet({"raw_wave": i})
        self.assertLessEqual(len(stream._raw_wave_buffer), 1024)

    def test_scan_paired_devices_returns_list_on_desktop(self):
        # On desktop, should return list of paired devices via bluetoothctl
        devices = bt_links.scan_paired()
        self.assertIsInstance(devices, list)
        for dev in devices:
            self.assertIn("name", dev)
            self.assertIn("address", dev)


if __name__ == "__main__":
    unittest.main(verbosity=2)
