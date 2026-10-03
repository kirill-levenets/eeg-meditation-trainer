"""A session start is one attempt: Stop and Cancel end it whatever phase it is in, and nothing queued for it runs later
(#52). A session row is dated and named by the session's start."""

import datetime
import os
import tempfile
import threading
import time
from unittest.mock import MagicMock

import pytest

import app.ui.app_manager as am
from app.config import APP
from app.session.manager import SessionManager, SessionState
from app.storage.database import DatabaseManager
from app.ui.app_manager import EEGMeditationApp

BANDS = {"delta": 10.0, "theta": 10.0, "alpha1": 10.0, "alpha2": 10.0, "beta1": 10.0, "beta2": 10.0,
         "gamma1": 10.0, "gamma2": 10.0, "signal_quality": 0}


def _app() -> EEGMeditationApp:
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._current_user_id = 1
    app._waiting_for_bt = False
    app._bt_signal_start = None
    app._tick_thread = None
    app._stop_tick_thread = MagicMock()
    app._real_stream = MagicMock()
    app._real_stream._device_name = "MindWave"
    app._eeg_stream = app._real_stream
    app._session_manager = SessionManager()
    app._timer_state = MagicMock()
    app._live_screen = MagicMock()
    app._settings_screen = MagicMock()
    app._audio = MagicMock()
    app._release_wake_lock = MagicMock()
    app._stop_session_keep_alive_service = MagicMock()
    app._confirm_action = MagicMock()
    queued = []
    app._on_main = queued.append
    app._queued = queued
    return app


def _run_queued(app) -> None:
    while app._queued:
        app._queued.pop(0)()


def _waiting(app) -> EEGMeditationApp:
    """In the BT wait, connected, the first band data arriving on this tick."""
    app._start_attempt += 1  # as _on_start does
    app._real_stream.start.return_value = True
    assert app._begin_bt_wait(50)
    app._tick_thread = MagicMock()
    app._bt_connect_start = time.time()
    app._real_stream.is_connected = True
    app._real_stream.read_sample.return_value = dict(BANDS)
    app._real_stream.seconds_since_last_packet = 0.1
    return app


# ---- Stop decides by the session, not by the wait flag ----


def test_stop_after_a_failed_wait_cleans_up_without_offering_to_save():
    app = _app()  # the wait just ended (flag cleared), the controls still show Stop; nothing was started
    app._on_stop()
    app._confirm_action.assert_not_called()  # "Stop session? It will be saved" for a session that never existed
    app._live_screen.set_controls_idle.assert_called()
    app._stop_tick_thread.assert_not_called()


def test_stop_during_a_running_session_still_asks():
    app = _app()
    app._session_manager.start()
    app._on_stop()
    app._confirm_action.assert_called_once()


# ---- nothing queued for an ended attempt runs ----


def test_a_cancel_in_the_frame_the_session_starts_leaves_no_session_running():
    app = _waiting(_app())
    app._handle_bt_wait()  # data arrived: the session starts and its "Running" UI + audio are queued
    assert app._session_manager.state == SessionState.RUNNING
    app._on_connect_cancel()  # the Cancel tap, handled before the queued callback
    _run_queued(app)
    app._audio.start.assert_not_called()
    assert app._session_manager.state == SessionState.IDLE
    assert not any(c.args == ("Running",) for c in app._live_screen.update_state.call_args_list)


def test_without_a_cancel_the_session_starts_its_audio():
    app = _waiting(_app())
    app._handle_bt_wait()
    _run_queued(app)
    app._audio.start.assert_called_once()


def test_a_cancel_while_the_tick_reads_the_first_data_leaves_no_session_running():
    # The Cancel tap is handled while the tick thread is inside the tick that gets the first data.
    app = _waiting(_app())
    in_read, release = threading.Event(), threading.Event()
    app._real_stream.read_sample.side_effect = lambda: (in_read.set(), release.wait(2), dict(BANDS))[2]
    tick = threading.Thread(target=app._handle_bt_wait)
    tick.start()
    assert in_read.wait(2)
    app._stop_tick_thread = MagicMock(side_effect=lambda: (release.set(), tick.join(2)))  # the real stop joins the tick
    app._on_connect_cancel()
    assert not tick.is_alive()
    _run_queued(app)
    app._audio.start.assert_not_called()
    assert app._session_manager.state == SessionState.IDLE
    assert not any(c.args == ("Running",) for c in app._live_screen.update_state.call_args_list)


