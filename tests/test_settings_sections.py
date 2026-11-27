"""Settings' small folds act on their own controls: the threshold's steps and presets stay in the slider's range, Data
Backup's buttons report through their hooks, and each Developer Tools button raises where it says."""
import threading

import pytest
from kivy.clock import Clock

from app.ui.hooks import wire
from app.ui.settings_screen import SettingsScreen
from app.ui.settings_sections.developer import CRASHES


@pytest.fixture(scope="module")
def screen():
    return SettingsScreen()


def _steps(screen):
    """The threshold's -/+ buttons and its presets, as the fold shows them."""
    slider_row, presets = screen.threshold._controls
    minus, _slider, _label, plus = reversed(slider_row.children)
    return minus, plus, presets.buttons()


def test_the_threshold_steps_by_five_and_stops_at_the_slider_s_ends(screen):
    minus, plus, _presets = _steps(screen)
    screen.threshold.value = 22
    minus.dispatch("on_release")
    assert screen.threshold.value == 20  # the slider's minimum, not 17
    minus.dispatch("on_release")
    assert screen.threshold.value == 20
    screen.threshold.value = 178
    plus.dispatch("on_release")
    assert screen.threshold.value == 180  # its maximum
    minus.dispatch("on_release")
    assert screen.threshold.value == 175


def test_a_threshold_preset_sets_the_slider_and_reports_the_value(screen):
    reported = []
    wire(screen.threshold, on_change=reported.append)
    _minus, _plus, presets = _steps(screen)
    presets[130].dispatch("on_release")
    assert screen.threshold.value == 130 and reported[-1] == 130
    wire(screen.threshold, on_change=None)


def test_data_backup_s_buttons_report_their_action(screen):
    pressed = []
    wire(screen.backup, on_backup=lambda: pressed.append("backup"), on_restore=lambda: pressed.append("restore"))
    buttons = {w.text: w for w in screen.backup._status.parent.children if hasattr(w, "bg_color")}
    buttons["Backup database"].dispatch("on_release")
    buttons["Restore database"].dispatch("on_release")
    assert pressed == ["backup", "restore"]
    wire(screen.backup, on_backup=None, on_restore=None)


def _crash_button(screen, text):
    section = next(w for w in screen.walk() if type(w).__name__ == "_AccordionSection"
                   and w._header.text == "Developer Tools")
    section.open()  # a folded section's content is detached
    return next(w for w in section.walk(restrict=True) if getattr(w, "text", "") == text)


def test_each_developer_button_raises_where_it_says(screen, monkeypatch):
    assert [text for text, _crash in CRASHES] == ["Crash: Kivy event", "Crash: Kivy clock", "Crash: thread"]
    with pytest.raises(RuntimeError, match="dev-trigger kivy-loop"):
        _crash_button(screen, "Crash: Kivy event").dispatch("on_release")
    _crash_button(screen, "Crash: Kivy clock").dispatch("on_release")
    with pytest.raises(RuntimeError, match="dev-trigger kivy-clock"):
        Clock.tick()
    caught = []
    monkeypatch.setattr(threading, "excepthook", lambda args: caught.append((args.thread.name, str(args.exc_value))))
    _crash_button(screen, "Crash: thread").dispatch("on_release")
    for thread in threading.enumerate():
        if thread.name == "CrashTestThread":
            thread.join(2.0)
    assert caught == [("CrashTestThread", "dev-trigger thread")]


def test_an_alert_with_no_engine_switch_fails_at_registration_naming_the_fix(fresh_app, monkeypatch):
    alerts = fresh_app._settings_screen.audio.alerts
    monkeypatch.setitem(alerts, "bogus_alert", alerts["sinking_alert"])  # a row added to ALERTS, no engine property
    with pytest.raises(AttributeError, match="AudioEngine has no bogus_alert_enabled: each alert in"):
        fresh_app._alert_settings()
