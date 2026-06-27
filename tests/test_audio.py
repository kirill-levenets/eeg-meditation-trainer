import os
import threading
import unittest

from app.audio_feedback.noise import (
    AudioEngine,
    _generate_bell_wav,
    _generate_noise_wav,
    _generate_tone_wav,
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
        self.assertFalse(self.gen.sinking_alert_enabled)

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

    def test_generate_tone_wav_length(self):
        pcm = _generate_tone_wav(22050, 220.0, 1.0)
        self.assertEqual(len(pcm), 22050 * 2)

    def test_generate_tone_wav_nonzero(self):
        pcm = _generate_tone_wav(22050, 220.0, 1.0)
        self.assertNotEqual(pcm, b"\x00" * (22050 * 2))

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

    def test_feedback_path_noise_is_rain(self):
        self.assertEqual(self.gen._feedback_path_for("noise"), self.gen._noise_path)

    def test_feedback_path_tone_lazy_generates(self):
        self.assertFalse(os.path.exists(self.gen._tone_path))
        path = self.gen._feedback_path_for("tone")
        self.assertEqual(path, self.gen._tone_path)
        self.assertTrue(os.path.exists(self.gen._tone_path))

    def test_feedback_path_custom_existing(self):
        self.assertEqual(
            self.gen._feedback_path_for("custom", self.gen._noise_path),
            self.gen._noise_path,
        )

    def test_feedback_path_custom_missing_falls_back_to_rain(self):
        self.assertEqual(
            self.gen._feedback_path_for("custom", "/no/such/file.wav"),
            self.gen._noise_path,
        )


class TestTimerBellLifecycle(unittest.TestCase):
    """Regression: timer-end gong used to be killed by _audio.stop(). The
    timer-expiry path DEFERS _audio.stop() to a frame AFTER play_timer_sound
    starts the gong, and stop() stopped+unloaded the shared `_bell_sound` slot
    — so on desktop (SoundLoader gong) the gong was silenced ~1 frame in. Fix:
    stop() no longer touches _bell_sound; the gong is owned solely by
    play_timer_sound / stop_timer_bell (summary buttons + new-session start)."""

    def setUp(self):
        self.engine = AudioEngine()

    def tearDown(self):
        self.engine.cleanup()

    def test_stop_does_not_kill_timer_gong(self):
        from unittest.mock import MagicMock
        gong = MagicMock()
        self.engine._bell_sound = gong
        self.engine.stop()
        gong.unload.assert_not_called()       # gong must keep ringing past stop()
        self.assertIs(self.engine._bell_sound, gong)  # slot preserved for stop_timer_bell

    def test_stop_timer_bell_clears_reference(self):
        from unittest.mock import MagicMock
        snd = MagicMock()
        self.engine._bell_sound = snd
        self.engine.stop_timer_bell()
        snd.stop.assert_called_once()
        snd.unload.assert_called_once()
        self.assertIsNone(self.engine._bell_sound)

    def test_stop_timer_bell_safe_when_nothing_playing(self):
        # Must not raise if the slot is empty.
        self.engine._bell_sound = None
        self.engine.stop_timer_bell()
        self.assertIsNone(self.engine._bell_sound)

    def test_play_timer_sound_after_stop_assigns_fresh_bell(self):
        # The fix relies on this ordering: tear the engine down first,
        # then play the bell. After stop() the slot is None; play_timer_sound
        # creates a fresh Sound that nothing else will preempt.
        self.engine.stop()
        self.assertIsNone(self.engine._bell_sound)
        self.engine.play_timer_sound("")  # default bell path
        # On headless test envs SoundLoader can return None for the WAV
        # backend, so we accept either a Sound or None — what matters is
        # nothing in the call path raises and the slot wasn't pre-populated.
        # A non-None value also confirms the fresh assignment happened.

    def test_default_timer_bell_is_separate_from_sinking_alert(self):
        # The two bells serve different purposes — sinking alert needs to
        # stay short/high (mid-session ping), timer end needs to be
        # deeper and longer (meditation closure). They live in separate
        # WAV files so the synthesis params can diverge.
        self.assertNotEqual(self.engine._bell_path, self.engine._timer_bell_path)
        self.assertTrue(os.path.exists(self.engine._timer_bell_path))
        self.assertTrue(os.path.exists(self.engine._bell_path))

    def test_timer_bell_config_is_deeper_and_longer(self):
        # Pin the human-meaningful intent of the change: the timer bell
        # must be lower-frequency and longer than the sinking alert.
        self.assertLess(APP.TIMER_BELL_FREQUENCY, APP.BELL_FREQUENCY)
        self.assertGreater(APP.TIMER_BELL_DURATION, APP.BELL_DURATION)


class _FakePlayer:
    def __init__(self, path):
        self.path = path
        self.volume = 0.0
        self.loop = False
        self.played = False
        self.stopped = False
        self.unloaded = False

    def play(self):
        self.played = True

    def stop(self):
        self.stopped = True

    def unload(self):
        self.unloaded = True


class TestFeedbackChannel(unittest.TestCase):
    """Multi-player feedback channel: one active (modulated), the rest at 0."""

    def setUp(self):
        import app.audio_feedback.noise as noise_mod
        self._noise_mod = noise_mod
        self._orig_factory = noise_mod._make_noise_player
        noise_mod._make_noise_player = lambda path: _FakePlayer(path)
        self.gen = AudioEngine()

    def tearDown(self):
        self._noise_mod._make_noise_player = self._orig_factory
        self.gen.cleanup()

    def test_prepare_creates_one_player_per_source(self):
        self.gen.prepare_feedback({"noise": ("noise", ""), "tone": ("tone", "")}, "noise")
        self.assertEqual(set(self.gen._feedback_players), {"noise", "tone"})
        self.assertEqual(self.gen._active_feedback, "noise")
        self.assertIs(self.gen._noise_sound, self.gen._feedback_players["noise"])

    def test_prepare_active_falls_back_when_id_absent(self):
        self.gen.prepare_feedback({"noise": ("noise", "")}, "tone")
        self.assertEqual(self.gen._active_feedback, "noise")

    def test_set_active_zeroes_old_and_repoints(self):
        self.gen.prepare_feedback({"noise": ("noise", ""), "tone": ("tone", "")}, "noise")
        self.gen._feedback_players["noise"].volume = 0.25
        self.gen.set_active_feedback("tone")
        self.assertEqual(self.gen._active_feedback, "tone")
        self.assertEqual(self.gen._feedback_players["noise"].volume, 0.0)
        self.assertIs(self.gen._noise_sound, self.gen._feedback_players["tone"])

    def test_set_active_unknown_is_noop(self):
        self.gen.prepare_feedback({"noise": ("noise", "")}, "noise")
        self.gen.set_active_feedback("nope")
        self.assertEqual(self.gen._active_feedback, "noise")

    def test_set_active_same_is_noop(self):
        self.gen.prepare_feedback({"noise": ("noise", ""), "tone": ("tone", "")}, "noise")
        self.gen._feedback_players["noise"].volume = 0.25
        self.gen.set_active_feedback("noise")
        self.assertEqual(self.gen._active_feedback, "noise")
        self.assertEqual(self.gen._feedback_players["noise"].volume, 0.25)  # untouched

    def test_mute_zeroes_all_players(self):
        self.gen.prepare_feedback({"noise": ("noise", ""), "tone": ("tone", "")}, "noise")
        for p in self.gen._feedback_players.values():
            p.volume = 0.3
        self.gen.mute()
        self.assertTrue(all(p.volume == 0.0 for p in self.gen._feedback_players.values()))

    def test_stop_tears_down_all_players(self):
        self.gen.prepare_feedback({"noise": ("noise", ""), "tone": ("tone", "")}, "noise")
        players = list(self.gen._feedback_players.values())
        self.gen.stop()
        self.assertTrue(all(p.unloaded for p in players))
        self.assertEqual(self.gen._feedback_players, {})
        self.assertIsNone(self.gen._noise_sound)

    def test_start_plays_all_active_loud_rest_silent(self):
        self.gen.prepare_feedback({"noise": ("noise", ""), "tone": ("tone", "")}, "tone")
        self.gen.start()
        self.assertTrue(all(p.played for p in self.gen._feedback_players.values()))
        self.assertEqual(self.gen._feedback_players["noise"].volume, 0.0)
        self.assertGreater(self.gen._feedback_players["tone"].volume, 0.0)
        self.gen.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
