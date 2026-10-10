"""Message dialogs must show their whole text on a short (landscape) window; lines that didn't fit were dropped."""

import pytest
from kivy.base import EventLoop
from kivy.uix.label import Label
from kivy.uix.popup import Popup

from app.ui.app_manager import _BACKUP_SOUND_NOTE, EEGMeditationApp

RESTORE_TEXT = (
    "Replace the ENTIRE database with this backup?\n\n"
    "Everything on this device (3 profiles, 120 sessions, settings, programs "
    "and formulas) will be replaced by the backup's.\n"
    f"{_BACKUP_SOUND_NOTE}\n"
    "This cannot be undone."
)
BACKUP_SAVED_TEXT = (
    "Saved to:\n/home/someone/.local/share/EEGMeditation/backups/eeg_backup_carl_2026-09-29_17-49.db"
    f"\n\n{_BACKUP_SOUND_NOTE}"
)
PROFILE_DELETE_TEXT = (
    'Delete profile "test"?\n\n'
    "Its 12 sessions and all its settings will be permanently deleted.\n"
    "This cannot be undone."
)


def _pump(n=10):
    for _ in range(n):
        EventLoop.idle()


def _laid_out_words(label) -> list[str]:
    return [w.text for line in label._label._cached_lines for w in line.words if w.text.strip()]


def _open_profile_delete(_text):
    from app.ui.settings_screen import SettingsScreen
    screen = SettingsScreen()
    screen.set_session_counter(lambda uid: 12)
    screen._confirm_user_delete(5, "test")


@pytest.mark.parametrize(("open_dialog", "text"), [
    (lambda t: EEGMeditationApp.__new__(EEGMeditationApp)._confirm_action(
        "Restore database", t, "Restore", lambda: None), RESTORE_TEXT),
    (lambda t: EEGMeditationApp.__new__(EEGMeditationApp)._info_popup("Backup saved", t), BACKUP_SAVED_TEXT),
    (_open_profile_delete, PROFILE_DELETE_TEXT),
])
def test_landscape_dialog_lays_out_every_line(open_dialog, text):
    from kivy.core.window import Window
    EventLoop.ensure_window()
    saved = tuple(Window.size)
    Window.size = (732, 360)
    _pump()
    open_dialog(text)
    _pump()
    popup = next(w for w in Window.children if isinstance(w, Popup))
    try:
        label = next(w for w in popup.content.walk() if isinstance(w, Label) and w.text == text)
        laid_out = " ".join(_laid_out_words(label)).split()
        assert laid_out == text.split(), "some lines were not laid out"
        assert label.height >= label.texture_size[1] - 1, "label is shorter than its text"
        assert popup.height <= Window.height, "dialog taller than the window"
    finally:
        popup.dismiss()
        _pump()
        Window.size = saved
        _pump()
