"""The Kivy providers the app picks itself, before Kivy picks its own."""
import sys

import kivy
from kivy.utils import platform as kivy_platform

from app.logger import logger


def clipboard_without_commands() -> None:
    """Kivy's xclip/xsel probe waits with no timeout; SDL2 reads the Linux clipboard itself, with one."""
    if kivy_platform != "linux":
        return
    if "kivy.core.clipboard" in sys.modules:
        logger.error("Kivy picked its clipboard before the app set its providers: xclip or xsel may hang")
    kivy.kivy_options["clipboard"] = ("sdl2", "dummy")
    kivy.kivy_options["cutbuffer"] = ()  # Kivy's middle-click paste comes only from xclip and xsel
