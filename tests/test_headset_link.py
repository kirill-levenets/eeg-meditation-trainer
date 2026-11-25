"""The headset's label on the Session screen and its status line in Settings show the stream's link, also outside a
session: the link outlives sessions, and its reader reconnects or gives up on its own."""
import pytest
from kivy.clock import Clock

from app.eeg.neurosky_stream import NeuroSkyStream
from tests._app import HEADSET, HeadsetSession, calls_of, frames, start_connecting


class Link:
    """The real stream's link as the test sets it (`up`), outside a session."""

    def __init__(self, monkeypatch, up: bool = False) -> None:
        self.up = up
        monkeypatch.setattr(NeuroSkyStream, "is_connected", property(lambda _stream: self.up))


def _shown(app) -> tuple[str, str, str]:
    """(the Session screen's headset label, Settings › Device's status line, the line under it)."""
    device = app._settings_screen.device
    return (app._live_screen.header._device_label.text, device._device_status_label.text,
            device._device_meta_label.text)


def _watch(app) -> None:
    """One run of the headset's link watch, as its 1 s Clock interval runs it."""
    app._headset._watch_link(1.0)


def _real_mode(app) -> None:
    app._user_settings.change("use_mock", False)
    app._real_stream.set_device(*HEADSET)


NAME = HEADSET[1]
CONNECTED = (f"[{NAME}] *", f"Connected: {NAME}", "Mode: Real Device")
NOT_CONNECTED = (f"[{NAME}]", "Not connected", f"Selected: {NAME}")


def test_a_session_that_ended_with_its_link_up_shows_the_headset_connected(fresh_app, monkeypatch):
    session = HeadsetSession(fresh_app, monkeypatch)
    session.tick()
    assert _shown(fresh_app) == CONNECTED
    fresh_app._session.timer.set_enabled(True)
    fresh_app._session.timer.remaining_seconds = 0.1
    session.tick()
    frames()
    assert not fresh_app._session.live()
    assert _shown(fresh_app) == CONNECTED  # the link is kept: the next Start begins at once


def test_after_a_session_the_labels_follow_the_link_dropping_and_coming_back(fresh_app, monkeypatch):
    session = HeadsetSession(fresh_app, monkeypatch)
    session.tick()
    fresh_app._session.timer.set_enabled(True)
    fresh_app._session.timer.remaining_seconds = 0.1
    session.tick()
    frames()
    session.connected = False  # the headset switched off: its reader gives up
    _watch(fresh_app)
    assert _shown(fresh_app) == NOT_CONNECTED
    session.connected = True  # the reader reconnected
    _watch(fresh_app)
    assert _shown(fresh_app) == CONNECTED


def test_a_link_that_comes_up_outside_a_session_shows(fresh_app, monkeypatch):
    link = Link(monkeypatch)
    _real_mode(fresh_app)
    fresh_app._headset.show_selected()
    assert _shown(fresh_app) == NOT_CONNECTED
    link.up = True
    _watch(fresh_app)
    assert _shown(fresh_app) == CONNECTED


def test_a_cancelled_start_shows_the_headset_as_it_is_not_disconnected(fresh_app, monkeypatch):
    Link(monkeypatch)
    start_connecting(fresh_app, monkeypatch)
    frames()
    assert fresh_app._live_screen.header._device_label.text == f"[{NAME}] ..."
    fresh_app._controls.cancel()
    frames()
    assert _shown(fresh_app) == NOT_CONNECTED


def test_while_a_start_waits_for_the_headset_the_watch_leaves_its_label_to_the_session(fresh_app, monkeypatch):
    link = Link(monkeypatch)
    start_connecting(fresh_app, monkeypatch)
    frames()
    link.up = True  # connected, its first data not in yet: the session's wait shows it
    _watch(fresh_app)
    assert fresh_app._live_screen.header._device_label.text == f"[{NAME}] ..."
    fresh_app._controls.cancel()
    frames()


def test_a_profile_picked_with_its_headset_still_linked_shows_it_connected(fresh_app, monkeypatch):
    Link(monkeypatch, up=True)
    uid = fresh_app._db.create_user("Linked")
    fresh_app._db.set_user_setting(uid, "bt_device_address", HEADSET[0])
    fresh_app._db.set_user_setting(uid, "bt_device_name", NAME)
    fresh_app._db.set_user_setting(uid, "use_mock", "False")
    fresh_app._activate_user(uid)
    assert _shown(fresh_app) == CONNECTED


@pytest.mark.parametrize("up", [False, True])
def test_the_mode_switch_shows_the_link_in_real_mode_and_the_mock_in_mock_mode(fresh_app, monkeypatch, up):
    Link(monkeypatch, up=up)
    fresh_app._real_stream.set_device(*HEADSET)
    fresh_app._settings_screen.device._device_mode_cb.active = False
    assert _shown(fresh_app) == (CONNECTED if up else NOT_CONNECTED)
    fresh_app._settings_screen.device._device_mode_cb.active = True
    assert _shown(fresh_app) == ("[Mock EEG]", "Not connected", f"Saved device: {NAME}")


def test_in_mock_mode_the_watch_leaves_the_labels_alone(fresh_app, monkeypatch):
    link = Link(monkeypatch)
    fresh_app._real_stream.set_device(*HEADSET)
    fresh_app._headset.show_selected()
    shown = _shown(fresh_app)
    repaints = calls_of(monkeypatch, fresh_app._settings_screen.device, "update_device_status")
    link.up = True  # a link kept from a real session: the mock is in use
    _watch(fresh_app)
    assert _shown(fresh_app) == shown == ("[Mock EEG]", "Not connected", f"Saved device: {NAME}")
    assert repaints == []  # nor repaints them every second


def test_the_watch_runs_every_second_on_the_clock(fresh_app):
    watches = [e for e in Clock.get_events() if e.get_callback() == fresh_app._headset._watch_link]
    assert len(watches) == 1 and watches[0].timeout == 1.0


def test_the_watch_repaints_nothing_while_the_link_stays_as_shown(fresh_app, monkeypatch):
    Link(monkeypatch, up=True)
    _real_mode(fresh_app)
    fresh_app._headset.show_selected()
    repaints = calls_of(monkeypatch, fresh_app._settings_screen.device, "update_device_status")
    _watch(fresh_app)
    assert repaints == []
