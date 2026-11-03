"""A settings store holding the given values, for an app built with __new__ whose code reads the store."""
from unittest.mock import MagicMock

from app.settings.registry import STR, Setting, SettingsStore
from tests._audio_metric import make_audio_metric


def held_store(**values) -> SettingsStore:
    return SettingsStore(MagicMock(), [Setting(key, value, STR[0], STR[1], None, lambda _v: None)
                                       for key, value in values.items()])


def audio_store(app, metric: str = "shamatha_score", index: int = 0) -> SettingsStore:
    """The app's AudioMetric (`app._audio_metric`) and its settings, holding `metric` (and its slot): what the tick, the
    scoring and the controllers read. The metric in force is shown on the app's Settings screen, a stand-in if it has
    none; a change is held and applied (the store's database is a stand-in, so nothing it persists is read back)."""
    if not hasattr(app, "_settings_screen"):
        app._settings_screen = MagicMock()
    app._audio_metric = make_audio_metric(app, change_setting=lambda key, value: app._settings_store.change(key, value))
    store = app._settings_store = SettingsStore(MagicMock(), app._audio_metric.settings())
    store.change("audio_formula_index", index)
    store.change("audio_metric", metric)
    return store
