"""Android hardware-back (key 27) handling: overlay close / navigate / double-exit."""
import time
import types
import unittest
from unittest import mock

from app.ui.app_manager import EEGMeditationApp


def _app(current="live_session"):
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._sm = types.SimpleNamespace(current=current)
    app._fullscreen_overlay = None
    app._fullscreen_close = None
    app._last_back_time = 0.0
    app._switched = []
    app._diary_back_calls = 0
    app._toasts = []
    app._switch_screen = lambda name: app._switched.append(name)
    app._on_diary_back = lambda: setattr(app, "_diary_back_calls", app._diary_back_calls + 1)
    app._android_toast = lambda msg: app._toasts.append(msg)
    return app


class TestBackButton(unittest.TestCase):
    def _press(self, app, key=27):
        # No modal open by default; stop() patched so the exit path is observable.
        with mock.patch("app.ui.app_manager.Window") as W, \
             mock.patch("app.ui.app_manager.App") as A:
            W.children = []
            stop = mock.Mock()
            A.get_running_app.return_value = types.SimpleNamespace(stop=stop)
            handled = app._on_keyboard(None, key, 0, None, [])
            return handled, stop

    def test_non_back_key_ignored(self):
        app = _app()
        handled, _ = self._press(app, key=97)  # 'a'
        self.assertFalse(handled)
        self.assertEqual(app._toasts, [])

    def test_open_modal_not_intercepted(self):
        app = _app(current="history")
        with mock.patch("app.ui.app_manager.Window") as W, \
             mock.patch("app.ui.app_manager.App"):
            from kivy.uix.modalview import ModalView
            W.children = [ModalView()]
            handled = app._on_keyboard(None, 27, 0, None, [])
        self.assertFalse(handled)  # let the popup dismiss itself
        self.assertEqual(app._switched, [])

    def test_fullscreen_overlay_closes(self):
        app = _app()
        closed = []
        app._fullscreen_overlay = object()
        app._fullscreen_close = lambda: closed.append(True)
        handled, _ = self._press(app)
        self.assertTrue(handled)
        self.assertEqual(closed, [True])

    def test_diary_back(self):
        app = _app(current="diary")
        handled, _ = self._press(app)
        self.assertTrue(handled)
        self.assertEqual(app._diary_back_calls, 1)
        self.assertEqual(app._switched, [])

    def test_history_navigates_to_session(self):
        app = _app(current="history")
        handled, _ = self._press(app)
        self.assertTrue(handled)
        self.assertEqual(app._switched, ["live_session"])

    def test_settings_navigates_to_session(self):
        app = _app(current="settings")
        handled, _ = self._press(app)
        self.assertTrue(handled)
        self.assertEqual(app._switched, ["live_session"])

    def test_root_first_press_toasts_no_exit(self):
        app = _app(current="live_session")
        app._last_back_time = 0.0  # epoch → far in the past
        handled, stop = self._press(app)
        self.assertTrue(handled)
        self.assertEqual(app._toasts, ["Press back again to exit"])
        stop.assert_not_called()
        self.assertGreater(app._last_back_time, 0.0)

    def test_root_double_press_exits(self):
        app = _app(current="live_session")
        app._last_back_time = time.time()  # a press just happened
        handled, stop = self._press(app)
        self.assertTrue(handled)
        stop.assert_called_once()

    def test_root_slow_second_press_does_not_exit(self):
        app = _app(current="live_session")
        app._last_back_time = time.time() - 5.0  # >2s ago
        handled, stop = self._press(app)
        self.assertTrue(handled)
        stop.assert_not_called()
        self.assertEqual(app._toasts, ["Press back again to exit"])


if __name__ == "__main__":
    unittest.main()
