"""The app's SoundSources wired to an app built with __new__, as build() wires it: its context reads the app when used
(tests/_context.py); the audio, timer state and Settings' Timer section are the app's at construction, mocks for the
ones it lacks."""
from unittest.mock import MagicMock

from app.ui.sound_sources import SoundSources
from tests._context import make_context


def make_sounds(app, **ctx_fields) -> SoundSources:
    def attr(value):
        return MagicMock() if value is None else value

    timer_section = getattr(getattr(app, "_settings_screen", None), "timer", None)
    return SoundSources(make_context(app, **ctx_fields), attr(getattr(app, "_audio", None)),
                        attr(getattr(app, "_timer_state", None)), attr(timer_section))
