"""Confirm dialogs must show their whole message on a short (landscape) window; lines that didn't fit were dropped."""

from kivy.base import EventLoop
from kivy.uix.label import Label
from kivy.uix.popup import Popup

from app.ui.app_manager import _BACKUP_SOUND_NOTE, EEGMeditationApp

RESTORE_TEXT = (
    "Replace the ENTIRE database with this backup?\n\n"
    "All 3 profile(s) on this device, with their 120 session(s), settings, programs "
    "and formulas, will be replaced by the backup's.\n"
    f"{_BACKUP_SOUND_NOTE}\n"
    "This cannot be undone."
)


def _pump(n=10):
    for _ in range(n):
        EventLoop.idle()


def _open_confirm(size):
    from kivy.core.window import Window
    EventLoop.ensure_window()
    saved = tuple(Window.size)
    Window.size = size
    _pump()
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._confirm_action("Restore database", RESTORE_TEXT, "Restore", lambda: None)
    _pump()
    popup = next(w for w in Window.children if isinstance(w, Popup))
    label = next(w for w in popup.content.walk() if isinstance(w, Label) and w.text == RESTORE_TEXT)
    return Window, saved, popup, label


def _laid_out_words(label) -> list[str]:
    return [w.text for line in label._label._cached_lines for w in line.words if w.text.strip()]


def test_landscape_confirm_lays_out_every_line_of_the_warning():
    Window, saved, popup, label = _open_confirm((732, 360))
    try:
        laid_out = " ".join(_laid_out_words(label)).split()
        expected = RESTORE_TEXT.split()
        assert laid_out == expected, "some warning lines were not laid out"
        assert label.height >= label.texture_size[1] - 1, "label is shorter than its text"
        assert popup.height <= Window.height, "dialog taller than the window"
    finally:
        popup.dismiss()
        _pump()
        Window.size = saved
        _pump()
