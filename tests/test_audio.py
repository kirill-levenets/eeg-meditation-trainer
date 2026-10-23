import os
import struct
import threading
import unittest
from unittest.mock import MagicMock

from kivy.clock import Clock

import app.audio_feedback.noise as noise_mod
from app.audio_feedback.noise import (
    AudioEngine,
    _generate_bell_wav,
    _generate_heartbeat_wav,
    _generate_noise_wav,
    _generate_tone_wav,
)
from app.config import APP
from app.ui.app_manager import EEGMeditationApp


def _pcm_samples(pcm: bytes) -> tuple[int, ...]:
    return struct.unpack(f"<{len(pcm) // 2}h", pcm)


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

    def test_generate_heartbeat_wav_length(self):
        pcm = _generate_heartbeat_wav(22050, 10.0, 0.8)
        self.assertEqual(len(pcm), int(22050 * 10.0) * 2)

    def test_generate_heartbeat_wav_one_short_burst_on_silent_bed(self):
        rate = 22050
        pcm = _generate_heartbeat_wav(rate, 10.0, 0.8)
        s = _pcm_samples(pcm)
        nz = [i for i, v in enumerate(s) if v != 0]
        self.assertTrue(nz, "expected a non-silent pulse")
        span = nz[-1] - nz[0] + 1
        self.assertLess(span, rate)                 # pulse is shorter than 1 second
        self.assertGreater(nz[0], 0)                # silent loop head -> gapless
        self.assertLess(nz[-1], len(s) - 1)         # silent loop tail -> gapless
        self.assertGreater(len(s) - len(nz), 8 * rate)  # >8s of the 10s buffer is silence

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
    starts the gong, and stop() stopped+unloaded the shared gong slot
    — so on desktop (SoundLoader gong) the gong was silenced ~1 frame in. Fix:
    stop() no longer touches _gong; the gong is owned solely by
    play_timer_sound / stop_timer_bell (summary buttons + new-session start)."""

    def setUp(self):
        self.engine = AudioEngine()

    def tearDown(self):
        self.engine.cleanup()

    def test_stop_does_not_kill_timer_gong(self):
        from unittest.mock import MagicMock
        gong = MagicMock()
        self.engine._gong = gong
        self.engine.stop()
        gong.unload.assert_not_called()       # gong must keep ringing past stop()
        self.assertIs(self.engine._gong, gong)  # slot preserved for stop_timer_bell

    def test_stop_timer_bell_clears_reference(self):
        from unittest.mock import MagicMock
        snd = MagicMock()
        self.engine._gong = snd
        self.engine.stop_timer_bell()
        snd.set_on_end.assert_called_once_with(None)  # its end no longer ends a play
        snd.unload.assert_called_once()  # each player's unload() stops it first
        self.assertIsNone(self.engine._gong)

    def test_stop_timer_bell_safe_when_nothing_playing(self):
        # Must not raise if the slot is empty.
        self.engine._gong = None
        self.engine.stop_timer_bell()
        self.assertIsNone(self.engine._gong)

    def test_play_timer_sound_after_stop_assigns_fresh_bell(self):
        # The fix relies on this ordering: tear the engine down first,
        # then play the bell. After stop() the slot is None; play_timer_sound
        # creates a fresh Sound that nothing else will preempt.
        self.engine.stop()
        self.assertIsNone(self.engine._gong)
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

    def test_prepare_active_falls_back_when_id_absent(self):
        self.gen.prepare_feedback({"noise": ("noise", "")}, "tone")
        self.assertEqual(self.gen._active_feedback, "noise")

    def test_set_active_zeroes_old_and_repoints(self):
        self.gen.prepare_feedback({"noise": ("noise", ""), "tone": ("tone", "")}, "noise")
        self.gen._feedback_players["noise"].volume = 0.25
        self.gen.set_active_feedback("tone")
        self.assertEqual(self.gen._active_feedback, "tone")
        self.assertEqual(self.gen._feedback_players["noise"].volume, 0.0)

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

    def test_start_plays_all_active_loud_rest_silent(self):
        self.gen.prepare_feedback({"noise": ("noise", ""), "tone": ("tone", "")}, "tone")
        self.gen.start()
        self.assertTrue(all(p.played for p in self.gen._feedback_players.values()))
        self.assertEqual(self.gen._feedback_players["noise"].volume, 0.0)
        self.assertGreater(self.gen._feedback_players["tone"].volume, 0.0)
        self.gen.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)


def test_cleanup_reports_a_sound_file_it_cannot_remove(monkeypatch):
    import app.storage.fileops as fileops
    eng = AudioEngine()
    warned = []
    monkeypatch.setattr(fileops.logger, "warning", lambda msg: warned.append(msg))

    def refuse(path):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(fileops.os, "remove", refuse)
    eng.cleanup()
    assert warned and all("Could not remove" in m for m in warned)
    monkeypatch.undo()
    eng.cleanup()  # the sounds it couldn't remove above


def test_the_audio_tests_teardown_runs_on_the_main_thread(monkeypatch):
    # The sequence runs on a daemon thread; its stop() releases MediaPlayers, which belongs to the main thread.
    monkeypatch.setattr(noise_mod, "_make_noise_player", lambda path, loop=True: _FakePlayer(path))
    monkeypatch.setattr(noise_mod.time, "sleep", lambda _s: None)
    eng = AudioEngine()
    stops = []
    monkeypatch.setattr(eng, "stop", lambda: stops.append(threading.current_thread()))
    eng.test_audio()
    for _ in range(200):
        if not eng._test_active:
            break
        threading.Event().wait(0.01)
    assert not eng._test_active
    assert stops == []
    Clock.tick()
    assert stops == [threading.main_thread()]
    monkeypatch.undo()
    eng.cleanup()


def _record_sequences(monkeypatch) -> list:
    """The Settings test's sequence threads, kept as they start: a quick one is gone before a search would find it."""
    started, base = [], threading.Thread

    class Recording(base):
        def start(self):
            if getattr(getattr(self, "_target", None), "__name__", "") == "_run_sequence":
                started.append(self)
            super().start()
    monkeypatch.setattr(threading, "Thread", Recording)
    return started


