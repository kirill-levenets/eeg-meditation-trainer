import unittest

from app.eeg.mock_stream import MockEEGStream as MockEEGStreamV1
from app.eeg.mock_stream_v2 import MockEEGStream as MockEEGStreamV2


class TestMockEEGStreamV1(unittest.TestCase):
    """Test original mock EEG signal generation."""

    def setUp(self):
        self.stream = MockEEGStreamV1()
        self.stream.start()

    def tearDown(self):
        self.stream.stop()

    def test_sample_has_all_bands(self):
        sample = self.stream.read_sample()
        expected = {"delta", "theta", "alpha1", "alpha2",
                    "beta1", "beta2", "gamma1", "gamma2",
                    "attention", "meditation", "timestamp"}
        self.assertTrue(expected.issubset(sample.keys()))

    def test_all_values_non_negative(self):
        for _ in range(50):
            sample = self.stream.read_sample()
            for key in ("delta", "theta", "alpha1", "alpha2",
                        "beta1", "beta2", "gamma1", "gamma2"):
                self.assertGreaterEqual(sample[key], 0.0, f"{key} was negative")

    def test_attention_meditation_in_range(self):
        for _ in range(50):
            sample = self.stream.read_sample()
            self.assertGreaterEqual(sample["attention"], 0)
            self.assertLessEqual(sample["attention"], 100)
            self.assertGreaterEqual(sample["meditation"], 0)
            self.assertLessEqual(sample["meditation"], 100)

    def test_state_transitions_produce_variation(self):
        stream = MockEEGStreamV1()
        stream.start()
        alphas = []
        for _ in range(100):
            s = stream.read_sample()
            alphas.append(s["alpha1"])
        stream.stop()
        self.assertGreater(max(alphas) - min(alphas), 50.0)

    def test_smooth_step(self):
        self.assertAlmostEqual(MockEEGStreamV1._smooth_step(0.0), 0.0)
        self.assertAlmostEqual(MockEEGStreamV1._smooth_step(1.0), 1.0)
        self.assertAlmostEqual(MockEEGStreamV1._smooth_step(0.5), 0.5)


class TestMockEEGStreamV2(unittest.TestCase):
    """Test frequency-based mock EEG signal generation (v2)."""

    def setUp(self):
        self.stream = MockEEGStreamV2()
        self.stream.start()

    def tearDown(self):
        self.stream.stop()

    def test_sample_has_all_bands(self):
        sample = self.stream.read_sample()
        expected = {"delta", "theta", "alpha1", "alpha2",
                    "beta1", "beta2", "gamma1", "gamma2",
                    "attention", "meditation", "timestamp"}
        self.assertTrue(expected.issubset(sample.keys()))

    def test_all_values_non_negative(self):
        for _ in range(50):
            sample = self.stream.read_sample()
            for key in ("delta", "theta", "alpha1", "alpha2",
                        "beta1", "beta2", "gamma1", "gamma2"):
                self.assertGreaterEqual(sample[key], 0.0, f"{key} was negative")

    def test_attention_meditation_in_range(self):
        for _ in range(50):
            sample = self.stream.read_sample()
            self.assertGreaterEqual(sample["attention"], 0)
            self.assertLessEqual(sample["attention"], 100)
            self.assertGreaterEqual(sample["meditation"], 0)
            self.assertLessEqual(sample["meditation"], 100)

    def test_state_transitions_produce_variation(self):
        stream = MockEEGStreamV2()
        stream.start()
        alphas = []
        for _ in range(100):
            s = stream.read_sample()
            alphas.append(s["alpha1"])
        stream.stop()
        self.assertGreater(max(alphas) - min(alphas), 50.0)

    def test_smooth_step(self):
        self.assertAlmostEqual(MockEEGStreamV2._smooth_step(0.0), 0.0)
        self.assertAlmostEqual(MockEEGStreamV2._smooth_step(1.0), 1.0)
        self.assertAlmostEqual(MockEEGStreamV2._smooth_step(0.5), 0.5)

    def test_frequency_regeneration(self):
        """Verify band frequencies are within expected Hz ranges."""
        from app.eeg.mock_stream_v2 import BAND_FREQ_RANGES
        self.stream._regenerate_frequencies()
        for band, (lo, hi) in BAND_FREQ_RANGES.items():
            freq = self.stream._band_frequencies[band]
            self.assertGreaterEqual(freq, lo)
            self.assertLessEqual(freq, hi)

    def test_raw_eeg_waveform_present(self):
        """Verify sample contains oscillating waveform burst."""
        sample = self.stream.read_sample()
        self.assertIn("raw_eeg_waveform", sample)
        waveform = sample["raw_eeg_waveform"]
        self.assertEqual(len(waveform), 64)

    def test_raw_eeg_waveform_oscillates(self):
        """Waveform should have both positive and negative values."""
        sample = self.stream.read_sample()
        waveform = sample["raw_eeg_waveform"]
        has_pos = any(v > 0 for v in waveform)
        has_neg = any(v < 0 for v in waveform)
        self.assertTrue(has_pos, "Waveform has no positive values")
        self.assertTrue(has_neg, "Waveform has no negative values")

    def test_is_connected_property(self):
        self.assertTrue(self.stream.is_connected)
        self.stream.stop()
        self.assertFalse(self.stream.is_connected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
