"""Settings → Developer Tools: unhandled exceptions on demand, to check the crash handler's hooks."""

import threading

from kivy.clock import Clock
from kivy.metrics import dp

from app.ui.theme import C, F, ThemedLabel, fit_height_to_text
from app.ui.widgets.styled_button import StyledButton


def _raise(where: str) -> None:
    raise RuntimeError(f"dev-trigger {where}")


def _crash_kivy_event(_btn) -> None:
    _raise("kivy-loop")


def _crash_kivy_clock(_btn) -> None:
    Clock.schedule_once(lambda _dt: _raise("kivy-clock"), 0)


def _crash_thread(_btn) -> None:
    threading.Thread(target=_raise, args=("thread",), daemon=True, name="CrashTestThread").start()


CRASHES = (("Crash: Kivy event", _crash_kivy_event), ("Crash: Kivy clock", _crash_kivy_clock),
           ("Crash: thread", _crash_thread))


class DeveloperSection:
    """Builds the section's content into `section`: a button per place an exception can escape from."""

    def __init__(self, section) -> None:
        desc = ThemedLabel(text="Trigger unhandled exceptions to verify crash-handler hooks.", font_size=F.SMALL,
                           size_hint_y=None, color=C.TEXT_SECONDARY, halign="left")
        fit_height_to_text(desc)
        section.add_widget(desc)
        for text, crash in CRASHES:
            btn = StyledButton(text=text, font_size=F.BODY, bg_color=C.DANGER, size_hint_y=None, height=dp(36))
            btn.bind(on_release=crash)
            section.add_widget(btn)
