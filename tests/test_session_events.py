"""What a running session's events show on the Session screen, applied by the app and ShownSession: the shamatha pill,
a program segment's line, the BT wait's progress, the warnings over the session and the headset's row."""
import ast
import inspect
import textwrap

import app.session.session_events as session_events
from app.session.session_events import SegmentStarted
from app.ui.app_manager import EEGMeditationApp
from app.ui.live_session import LiveSessionScreen
from app.ui.shown_session import ShownSession
from tests._app import FedSession, HeadsetSession, reload_with, tick_metrics
from tests._program_run import shown_on


def test_the_shamatha_pill_lights_after_three_ticks_above_the_threshold(fresh_app, monkeypatch):
    reload_with(fresh_app, threshold="50")
    fed = FedSession(fresh_app, monkeypatch)
    for shown in (False, False, True):
        fed.tick(metrics=tick_metrics(80.0))
        assert fresh_app._live_screen._shamatha_active is shown


def test_a_custom_segment_shows_its_line_again_after_it_was_hidden():
    screen = LiveSessionScreen()
    screen.graph.set_visible("program_formula", False)  # hidden through the picker during the session
    shown_on(screen).show(SegmentStarted("program_formula", "Program: Alpha"))
    assert screen.graph.is_visible("program_formula") and screen.graph.series_name("program_formula") == "Program: Alpha"


def test_the_bt_wait_shows_its_progress_on_the_overlay(fresh_app, monkeypatch):
    wait = HeadsetSession(fresh_app, monkeypatch, start=False)
    wait.connected, wait.since_packet = True, 0.0  # linked, no packet yet
    wait.tick()
    assert "Waiting for EEG data" in fresh_app._live_screen._overlay_status.text


def test_a_low_headset_battery_is_shown_over_the_session(fresh_app, monkeypatch):
    fed = FedSession(fresh_app, monkeypatch)
    fed.tick(raw={**fed.raw, "battery": 10})
    assert fresh_app._live_screen._alert_label.text == "Low headset battery (7%)."


def test_a_link_dropped_mid_session_shows_the_headset_reconnecting(fresh_app, monkeypatch):
    session = HeadsetSession(fresh_app, monkeypatch)
    session.tick()  # the session's first tick follows the link: up
    label = fresh_app._live_screen._device_label
    assert label.text.endswith("] *")
    session.connected = False
    session.tick()
    assert label.text.endswith("] ...")


def _handled(function) -> set[str]:
    """The classes the function's match statement has a case for."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    return {node.cls.id for node in ast.walk(tree) if isinstance(node, ast.MatchClass)}


def test_every_session_event_has_a_handler():
    # The app hands what it doesn't handle to ShownSession: an event neither names would be dropped.
    events = {name for name, value in vars(session_events).items()
              if inspect.isclass(value) and value.__module__ == session_events.__name__}
    assert events - (_handled(EEGMeditationApp._on_session_event) | _handled(ShownSession.show)) == set()
