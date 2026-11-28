"""The Session screen's duration picker: its label follows the timer, a preset picked reaches the app and closes the
popup, and Programs… lists the saved programs, the one picked reaching the app by its index."""
import pytest
from kivy.core.window import Window
from kivy.tests.common import UnitTestTouch
from kivy.uix.modalview import ModalView

from app.ui.session_sections.duration_picker import DurationPicker
from tests._app import frames, frames_until, tap


def _open_popups() -> list[ModalView]:
    return [w for w in Window.children if isinstance(w, ModalView)]


def _popups_after(action, count: int) -> list[ModalView]:
    """The popups open once `action` opened or closed them (a closing one stays in the window while it fades)."""
    action()
    frames_until(lambda: len(_open_popups()) == count)
    return _open_popups()


def _tap(button) -> None:
    t = UnitTestTouch(*button.to_window(*button.center))
    t.touch_down()
    t.touch_up()


@pytest.fixture
def picker():
    picker, picked = DurationPicker(), []
    picker.on_preset = lambda minutes: picked.append(("preset", minutes))
    picker.on_program_pick = lambda index: picked.append(("program", index))
    Window.add_widget(picker.button)
    yield picker, picked
    for popup in _open_popups():
        popup.dismiss(animation=False)
    Window.remove_widget(picker.button)
    frames()


@pytest.mark.parametrize("timer, label", [((False, 30), "∞"), ((True, 90), "90m"), ((True, 120), "2h"),
                                          ((True, 20, True), "P")])
def test_the_button_shows_the_timer_or_a_program(picker, timer, label):
    picker[0].refresh(*timer)
    assert picker[0].button.text == label


def test_a_preset_picked_reaches_the_app_and_closes_the_popup(picker):
    picker_, picked = picker
    [popup] = _popups_after(lambda: _tap(picker_.button), 1)
    assert _popups_after(lambda: tap(popup, "10 min"), 0) == [] and picked == [("preset", 10)]
    [popup] = _popups_after(lambda: _tap(picker_.button), 1)
    _popups_after(lambda: tap(popup, "Free"), 0)
    assert picked == [("preset", 10), ("preset", None)]


def test_programs_lists_the_saved_ones_and_the_one_picked_reaches_the_app(picker):
    picker_, picked = picker
    picker_.set_programs([{"name": "Morning"}, {"name": "Evening"}], "Evening")
    [durations] = _popups_after(lambda: _tap(picker_.button), 1)
    [programs] = _popups_after(lambda: tap(durations, "Program: Evening"), 1)  # the durations gave way to the list
    assert programs is not durations
    assert _popups_after(lambda: tap(programs, "Morning"), 0) == [] and picked == [("program", 0)]


@pytest.mark.parametrize("timer, filled", [((True, 20), "20 min"), ((False, 20), "Free")])
def test_the_popup_fills_the_duration_set(picker, monkeypatch, timer, filled):
    import app.ui.session_sections.duration_picker as module
    shown = []
    monkeypatch.setattr(module, "make_scroll_popup", lambda title, rows, **k: shown.extend(rows) or type(
        "P", (), {"open": lambda self: None, "dismiss": lambda self: None})())
    p, _picked = picker
    p.refresh(*timer)
    p._open_popup()
    buttons = [w for row in shown for w in row.walk() if hasattr(w, "bg_color") and getattr(w, "text", "")]
    from app.ui.theme import C
    assert [b.text for b in buttons if tuple(b.bg_color) == tuple(C.ACCENT)] == [filled]
