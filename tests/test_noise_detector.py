import math
import unittest

from app.metrics.noise_detector import PowerLineDetector


class TestPowerLineDetector(unittest.TestCase):

    def _generate_sine(self, freq: float, n: int = 2048,
                       sample_rate: int = 512, amplitude: float = 100.0) -> list:
        return [amplitude * math.sin(2 * math.pi * freq * i / sample_rate)
                for i in range(n)]

    def test_detects_50hz(self):
        det = PowerLineDetector()
        samples = self._generate_sine(50)
        det.feed(samples)
        self.assertTrue(det.ready())
        detected, freq = det.result()
        self.assertTrue(detected)
        self.assertEqual(freq, 50)

    def test_detects_60hz(self):
        det = PowerLineDetector()
        samples = self._generate_sine(60)
        det.feed(samples)
        self.assertTrue(det.ready())
        detected, freq = det.result()
        self.assertTrue(detected)
        self.assertEqual(freq, 60)

    def test_clean_alpha_signal(self):
        """A 10 Hz alpha wave should not trigger detection."""
        det = PowerLineDetector()
        samples = self._generate_sine(10)
        det.feed(samples)
        self.assertTrue(det.ready())
        detected, freq = det.result()
        self.assertFalse(detected)
        self.assertIsNone(freq)

    def test_noise_on_top_of_eeg(self):
        """50Hz noise mixed with normal EEG bands should still be detected."""
        det = PowerLineDetector()
        n = 2048
        sr = 512
        samples = []
        for i in range(n):
            t = i / sr
            eeg = (30 * math.sin(2 * math.pi * 10 * t)   # alpha
                   + 15 * math.sin(2 * math.pi * 20 * t)  # beta
                   + 10 * math.sin(2 * math.pi * 5 * t))  # theta
            noise = 80 * math.sin(2 * math.pi * 50 * t)
            samples.append(eeg + noise)
        det.feed(samples)
        self.assertTrue(det.ready())
        detected, freq = det.result()
        self.assertTrue(detected)
        self.assertEqual(freq, 50)

    def test_not_ready_until_enough_samples(self):
        det = PowerLineDetector()
        det.feed([0.0] * 100)
        self.assertFalse(det.ready())
        self.assertIsNone(det.result())

    def test_reset(self):
        det = PowerLineDetector()
        det.feed(self._generate_sine(50))
        self.assertTrue(det.ready())
        det.reset()
        self.assertFalse(det.ready())

    def test_feed_stops_after_detection(self):
        det = PowerLineDetector()
        det.feed(self._generate_sine(50))
        self.assertTrue(det.ready())
        # Feed more data — result shouldn't change
        det.feed(self._generate_sine(60))
        detected, freq = det.result()
        self.assertEqual(freq, 50)

    def test_incremental_feed(self):
        """Feeding in small chunks should work once total >= MIN_SAMPLES."""
        det = PowerLineDetector()
        samples = self._generate_sine(60, n=2200)
        chunk = 200
        for i in range(0, len(samples), chunk):
            det.feed(samples[i:i + chunk])
            if det.ready():
                break
        self.assertTrue(det.ready())
        detected, freq = det.result()
        self.assertTrue(detected)
        self.assertEqual(freq, 60)


    def test_broadband_noise_no_false_positive(self):
        """Random broadband noise (simulating real EEG) should not trigger."""
        import random
        random.seed(42)
        det = PowerLineDetector()
        # Mix of typical EEG bands without power line noise
        n = 2048
        sr = 512
        samples = []
        for i in range(n):
            t = i / sr
            val = (50 * math.sin(2 * math.pi * 10 * t)    # alpha
                   + 30 * math.sin(2 * math.pi * 8 * t)    # alpha2
                   + 20 * math.sin(2 * math.pi * 20 * t)   # beta
                   + 15 * math.sin(2 * math.pi * 30 * t)   # beta2
                   + 25 * math.sin(2 * math.pi * 5 * t)    # theta
                   + 10 * math.sin(2 * math.pi * 2 * t)    # delta
                   + random.gauss(0, 20))                    # broad noise
            samples.append(val)
        det.feed(samples)
        self.assertTrue(det.ready())
        detected, freq = det.result()
        self.assertFalse(detected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
