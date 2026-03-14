import unittest

from app.config import APP
from app.ui.timer_screen import TimerScreen


class TestTimerScreen(unittest.TestCase):
    """Test meditation timer functionality."""

    def setUp(self):
        self.timer = TimerScreen()

    def test_default_disabled(self):
        self.assertFalse(self.timer.enabled)

    def test_enable_toggle(self):
        self.timer._enable_cb.active = True
        self.assertTrue(self.timer.enabled)

    def test_duration_default(self):
        self.assertEqual(self.timer._duration_minutes, APP.TIMER_DEFAULT_MINUTES)

    def test_set_duration(self):
        self.timer._set_duration(30)
        self.assertEqual(self.timer._duration_minutes, 30)

    def test_tick_returns_false_when_disabled(self):
        self.assertFalse(self.timer.tick(0.5))

    def test_countdown(self):
        self.timer._enable_cb.active = True
        self.timer._set_duration(1)  # 1 minute
        self.timer.start_countdown()
        self.assertEqual(self.timer._remaining_seconds, 60.0)
        expired = self.timer.tick(30.0)
        self.assertFalse(expired)
        self.assertEqual(self.timer._remaining_seconds, 30.0)

    def test_timer_expires(self):
        self.timer._enable_cb.active = True
        self.timer._set_duration(1)
        self.timer.start_countdown()
        expired = self.timer.tick(61.0)
        self.assertTrue(expired)

    def test_reset(self):
        self.timer._enable_cb.active = True
        self.timer._set_duration(5)
        self.timer.start_countdown()
        self.timer.tick(10.0)
        self.timer.reset()
        self.assertEqual(self.timer._remaining_seconds, 0.0)

    def test_duration_seconds_property(self):
        self.timer._set_duration(20)
        self.assertEqual(self.timer.duration_seconds, 1200.0)

    def test_custom_sound_path_default_empty(self):
        self.assertEqual(self.timer.custom_sound_path, "")

    def test_custom_sound_path_set(self):
        self.timer._sound_path_input.text = "/tmp/bell.wav"
        self.assertEqual(self.timer.custom_sound_path, "/tmp/bell.wav")

    def test_test_sound_callback(self):
        called = []
        self.timer.set_test_sound_callback(lambda: called.append(True))
        self.timer._on_test_sound_pressed()
        self.assertEqual(len(called), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
