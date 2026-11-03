"""Every BT-wait exit stops the tick watcher before the stream, which it would read as a failed connect."""

import time
from unittest.mock import MagicMock

import app.ui.app_manager as am
import app.ui.bt_wait as bt_wait
from app.session.manager import SessionManager
from app.session.session_run import Phase, SessionRun
from app.ui.app_manager import EEGMeditationApp
from app.ui.bt_wait import BtWait, WaitEnd
from tests._bt_wait import make_bt_wait
from tests._headset import make_headset
from tests._program_run import make_run
from tests._session_run import run_in
from tests._shown_session import make_shown


def _make_waiting_app() -> tuple[EEGMeditationApp, list]:
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    events: list = []
    run_in(app, Phase.CONNECTING).signal_start = 123.0
    app._ticker = MagicMock(running=True)

    def stop_tick():
        events.append("tick_stopped")
        app._ticker.running = False

    app._ticker.stop.side_effect = stop_tick
    app._real_stream = MagicMock()
    app._real_stream.stop.side_effect = lambda: events.append(
        ("stream_stopped", app._connecting(), app._ticker.running)
    )
    app._eeg_stream = app._real_stream
    app._keep_awake = MagicMock()
    app._live_screen = MagicMock()
    app._settings_screen = MagicMock()
    app._timer_state = MagicMock()
    app._session_manager = SessionManager()  # idle: the session starts only when data arrives
    app._program_run = make_run(app)
    app._headset = make_headset(app)
    app._bt_wait = make_bt_wait(app)
    app._shown = make_shown(app)
    return app, events


def _assert_unwatched_stream_stop(app: EEGMeditationApp, events: list) -> None:
    assert events == ["tick_stopped", ("stream_stopped", False, False)]
    assert not app._connecting()
    # Released by the abort itself (on the tick thread for a wait exit), and again by a cancel's shared teardown.
    app._keep_awake.release.assert_called()


def test_connect_cancel_stops_watcher_before_stream():
    app, events = _make_waiting_app()
    app._on_connect_cancel()
    _assert_unwatched_stream_stop(app, events)
    assert app._run is None  # the start's run ended with it


def test_stop_during_bt_wait_stops_watcher_before_stream():
    app, events = _make_waiting_app()
    app._on_stop()
    _assert_unwatched_stream_stop(app, events)
    assert app._run is None
    app._live_screen.hide_overlay.assert_called_once()


def test_app_init_defines_bt_wait_state(monkeypatch):
    """Cancel before any session (e.g. during the device scan) read an attribute only Start created."""
    monkeypatch.setattr(am, "DatabaseManager", MagicMock())
    monkeypatch.setattr(am, "AudioEngine", MagicMock())
    app = am.EEGMeditationApp()
    assert app._run is None and not app._connecting()

    app._live_screen = MagicMock()  # built by build(), which runs before any UI action
    app._settings_screen = MagicMock()
    app._timer_state = MagicMock()
    app._program_run = make_run(app)
    app._on_connect_cancel()  # must not raise


def test_failed_connect_exit_releases_wake_lock_and_service():
    app, events = _make_waiting_app()
    app._run.connect_start = time.time()
    app._real_stream.is_connected = False
    app._real_stream._running = False
    app._real_stream._device_name = "MindWave"
    app._real_stream._last_connect_error = "Headset is asleep or off."
    app._on_main = MagicMock()
    app._bt_wait._report_connect_failure = MagicMock()

    app._follow_bt_wait(app._run)

    _assert_unwatched_stream_stop(app, events)
    assert app._run.phase is Phase.ENDED  # its teardown is queued for the main thread
    app._bt_wait._report_connect_failure.assert_called_once()


def test_refused_start_undoes_setup_without_entering_the_wait():
    app, _ = _make_waiting_app()
    app._run.phase = Phase.STARTING  # Start pressed, the wait not begun
    app._real_stream.start.return_value = False
    app._real_stream._device_name = "MindWave"
    app._real_stream._last_connect_error = "Previous connection is still closing."
    app._bt_wait._report_connect_failure = MagicMock()

    assert app._begin_bt_wait(app._run) is False

    assert not app._connecting()
    app._keep_awake.release.assert_called_once()
    shown = app._live_screen.show_overlay_retry.call_args.args[0]
    assert "still closing" in shown
    app._bt_wait._report_connect_failure.assert_not_called()


def test_started_stream_enters_the_wait():
    app, _ = _make_waiting_app()
    app._run.phase = Phase.STARTING  # Start pressed, the wait not begun
    app._real_stream.start.return_value = True
    app._real_stream._device_name = "MindWave"

    assert app._begin_bt_wait(app._run) is True

    assert app._connecting()
    app._live_screen.show_overlay.assert_called_once()
    app._keep_awake.release.assert_not_called()


def test_a_failed_connect_is_reported_with_its_headset_and_hint(monkeypatch):
    reports = []
    monkeypatch.setattr(bt_wait, "report_soft_error", lambda label, detail="", **_k: reports.append((label, detail)))
    stream = MagicMock(is_connected=False, _running=False, _device_address="AA:BB",
                       _last_connect_error="Headset is asleep or off.")
    wait = BtWait(stream, MagicMock(), headset_name=lambda: "MWM2", on_main_for=lambda run, fn: None)
    run = SessionRun(1)
    run.connect_start = time.time()
    assert wait.tick(run) == WaitEnd(False, "Connection to MWM2 failed.\nHeadset is asleep or off.")
    (label, detail), = reports
    assert label == "bt_connect_failed" and "MWM2 (AA:BB)" in detail and "Headset is asleep or off." in detail