def test_a_tick_that_outlives_the_cancel_shows_nothing():
    # The Cancel's 1 s join timed out: the tick queues the first data's "connected" UI after the Cancel has finished.
    app = _waiting(_app())
    in_read, release = threading.Event(), threading.Event()
    app._real_stream.read_sample.side_effect = lambda: (in_read.set(), release.wait(2), dict(BANDS))[2]
    tick = threading.Thread(target=app._handle_bt_wait)
    tick.start()
    assert in_read.wait(2)
    app._on_connect_cancel()  # the fixture's _stop_tick_thread returns without the tick, like a timed-out join
    release.set()
    tick.join(2)
    _run_queued(app)
    app._audio.start.assert_not_called()
    assert not any(c.args == ("Running",) for c in app._live_screen.update_state.call_args_list)


def test_deleting_the_profile_in_the_frame_the_session_starts_leaves_no_audio_playing():
    app = _waiting(_app())
    app._handle_bt_wait()  # data arrived: the "Running" UI + audio are queued
    app._db = MagicMock()
    app._current_session_id = None
    app._metrics_buffer = []
    app._reload_live_graphs_from_mirror = MagicMock()
    app._mark_history_dirty = MagicMock()
    app._discard_running_session()
    _run_queued(app)
    app._audio.start.assert_not_called()


def test_the_header_start_time_is_when_the_data_arrived(monkeypatch):
    app = _waiting(_app())
    app._handle_bt_wait()
    started = app._session_manager.started_at
    monkeypatch.setattr(am.time, "time", lambda: started + 600)  # the queued UI runs after a 10-min screen lock
    _run_queued(app)
    app._live_screen.set_start_time.assert_called_once_with(started)


def test_stop_after_the_timer_ended_the_session_leaves_its_teardown_alone():
    app = _app()
    app._session_manager.start()
    app._session_manager.stop(reason="timer")  # saved on the tick thread; its UI teardown is queued
    app._tick_thread = MagicMock()
    app._on_stop()
    app._real_stream.stop.assert_not_called()  # the kept-alive headset link stays up
    app._confirm_action.assert_not_called()
    app._live_screen.update_state.assert_not_called()


