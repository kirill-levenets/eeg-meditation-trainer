"""Aborting a BT-connect wait must stop the tick watcher before the stream.

The watcher treats ``not stream._running`` as a failed connect, so stopping the
stream first made a user Cancel surface a false "Connection failed" dialog.
"""

from unittest.mock import MagicMock

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
    app._timer_state = MagicMock()
    return app, events


def _assert_unwatched_stream_stop(app: EEGMeditationApp, events: list) -> None:
    assert events == ["tick_stopped", ("stream_stopped", False, None)]
    assert app._bt_signal_start is None
    app._release_wake_lock.assert_called_once()
    app._stop_session_keep_alive_service.assert_called_once()


def test_connect_cancel_stops_watcher_before_stream():
    app, events = _make_waiting_app()
    app._on_connect_cancel()
    _assert_unwatched_stream_stop(app, events)


def test_stop_during_bt_wait_stops_watcher_before_stream():
    app, events = _make_waiting_app()
    app._on_stop()
    _assert_unwatched_stream_stop(app, events)
