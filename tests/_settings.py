"""A settings store holding the given values, for an app built with __new__ whose code reads the store."""
from unittest.mock import MagicMock

from app.settings.registry import STR, Setting, SettingsStore


def held_store(**values) -> SettingsStore:
    return SettingsStore(MagicMock(), [Setting(key, value, STR[0], STR[1], None, lambda _v: None)
                                       for key, value in values.items()])
