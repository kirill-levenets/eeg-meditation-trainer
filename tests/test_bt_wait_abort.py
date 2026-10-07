"""Every BT-wait exit stops the tick watcher before the stream, which it would read as a failed connect."""

import time
from unittest.mock import MagicMock

import app.ui.app_manager as am
from app.session.manager import SessionManager
from app.ui.app_manager import EEGMeditationApp


def _make_waiting_app() -> tuple[EEGMeditationApp, list]:
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    events: list = []
    app._waiting_for_bt = True
    app._bt_signal_start = 123.0
    app._tick_thread = MagicMock()

    def stop_tick():
        events.append("tick_stopped")
        app._tick_thread = None

    app._stop_tick_thread = stop_tick
    app._real_stream = MagicMock()
    app._real_stream.stop.side_effect = lambda: events.append(
        ("stream_stopped", app._waiting_for_bt, app._tick_thread)
    )
    app._eeg_stream = app._real_stream
    app._release_wake_lock = MagicMock()
    app._stop_session_keep_alive_service = MagicMock()
    app._live_screen = MagicMock()
    app._settings_screen = MagicMock()
    app._timer_state = MagicMock()
    app._session_manager = SessionManager()  # idle: the session starts only when data arrives
    return app, events


def _assert_unwatched_stream_stop(app: EEGMeditationApp, events: list) -> None:
    assert events == ["tick_stopped", ("stream_stopped", False, None)]
    assert app._bt_signal_start is None
    # Released by the abort itself (on the tick thread for a wait exit), and again by a cancel's shared teardown.
    app._release_wake_lock.assert_called()
    app._stop_session_keep_alive_service.assert_called()


def test_connect_cancel_stops_watcher_before_stream():
    app, events = _make_waiting_app()
    app._on_connect_cancel()
    _assert_unwatched_stream_stop(app, events)


def test_stop_during_bt_wait_stops_watcher_before_stream():
    app, events = _make_waiting_app()
    app._on_stop()
    _assert_unwatched_stream_stop(app, events)
    app._live_screen.hide_overlay.assert_called_once()


def test_app_init_defines_bt_wait_state(monkeypatch):
    """Cancel before any session (e.g. during the device scan) read an attribute only Start created."""
    monkeypatch.setattr(am, "DatabaseManager", MagicMock())
    monkeypatch.setattr(am, "AudioEngine", MagicMock())
    app = am.EEGMeditationApp()
    assert app._waiting_for_bt is False
    assert app._bt_signal_start is None

    app._live_screen = MagicMock()  # built by build(), which runs before any UI action
    app._settings_screen = MagicMock()
    app._timer_state = MagicMock()
    app._on_connect_cancel()  # must not raise


def test_failed_connect_exit_releases_wake_lock_and_service():
    app, events = _make_waiting_app()
    app._bt_connect_start = time.time()
    app._real_stream.is_connected = False
    app._real_stream._running = False
    app._real_stream._device_name = "MindWave"
    app._real_stream._last_connect_error = "Headset is asleep or off."
    app._on_main = MagicMock()
    app._report_bt_connect_failure = MagicMock()

    app._handle_bt_wait()

    _assert_unwatched_stream_stop(app, events)
    app._report_bt_connect_failure.assert_called_once()


def test_refused_start_undoes_setup_without_entering_the_wait():
    app, _ = _make_waiting_app()
    app._waiting_for_bt = False
    app._real_stream.start.return_value = False
    app._real_stream._device_name = "MindWave"
    app._real_stream._last_connect_error = "Previous connection is still closing."
    app._report_bt_connect_failure = MagicMock()

    assert app._begin_bt_wait() is False

    assert app._waiting_for_bt is False
    app._release_wake_lock.assert_called_once()
    app._stop_session_keep_alive_service.assert_called_once()
    shown = app._live_screen.show_overlay_retry.call_args.args[0]
    assert "still closing" in shown
    app._report_bt_connect_failure.assert_not_called()


def test_started_stream_enters_the_wait():
    app, _ = _make_waiting_app()
    app._waiting_for_bt = False
    app._real_stream.start.return_value = True
    app._real_stream._device_name = "MindWave"

    assert app._begin_bt_wait() is True

    assert app._waiting_for_bt is True
    app._live_screen.show_overlay.assert_called_once()
    app._release_wake_lock.assert_not_called()
