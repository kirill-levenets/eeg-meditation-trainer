import unittest

from app.ui.app_manager import EEGMeditationApp
from app.ui.widgets.loading_overlay import LoadingOverlay


class TestLoadingOverlay(unittest.TestCase):
    def test_starts_hidden(self):
        ov = LoadingOverlay()
        self.assertEqual(ov.opacity, 0)
        self.assertEqual(tuple(ov.size_hint), (0, 0))
        self.assertFalse(ov.is_visible)

    def test_show_makes_visible_and_sets_text(self):
        ov = LoadingOverlay()
        ov.show("Loading session")
        self.assertEqual(ov.opacity, 1)
        self.assertEqual(tuple(ov.size_hint), (1, 1))
        self.assertEqual(ov._status.text, "Loading session")
        self.assertTrue(ov.is_visible)
        self.assertIsNotNone(ov._dot_event)
        ov.hide()

    def test_update_only_when_visible(self):
        ov = LoadingOverlay()
        ov.update("ignored while hidden")
        self.assertEqual(ov._status.text, "")
        ov.show("first")
        ov.update("second")
        self.assertEqual(ov._status.text, "second")
        ov.hide()

    def test_hide_collapses_and_cancels_animation(self):
        ov = LoadingOverlay()
        ov.show("x")
        ov.hide()
        self.assertEqual(ov.opacity, 0)
        self.assertEqual(tuple(ov.size_hint), (0, 0))
        self.assertIsNone(ov._dot_event)
        self.assertFalse(ov.is_visible)

    def test_hide_before_show_is_safe(self):
        ov = LoadingOverlay()
        ov.hide()  # must not raise
        self.assertIsNone(ov._dot_event)

    def test_blocks_touches_while_visible(self):
        ov = LoadingOverlay()

        class _T:
            pos = (10, 10)
            x = 10
            y = 10

        self.assertFalse(ov.on_touch_down(_T()))  # hidden: passes through
        ov.show("x")
        self.assertTrue(ov.on_touch_down(_T()))  # visible: swallowed
        ov.hide()


class TestAppLoadingDelegation(unittest.TestCase):
    def test_show_hide_delegate_to_overlay(self):
        app = EEGMeditationApp.__new__(EEGMeditationApp)
        app._loading_overlay = LoadingOverlay()
        app.show_loading("Crunching")
        self.assertTrue(app._loading_overlay.is_visible)
        self.assertEqual(app._loading_overlay._status.text, "Crunching")
        app.hide_loading()
        self.assertFalse(app._loading_overlay.is_visible)

    def test_show_hide_safe_without_overlay(self):
        app = EEGMeditationApp.__new__(EEGMeditationApp)
        app.show_loading("x")  # no _loading_overlay attribute — must not raise
        app.hide_loading()
