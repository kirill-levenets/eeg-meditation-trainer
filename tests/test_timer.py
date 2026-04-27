import unittest

from app.config import APP
from app.session.timer_state import TimerState


class TestTimerState(unittest.TestCase):
    """Headless timer state used by the session tick loop.

    Replaces the old TimerScreen tests — that Screen was orphaned (no nav
    entry, no UI access path) and was removed when the file picker / Test
    Sound / countdown display moved into Settings → Timer.
    """

    def setUp(self):
        self.timer = TimerState()

    def test_default_disabled(self):
        self.assertFalse(self.timer.enabled)

    def test_set_enabled(self):
        self.timer.set_enabled(True)
        self.assertTrue(self.timer.enabled)
        self.timer.set_enabled(False)
        self.assertFalse(self.timer.enabled)

    def test_default_duration(self):
        self.assertEqual(self.timer.duration_minutes, APP.TIMER_DEFAULT_MINUTES)

    def test_set_duration_clamps_to_at_least_one(self):
        self.timer.set_duration(0)
        self.assertEqual(self.timer.duration_minutes, 1)
        self.timer.set_duration(15)
        self.assertEqual(self.timer.duration_minutes, 15)

    def test_tick_returns_false_when_disabled(self):
        self.assertFalse(self.timer.tick(0.5))

    def test_countdown_decrements_remaining(self):
        self.timer.set_enabled(True)
        self.timer.set_duration(1)  # 1 minute
        self.timer.start_countdown()
        self.assertEqual(self.timer.remaining_seconds, 60.0)
        self.assertFalse(self.timer.tick(30.0))
        self.assertEqual(self.timer.remaining_seconds, 30.0)

    def test_timer_expires_when_countdown_reaches_zero(self):
        self.timer.set_enabled(True)
        self.timer.set_duration(1)
        self.timer.start_countdown()
        self.assertTrue(self.timer.tick(61.0))
        self.assertEqual(self.timer.remaining_seconds, 0.0)

    def test_reset_clears_remaining(self):
        self.timer.set_enabled(True)
        self.timer.set_duration(5)
        self.timer.start_countdown()
        self.timer.tick(10.0)
        self.timer.reset()
        self.assertEqual(self.timer.remaining_seconds, 0.0)

    def test_duration_seconds_property(self):
        self.timer.set_duration(20)
        self.assertEqual(self.timer.duration_seconds, 1200.0)

    def test_custom_sound_path_default_empty(self):
        self.assertEqual(self.timer.custom_sound_path, "")

    def test_custom_sound_path_strips_whitespace(self):
        self.timer.set_custom_sound_path("  /tmp/bell.wav  ")
        self.assertEqual(self.timer.custom_sound_path, "/tmp/bell.wav")

    def test_custom_sound_path_handles_none(self):
        self.timer.set_custom_sound_path("")
        self.assertEqual(self.timer.custom_sound_path, "")


if __name__ == "__main__":
    unittest.main()
