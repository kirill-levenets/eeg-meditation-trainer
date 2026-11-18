"""The marker hotkey: the key picked in Settings › Display places a marker when pressed, a key with no character (F5)
too; while a new one is being picked, no key places one."""
from kivy.core.window import Keyboard, Window

from tests._app import calls_of


def _press(app, key: int, codepoint: str | None = None) -> bool:
    return app._on_key_down(Window, key, 0, codepoint, [])


def _pick(display, key: int, codepoint: str | None = None) -> None:
    display._on_marker_hotkey_pressed()
    display._on_hotkey_capture(Window, key, 0, codepoint, [])


def test_a_hotkey_with_a_character_places_a_marker_and_no_other_key_does(fresh_app, monkeypatch):
    marks = calls_of(monkeypatch, fresh_app._controls, "mark")
    _pick(fresh_app._settings_screen.display, 107, "k")
    assert _press(fresh_app, 107, "k") is True and marks == [()]
    assert _press(fresh_app, 108, "l") is False and marks == [()]


def test_a_hotkey_with_no_character_places_a_marker(fresh_app, monkeypatch):
    f5 = Keyboard.keycodes["f5"]
    marks = calls_of(monkeypatch, fresh_app._controls, "mark")
    _pick(fresh_app._settings_screen.display, f5)
    assert fresh_app._settings_screen.display.marker_hotkey == "f5"
    assert _press(fresh_app, f5) is True and marks == [()]


def test_no_marker_while_a_new_hotkey_is_picked(fresh_app, monkeypatch):
    display = fresh_app._settings_screen.display
    marks = calls_of(monkeypatch, fresh_app._controls, "mark")
    display.marker_hotkey = "m"
    display._on_marker_hotkey_pressed()  # picking: the next key is the new hotkey
    try:
        assert _press(fresh_app, 109, "m") is False and marks == []
    finally:
        display._on_marker_hotkey_clear()


def test_a_key_with_no_character_and_no_name_is_picked_by_its_code_and_matches_no_cleared_hotkey(fresh_app, monkeypatch):
    display, unnamed = fresh_app._settings_screen.display, 9999  # a code Kivy has no name for
    marks = calls_of(monkeypatch, fresh_app._controls, "mark")
    display._on_marker_hotkey_clear()
    assert _press(fresh_app, unnamed) is False and marks == []
    _pick(display, unnamed)
    assert display.marker_hotkey == "9999" and display._marker_hotkey_btn.text == "key 9999"
    assert _press(fresh_app, unnamed) is True and marks == [()]