def test_cancel_during_the_device_scan_does_not_start_the_session(monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", False)
    monkeypatch.setattr(am.NeuroSkyStream, "scan_paired_devices",
                        staticmethod(lambda: [{"name": "MindWave Mobile", "address": "00:11"}]))
    monkeypatch.setattr(am.threading, "Thread", lambda target, **k: MagicMock(start=target))
    scheduled = []
    monkeypatch.setattr(am.Clock, "schedule_once", lambda cb, *a, **k: scheduled.append(cb))
    app = _app()
    app._real_stream._device_address = ""
    app._on_device_select = MagicMock()
    app._start_session_common = MagicMock()
    app._on_start()  # "Scanning for MindWave..."; the scan result is queued
    app._on_connect_cancel()
    for cb in scheduled:
        cb(0)
    app._start_session_common.assert_not_called()


def test_a_scan_result_still_starts_the_session_without_a_cancel(monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", False)
    monkeypatch.setattr(am.NeuroSkyStream, "scan_paired_devices",
                        staticmethod(lambda: [{"name": "MindWave Mobile", "address": "00:11"}]))
    monkeypatch.setattr(am.threading, "Thread", lambda target, **k: MagicMock(start=target))
    scheduled = []
    monkeypatch.setattr(am.Clock, "schedule_once", lambda cb, *a, **k: scheduled.append(cb))
    app = _app()
    app._real_stream._device_address = ""
    app._on_device_select = MagicMock()
    app._start_session_common = MagicMock()
    app._on_start()
    for cb in scheduled:
        cb(0)
    app._start_session_common.assert_called_once()


# ---- an ended attempt undoes its program setup ----


def _with_program(app) -> EEGMeditationApp:
    """What _start_session_common's _show_program_series left before the wait."""
    app._session_program_active = True
    app._active_program = MagicMock()
    app._program_prev_visibility = {"shamatha_score": True, "program_formula": False}
    app._live_screen.graph.series_keys.return_value = ["shamatha_score", "program_formula"]
    return app


def test_a_cancelled_program_session_restores_the_series_and_leaves_no_program_state():
    app = _with_program(_waiting(_app()))
    app._on_connect_cancel()
    assert app._session_program_active is False and app._program_prev_visibility == {}


def _end_the_wait(app, exit_case: str) -> None:
    """Make the next _handle_bt_wait tick end the wait the given way."""
    if exit_case == "failed":
        app._real_stream.is_connected = False
        app._real_stream._running = False
        app._real_stream._last_connect_error = "Host is down"
        app._report_bt_connect_failure = MagicMock()
    elif exit_case == "no data":
        app._real_stream.read_sample.return_value = dict(BANDS, delta=0.0, theta=0.0, alpha1=0.0, alpha2=0.0,
                                                         beta1=0.0, beta2=0.0, gamma1=0.0, gamma2=0.0)
        app._real_stream.seconds_since_last_packet = 0
        app._bt_signal_start = time.time() - app._BT_SIGNAL_TIMEOUT - 1
    else:
        app._real_stream.is_connected = False
        app._real_stream._running = True
        app._bt_connect_start = time.time() - app._BT_CONNECT_TIMEOUT - 1


@pytest.mark.parametrize("exit_case", ["failed", "no data", "timeout"])
def test_a_wait_that_ends_on_its_own_undoes_the_program_setup(exit_case):
    app = _with_program(_waiting(_app()))
    _end_the_wait(app, exit_case)
    app._handle_bt_wait()
    _run_queued(app)
    assert app._session_program_active is False and app._program_prev_visibility == {}
    app._live_screen.show_overlay_retry.assert_called_once()


@pytest.mark.parametrize("exit_case", ["failed", "no data", "timeout"])
def test_a_wait_exit_queued_before_a_cancel_leaves_the_next_start_alone(exit_case, monkeypatch):
    app = _waiting(_app())
    _end_the_wait(app, exit_case)
    app._handle_bt_wait()  # the wait ended on the tick thread; its retry screen is queued
    app._on_connect_cancel()
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", True)
    app._mock_stream = MagicMock()
    app._start_session_common = lambda: app._session_manager.start()
    app._on_start()  # the next Start, handled before the queued retry screen
    _run_queued(app)
    assert app._session_manager.state == SessionState.RUNNING
    app._live_screen.show_overlay_retry.assert_not_called()


# ---- a session row is dated and named by its start ----


def test_a_session_row_is_dated_and_named_at_the_session_start(monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", True)
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = DatabaseManager(db_path=path)
    try:
        app = _app()
        app._db = db
        app._current_session_id = None
        app._metrics_buffer = [{"timestamp": 0.5, "shamatha_score": 70}]
        app._with_score = lambda stats: stats
        app._session_custom_formulas_json = lambda: ""
        app._session_program_json = lambda: ""
        app._session_manager.start()
        started = time.time() - 3 * 3600  # the first checkpoint lands well after the start
        app._session_manager._start_time = started
        app._checkpoint_session()
        row = db.get_session(app._current_session_id)
        assert row["date_time"][:19] == datetime.datetime.fromtimestamp(started).isoformat()[:19]
        assert row["session_name"] == time.strftime("%H:%M", time.localtime(started)) + " - Mock"
    finally:
        db.close()
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(path + suffix):
                os.remove(path + suffix)


def test_a_reset_session_has_no_start_time():
    sm = SessionManager()
    sm.start()
    sm.stop()
    sm.reset()
    assert sm.started_at == 0.0


def test_a_name_made_before_the_start_uses_the_current_time(monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", True)
    before = time.strftime("%H:%M")
    name = _app()._make_session_name()
    assert name in (before + " - Mock", time.strftime("%H:%M") + " - Mock")
