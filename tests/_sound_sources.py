"""A SoundSources on its own, for the sound-source tests."""
from unittest.mock import MagicMock

from app.ui.sound_sources import SoundSources
from tests._context import stub_context


def sounds_alone(settings: dict | None = None, *, audio=None, timer_state=None, timer_section=None,
                 **ctx_fields) -> SoundSources:
    """Its context a stub that reads the profile's `settings`; mocks for the parts not given."""
    ctx = stub_context(**{"setting": lambda key: (settings or {})[key], **ctx_fields})
    return SoundSources(ctx, audio or MagicMock(), timer_state or MagicMock(), timer_section or MagicMock())
