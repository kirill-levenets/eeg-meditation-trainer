import os
import threading
import unittest

from app.audio_feedback.noise import (
    AudioEngine,
    _generate_bell_wav,
    _generate_noise_wav,
)
from app.config import APP


class TestAudioFeedback(unittest.TestCase):
    """Test dual-channel audio engine volume computation and lifecycle."""

    def setUp(self):
        self.gen = AudioEngine()

    def tearDown(self):
        self.gen.cleanup()

    def test_volume_at_threshold(self):
        self.gen.set_threshold(50)
        vol = self.gen.compute_volume(50)
        self.assertAlmostEqual(vol, 0.0)

    def test_volume_above_threshold(self):
        self.gen.set_threshold(50)
        vol = self.gen.compute_volume(100)
        self.assertAlmostEqual(vol, 0.0)

    def test_volume_at_zero(self):
        self.gen.set_threshold(50)
        vol = self.gen.compute_volume(0)
        self.assertAlmostEqual(vol, self.gen._max_volume)

    def test_volume_proportional(self):
        self.gen.set_threshold(100)
        vol = self.gen.compute_volume(50)
        # Log curve: volume at half-threshold is above half of max
        self.assertGreater(vol, self.gen._max_volume * 0.5)
        self.assertLess(vol, self.gen._max_volume)

    def test_volume_curve_monotonically_decreasing(self):
        self.gen.set_threshold(100)
        prev_vol = self.gen.compute_volume(0)
        for score in range(10, 110, 10):
            vol = self.gen.compute_volume(score)
            self.assertLessEqual(vol, prev_vol)
            prev_vol = vol

    def test_volume_never_negative(self):
        self.gen.set_threshold(50)
        for score in range(-10, 200, 5):
            vol = self.gen.compute_volume(score)
            self.assertGreaterEqual(vol, 0.0)

    def test_volume_never_exceeds_max(self):
        self.gen.set_threshold(50)
        for score in range(-10, 200, 5):
            vol = self.gen.compute_volume(score)
            self.assertLessEqual(vol, APP.MAX_VOLUME)

    def test_set_threshold_minimum_clamp(self):
        self.gen.set_threshold(0)
        self.assertEqual(self.gen._threshold, 1)

    def test_set_threshold_updates_value(self):
        self.gen.set_threshold(75)
        self.assertEqual(self.gen._threshold, 75)

    def test_update_sets_internal_volume(self):
        self.gen.set_threshold(100)
        self.gen.update(50)
        self.assertGreater(self.gen.volume, self.gen._max_volume * 0.5)
        self.assertLess(self.gen.volume, self.gen._max_volume)

    def test_update_at_threshold_zeroes_volume(self):
        self.gen.set_threshold(50)
        self.gen.update(50)
        self.assertAlmostEqual(self.gen.volume, 0.0)

    def test_initial_state_not_playing(self):
        self.assertFalse(self.gen.is_playing)

    def test_stop_resets_volume(self):
        self.gen.set_threshold(100)
        self.gen.update(25)
        self.assertGreater(self.gen.volume, 0.0)
        self.gen.stop()
        self.assertAlmostEqual(self.gen.volume, 0.0)

    def test_stop_sets_not_playing(self):
        self.gen.stop()
        self.assertFalse(self.gen.is_playing)

    def test_cleanup_idempotent(self):
        self.gen.cleanup()
        self.gen.cleanup()  # should not raise

    def test_volume_with_different_thresholds(self):
        for threshold in [30, 50, 80, 100]:
            self.gen.set_threshold(threshold)
            vol_zero = self.gen.compute_volume(0)
            vol_threshold = self.gen.compute_volume(threshold)
            self.assertAlmostEqual(vol_zero, self.gen._max_volume)
            self.assertAlmostEqual(vol_threshold, 0.0)

    def test_bell_wav_created(self):
        self.assertTrue(os.path.exists(self.gen._bell_path))

    def test_cleanup_removes_temp_files(self):
        bell_path = self.gen._bell_path
        self.gen.cleanup()
        self.assertFalse(os.path.exists(bell_path))
        self.assertIsNone(self.gen._noise_sound)

    def test_update_only_sets_internal_volume(self):
        self.gen.set_threshold(100)
        self.gen.update(50)
        self.assertGreater(self.gen._volume, self.gen._max_volume * 0.5)
        self.assertLess(self.gen._volume, self.gen._max_volume)

    def test_default_threshold_is_100(self):
        gen = AudioEngine()
        self.assertEqual(gen._threshold, 100)
        gen.cleanup()

    def test_sinking_alert_enabled_default(self):
        self.assertTrue(self.gen.sinking_alert_enabled)

    def test_sinking_alert_toggle(self):
        self.gen.sinking_alert_enabled = False
        self.assertFalse(self.gen.sinking_alert_enabled)
        self.gen.sinking_alert_enabled = True
        self.assertTrue(self.gen.sinking_alert_enabled)

    def test_disconnect_alert_toggle(self):
        self.gen.disconnect_alert_enabled = True
        self.assertTrue(self.gen.disconnect_alert_enabled)
        self.gen.disconnect_alert_enabled = False
        self.assertFalse(self.gen.disconnect_alert_enabled)

    def test_generate_noise_wav_silence(self):
        pcm = _generate_noise_wav(0.0, 22050, 1.0)
        self.assertEqual(pcm, b"\x00" * (22050 * 2))

    def test_generate_noise_wav_nonzero(self):
        pcm = _generate_noise_wav(0.5, 22050, 1.0)
        self.assertEqual(len(pcm), 22050 * 2)
        self.assertNotEqual(pcm, b"\x00" * (22050 * 2))

    def test_generate_bell_wav(self):
        pcm = _generate_bell_wav(22050, 800.0, 0.6)
        expected_len = int(22050 * 0.6) * 2
        self.assertEqual(len(pcm), expected_len)

    def test_update_sinking_no_trigger_when_disabled(self):
        self.gen.sinking_alert_enabled = False
        self.gen._is_playing = True
        self.gen.update_sinking(99.0)

    def test_stop_resets_test_active(self):
        self.gen._test_active = True
        self.gen.stop()
        self.assertFalse(self.gen._test_active)

    def test_thread_safe_volume_update(self):
        results = []

        def update_volume():
            for i in range(100):
                self.gen.update(i % 100)
                results.append(self.gen.volume)

        threads = [threading.Thread(target=update_volume) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for v in results:
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
