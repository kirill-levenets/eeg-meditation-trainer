"""The in-app help: in the device's language, the Ukrainian topics mirroring the English, every character drawable."""
import pathlib

import kivy
import pytest

from app import android_jni
from app.ui import settings_screen
from app.ui.settings_screen import _load_help_topics, help_language
from tests._font_glyphs import font_codepoints

HELP_DIR = pathlib.Path(settings_screen.__file__).resolve().parent.parent / "assets" / "help"
FONTS = pathlib.Path(kivy.__path__[0]) / "data" / "fonts"


@pytest.mark.parametrize("name", ["help_en.txt", "help_ua.txt"])
def test_every_help_character_has_a_glyph_in_roboto(name):
    text = (HELP_DIR / name).read_text(encoding="utf-8")
    for font in ("Roboto-Regular.ttf", "Roboto-Bold.ttf"):  # body, and the [b] topic titles
        drawable = font_codepoints(FONTS / font)
        missing = sorted({c for c in text if c not in "\n" and ord(c) not in drawable})
        assert not missing, f"{name} draws as empty boxes in {font}: {missing}"


def test_the_ukrainian_help_has_the_english_topics():
    assert len(_load_help_topics("ua")) == len(_load_help_topics("en")) == 18


@pytest.mark.parametrize("env, lang", [
    ({"LANG": "uk_UA.UTF-8"}, "ua"),
    ({"LANGUAGE": "uk:en", "LANG": "en_US.UTF-8"}, "ua"),  # LANGUAGE's first choice wins
    ({"LC_ALL": "de_DE.UTF-8"}, "de"),  # no help_de.txt: the loader falls back to English
    ({"LANG": "C"}, "c"),
    ({}, "en"),
])
def test_the_help_follows_the_desktop_locale(monkeypatch, env, lang):
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    monkeypatch.setattr(android_jni, "on_android", lambda: False)
    assert help_language() == lang


def test_the_help_follows_the_android_locale_and_falls_back_to_english(monkeypatch):
    monkeypatch.setattr(android_jni, "on_android", lambda: True)
    monkeypatch.setattr(android_jni, "language", lambda: "uk")
    assert help_language() == "ua"

    def jni_fails():
        raise RuntimeError("no JVM")
    monkeypatch.setattr(android_jni, "language", jni_fails)
    assert help_language() == "en"


def test_a_language_without_a_help_file_reads_the_english_help():
    assert _load_help_topics("de") == _load_help_topics("en")
