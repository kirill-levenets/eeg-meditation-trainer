"""What a running session's events show on the Session screen, applied by the app and ShownSession: the shamatha pill,
a program segment's line, the BT wait's progress, the warnings over the session and the headset's row."""
import ast
import inspect
import textwrap
import threading

import pytest

import app.session.session_events as session_events
from app.session.manager import elapsed_clock
from app.session.session_events import Connected, SegmentStarted
from app.ui.app_manager import EEGMeditationApp
from app.ui.live_session import LiveSessionScreen
from app.ui.shown_session import ShownSession
from tests._app import (
    FedSession,
    HeadsetSession,
    calls_of,
    frames,
    reload_with,
    start_ticked_by_hand,
    tick_metrics,
)
from tests._program_run import shown_on


def test_a_start_on_the_mock_data_shows_the_session_running_at_once(fresh_app, monkeypatch):
    app, screen = fresh_app, fresh_app._live_screen
    started, chimes = calls_of(monkeypatch, app._audio, "start"), calls_of(monkeypatch, app._audio, "play_connect_sound")
    start_ticked_by_hand(app)
    assert screen._device_label.text == "[Mock EEG] *" and screen._last_state == "Running" and screen._overlay.opacity == 0
    assert started == [()] and chimes == []  # the feedback plays; the connect chime is a headset's


def test_a_start_stops_the_last_gong_and_a_settings_test_still_playing(fresh_app, monkeypatch):
    gongs, tests = calls_of(monkeypatch, fresh_app._audio, "stop_timer_bell"), calls_of(monkeypatch, fresh_app._audio, "end_test")
    start_ticked_by_hand(fresh_app)
    assert gongs == [()] and tests == [()]


def test_an_ending_tears_the_players_down_on_the_main_thread(fresh_app, monkeypatch):
    app, stops = fresh_app, []
    stop = app._audio.stop
    monkeypatch.setattr(app._audio, "stop", lambda: (stops.append(threading.current_thread() is threading.main_thread()),
                                                     stop()))
    FedSession(app, monkeypatch).tick()
    app._stop_and_save()
    frames()
    assert stops == [True] and app._audio._feedback_players == {}


def test_an_ending_tears_the_players_down_even_when_the_screens_part_fails(fresh_app, monkeypatch):
    # Left up, they keep the engine playing: the next session's start would find it so and play no feedback.
    app = fresh_app
    FedSession(app, monkeypatch).tick()
    finalize = app._finalize_stop_ui
    monkeypatch.setattr(app, "_finalize_stop_ui", lambda *_a: (_ for _ in ()).throw(RuntimeError("a screen update")))
    app._stop_and_save()
    with pytest.raises(RuntimeError):
        frames()
    assert app._audio._feedback_players == {}
    finalize(None, None)  # the teardown the failure skipped, for the next test


def test_a_start_whose_screen_part_fails_plays_no_feedback(fresh_app, monkeypatch):
    app = fresh_app
    started = calls_of(monkeypatch, app._audio, "start")
    show = app._shown.show
    monkeypatch.setattr(app._shown, "show", lambda event: (_ for _ in ()).throw(RuntimeError("a screen"))
                        if isinstance(event, Connected) else show(event))
    monkeypatch.setattr(app._session, "start_running", lambda: None)
    with pytest.raises(RuntimeError):
        app._on_start()
    assert started == []
    monkeypatch.undo()
    app._stop_and_save()  # the start got that far: its ending, for the next test
    frames()


def test_an_ending_leaves_the_screen_finished_and_idle(fresh_app, monkeypatch):
    app, screen = fresh_app, fresh_app._live_screen
    reload_with(app, threshold="50")
    fed = FedSession(app, monkeypatch)
    for _ in range(3):
        fed.tick(metrics=tick_metrics(80.0))
    assert screen._shamatha_active and screen._device_label.text == "[Mock EEG] *"
    app._history._history_dirty = False
    screen.update_timer("59:59")  # the clock as a screen lock froze it
    app._stop_and_save()
    frames()
    duration = app._db.get_all_sessions(app._current_user_id)[0]["duration"]
    assert screen._last_state == "FINISHED" and screen._timer_label.text.endswith(elapsed_clock(duration))
    assert not screen._shamatha_active and screen._device_label.text == "[Disconnected]" and app._history._history_dirty


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