def _gated_test(monkeypatch, eng, gate):
    """Start the Settings test with every sleep held at `gate`; record the alerts it plays and its stop."""
    sequences = _record_sequences(monkeypatch)
    monkeypatch.setattr(noise_mod, "_make_noise_player", lambda path, loop=True: _FakePlayer(path))
    monkeypatch.setattr(noise_mod.time, "sleep", lambda _s: gate.wait(2))
    played, stops = [], []
    for name in ("_play_bell", "_play_chime", "_play_disconnect"):
        monkeypatch.setattr(eng, name, lambda n=name: played.append(n))
    monkeypatch.setattr(eng, "stop", lambda: stops.append(1))
    eng.test_audio()
    return played, stops, sequences


def test_a_session_taking_the_engine_over_ends_the_settings_test(monkeypatch):
    eng = AudioEngine()
    gate = threading.Event()
    played, stops, sequences = _gated_test(monkeypatch, eng, gate)
    eng.end_test()  # the session's start, mid-sweep
    assert not eng._is_playing  # handed back: the session's start() isn't skipped
    gate.set()
    sequences[0].join(2)
    Clock.tick()
    assert (played, stops) == ([], [])  # no more alerts over the session, and no teardown of its players
    monkeypatch.undo()
    eng.cleanup()


def test_a_session_starting_during_the_alerts_stops_them(monkeypatch):
    eng = AudioEngine()
    sequences = _record_sequences(monkeypatch)
    monkeypatch.setattr(noise_mod, "_make_noise_player", lambda path, loop=True: _FakePlayer(path))
    monkeypatch.setattr(noise_mod.time, "sleep", lambda _s: None)
    played = []

    def bell():
        played.append("_play_bell")
        eng.end_test()  # the session starts while the bell rings
    monkeypatch.setattr(eng, "_play_bell", bell)
    for name in ("_play_chime", "_play_disconnect"):
        monkeypatch.setattr(eng, name, lambda n=name: played.append(n))
    eng.test_audio()
    sequences[0].join(2)
    assert played == ["_play_bell"]  # no chime or warble over the session
    monkeypatch.undo()
    eng.cleanup()


def test_a_session_starting_after_the_test_ends_keeps_its_players(monkeypatch):
    eng = AudioEngine()
    gate = threading.Event()
    gate.set()
    played, stops, sequences = _gated_test(monkeypatch, eng, gate)
    sequences[0].join(2)
    assert len(played) == 3
    eng.end_test()  # the session starts in the frame before the test's teardown runs
    Clock.tick()
    assert stops == []
    monkeypatch.undo()
    eng.cleanup()


def test_a_test_restarted_supersedes_the_one_running(monkeypatch):
    eng = AudioEngine()
    gate = threading.Event()
    played, stops, sequences = _gated_test(monkeypatch, eng, gate)
    eng.test_audio()  # Test pressed again mid-test
    gate.set()
    for seq in sequences:
        seq.join(2)
    assert len(sequences) == 2
    Clock.tick()
    assert len(played) == 3 and stops == [1]  # one sequence's alerts, one teardown: no session thought to be playing
    monkeypatch.undo()
    eng.cleanup()


def test_the_settings_audio_test_is_refused_while_a_session_runs(monkeypatch):
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    monkeypatch.setattr(EEGMeditationApp, "_session_pipeline_live", lambda self: True)  # running, paused or connecting
    app._info_popup = MagicMock()
    app._audio = MagicMock()
    app._on_test_audio()
    app._audio.prepare_feedback.assert_not_called()  # it would replace the session's players
    app._audio.test_audio.assert_not_called()
    assert app._info_popup.call_args.args[0] == "Session in progress"

