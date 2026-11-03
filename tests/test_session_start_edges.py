"""A session start is one run: Stop and Cancel end it whatever phase it is in, and nothing queued for it runs later
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
from app.session.session_run import Phase
from app.storage.database import DatabaseManager
from app.ui.app_manager import EEGMeditationApp
from app.ui.bt_wait import BtWait
from tests._bt_wait import make_bt_wait
from tests._headset import fake_paired, make_headset
from tests._program_run import make_run
from tests._recorder import make_recorder
from tests._session_run import run_in
from tests._shown_session import make_shown


@pytest.fixture(autouse=True)
def _reports(monkeypatch):
    """A failed connect files a diagnostic report: here it is recorded (`am.report_soft_error`), not shown."""
    monkeypatch.setattr(am, "report_soft_error", MagicMock())

BANDS = {"delta": 10.0, "theta": 10.0, "alpha1": 10.0, "alpha2": 10.0, "beta1": 10.0, "beta2": 10.0,
         "gamma1": 10.0, "gamma2": 10.0, "signal_quality": 0}


def _app() -> EEGMeditationApp:
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._current_user_id = 1
    app._ticker = MagicMock(running=False)
    app._real_stream = MagicMock()
    app._real_stream._device_name = "MindWave"
    app._eeg_stream = app._real_stream
    app._session_manager = SessionManager()
    app._timer_state = MagicMock()
    app._live_screen = MagicMock()
    app._settings_screen = MagicMock()
    app._audio = MagicMock()
    app._keep_awake = MagicMock()
    app._confirm_action = MagicMock()
    app._program_run = make_run(app)
    queued = []
    app._on_main = queued.append
    app._queued = queued
    app._headset = make_headset(app)
    app._bt_wait = make_bt_wait(app)
    app._shown = make_shown(app)
    return app


def _run_queued(app) -> None:
    while app._queued:
        app._queued.pop(0)()


def _waiting(app) -> EEGMeditationApp:
    """In the BT wait, connected, the first band data arriving on this tick."""
    run_in(app, Phase.STARTING)  # as _on_start makes it
    app._real_stream.start.return_value = True
    assert app._begin_bt_wait(app._run)
    app._run.connect_start = time.time()
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
    app._ticker.stop.assert_not_called()


def test_stop_during_a_running_session_still_asks():
    app = _app()
    app._session_manager.start()
    app._on_stop()
    app._confirm_action.assert_called_once()


# ---- nothing queued for an ended run runs ----


def test_a_cancel_in_the_frame_the_session_starts_leaves_no_session_running():
    app = _waiting(_app())
    app._follow_bt_wait(app._run)  # data arrived: the session starts and its "Running" UI + audio are queued
    assert app._session_manager.state == SessionState.RUNNING
    app._on_connect_cancel()  # the Cancel tap, handled before the queued callback
    _run_queued(app)
    app._audio.start.assert_not_called()
    assert app._session_manager.state == SessionState.IDLE
    assert not any(c.args == ("Running",) for c in app._live_screen.update_state.call_args_list)


def test_without_a_cancel_the_session_starts_its_audio():
    app = _waiting(_app())
    app._follow_bt_wait(app._run)
    _run_queued(app)
    app._audio.start.assert_called_once()


def test_a_cancel_while_the_tick_reads_the_first_data_leaves_no_session_running():
    # The Cancel tap is handled while the tick thread is inside the tick that gets the first data.
    app = _waiting(_app())
    in_read, release = threading.Event(), threading.Event()
    app._real_stream.read_sample.side_effect = lambda: (in_read.set(), release.wait(2), dict(BANDS))[2]
    tick = threading.Thread(target=app._follow_bt_wait, args=(app._run,))
    tick.start()
    assert in_read.wait(2)
    app._ticker.stop = MagicMock(side_effect=lambda: (release.set(), tick.join(2)))  # the real stop joins the tick
    app._on_connect_cancel()
    assert not tick.is_alive()
    _run_queued(app)
    app._audio.start.assert_not_called()
    assert app._session_manager.state == SessionState.IDLE
    assert not any(c.args == ("Running",) for c in app._live_screen.update_state.call_args_list)


def test_a_tick_that_outlives_the_cancel_shows_nothing():
    # The Cancel's 1 s join timed out: the tick reads the first data after the Cancel has finished, and acts on nothing.
    app = _waiting(_app())
    in_read, release = threading.Event(), threading.Event()
    app._real_stream.read_sample.side_effect = lambda: (in_read.set(), release.wait(2), dict(BANDS))[2]
    tick = threading.Thread(target=app._follow_bt_wait, args=(app._run,))
    tick.start()
    assert in_read.wait(2)
    app._on_connect_cancel()  # the fixture's ticker stop returns without the tick, like a timed-out join
    release.set()
    tick.join(2)
    _run_queued(app)
    app._audio.start.assert_not_called()
    assert not any(c.args == ("Running",) for c in app._live_screen.update_state.call_args_list)
    assert app._session_manager.state == SessionState.IDLE  # not started: Restore and a switch stay free
    app._timer_state.start_countdown.assert_not_called()


def test_a_first_data_tick_that_outlived_its_run_starts_nothing():
    app = _waiting(_app())
    old = app._run
    new = run_in(app, Phase.CONNECTING)  # a Cancel and a new Start while the tick read the first data
    app._follow_bt_wait(old)
    assert app._session_manager.state == SessionState.IDLE and new.phase is Phase.CONNECTING and not app._queued
    app._timer_state.start_countdown.assert_not_called()


def test_deleting_the_profile_in_the_frame_the_session_starts_leaves_no_audio_playing():
    app = _waiting(_app())
    app._follow_bt_wait(app._run)  # data arrived: the "Running" UI + audio are queued
    app._db = MagicMock()
    app._recorder = make_recorder(app)
    app._recorder._buffer = []
    app._shown.mirror = MagicMock()
    app._history = MagicMock()
    app._discard_running_session()
    _run_queued(app)
    app._audio.start.assert_not_called()


def test_the_header_start_time_is_when_the_data_arrived(monkeypatch):
    app = _waiting(_app())
    app._follow_bt_wait(app._run)
    started = app._session_manager.started_at
    monkeypatch.setattr(am.time, "time", lambda: started + 600)  # the queued UI runs after a 10-min screen lock
    _run_queued(app)
    app._live_screen.set_start_time.assert_called_once_with(started)


def test_stop_after_the_timer_ended_the_session_leaves_its_teardown_alone():
    app = _app()
    app._session_manager.start()
    app._session_manager.stop(reason="timer")  # saved on the tick thread; its UI teardown is queued
    app._on_stop()
    app._real_stream.stop.assert_not_called()  # the kept-alive headset link stays up
    app._confirm_action.assert_not_called()
    app._live_screen.update_state.assert_not_called()


def test_cancel_during_the_device_scan_does_not_start_the_session(monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", False)
    paired = fake_paired(monkeypatch)
    paired.devices.append({"name": "MindWave Mobile", "address": "00:11"})
    app = _app()
    app._real_stream._device_address = ""
    app._headset.on_select = MagicMock()
    app._start_session_common = MagicMock()
    app._on_start()  # "Scanning for MindWave..."; the scan result is queued
    app._on_connect_cancel()
    paired.arrive()
    app._start_session_common.assert_not_called()


def test_a_scan_result_still_starts_the_session_without_a_cancel(monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", False)
    paired = fake_paired(monkeypatch)
    paired.devices.append({"name": "MindWave Mobile", "address": "00:11"})
    app = _app()
    app._real_stream._device_address = ""
    app._real_stream.set_device.side_effect = lambda address, name="": setattr(app._real_stream, "_device_address",
                                                                              address)
    app._start_session_common = MagicMock()
    app._on_start()
    paired.arrive()
    app._start_session_common.assert_called_once()
    assert app._real_stream._device_address == "00:11"


def test_a_scan_result_for_a_profile_picked_away_ends_the_start(monkeypatch):
    """The Start was the profile's that pressed it: another one picked while it scanned gets neither its headset nor
    its session (#99)."""
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", False)
    paired = fake_paired(monkeypatch)
    paired.devices.append({"name": "MindWave Mobile", "address": "00:11"})
    app = _app()
    app._real_stream._device_address = None
    app._headset.on_select = MagicMock()
    app._start_session_common = MagicMock()
    app._on_start()
    app._current_user_id = 2  # picked in Settings while the scan ran
    paired.arrive()
    app._start_session_common.assert_not_called()
    app._headset.on_select.assert_not_called()
    app._live_screen.hide_overlay.assert_called()
    app._live_screen.set_controls_idle.assert_called()


# ---- an ended run undoes its program setup ----


def _with_program(app) -> EEGMeditationApp:
    """What _start_session_common's ProgramRun.begin left before the wait."""
    app._program_run.program = MagicMock()
    app._program_run._prev_visibility = {"shamatha_score": True, "program_formula": False}
    app._live_screen.graph.series_keys.return_value = ["shamatha_score", "program_formula"]
    return app


def test_a_cancelled_program_session_restores_the_series_and_leaves_no_program_state():
    app = _with_program(_waiting(_app()))
    app._on_connect_cancel()
    assert not app._program_run.active and app._program_run._prev_visibility == {}


def _end_the_wait(app, exit_case: str) -> None:
    """Make the next BT-wait tick end the wait the given way."""
    if exit_case == "failed":
        app._real_stream.is_connected = False
        app._real_stream._running = False
        app._real_stream._last_connect_error = "Host is down"
    elif exit_case == "no data":
        app._real_stream.read_sample.return_value = dict(BANDS, delta=0.0, theta=0.0, alpha1=0.0, alpha2=0.0,
                                                         beta1=0.0, beta2=0.0, gamma1=0.0, gamma2=0.0)
        app._real_stream.seconds_since_last_packet = 0
        app._run.signal_start = time.time() - BtWait.SIGNAL_TIMEOUT - 1
    else:
        app._real_stream.is_connected = False
        app._real_stream._running = True
        app._run.connect_start = time.time() - BtWait.CONNECT_TIMEOUT - 1


@pytest.mark.parametrize("exit_case", ["failed", "no data", "timeout"])
def test_a_wait_that_ends_on_its_own_undoes_the_program_setup(exit_case):
    app = _with_program(_waiting(_app()))
    _end_the_wait(app, exit_case)
    app._follow_bt_wait(app._run)
    _run_queued(app)
    assert not app._program_run.active and app._program_run._prev_visibility == {}
    app._live_screen.show_overlay_retry.assert_called_once()


@pytest.mark.parametrize("exit_case", ["failed", "no data", "timeout"])
def test_a_wait_exit_queued_before_a_cancel_leaves_the_next_start_alone(exit_case, monkeypatch):
    app = _waiting(_app())
    _end_the_wait(app, exit_case)
    app._follow_bt_wait(app._run)  # the wait ended on the tick thread; its retry screen is queued
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
        app._recorder = make_recorder(app)
        app._recorder._buffer = [{"timestamp": 0.5, "shamatha_score": 70}]
        app._with_score = lambda stats: stats
        app._session_custom_formulas_json = lambda: ""
        app._session_manager.start()
        started = time.time() - 3 * 3600  # the first checkpoint lands well after the start
        app._session_manager._start_time = started
        app._recorder.checkpoint()
        row = db.get_session(app._recorder.session_id)
        assert row["date_time"][:19] == datetime.datetime.fromtimestamp(started).isoformat()[:19]
        assert row["session_name"] == time.strftime("%Y-%m-%d %H:%M", time.localtime(started)) + " - Mock"
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
    before = time.strftime("%Y-%m-%d %H:%M")
    name = _app()._make_session_name()
    assert name in (before + " - Mock", time.strftime("%Y-%m-%d %H:%M") + " - Mock")


# ---- how a headset session starts ----


def test_a_link_kept_from_the_last_session_starts_the_session_at_once(monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", False)
    app = _app()
    run_in(app, Phase.STARTING)
    app._real_stream.is_connected, app._real_stream._device_address = True, "00:11"
    assert app._connect_session(app._run, 60)
    assert app._run.phase is Phase.STARTED and app._session_manager.state == SessionState.RUNNING
    app._real_stream.start.assert_not_called()  # no BT wait
    app._real_stream.reset_sample_state.assert_called_once()  # the last session's sample can't start this one
    app._live_screen.update_device_status.assert_called_with(True, device_name="MindWave", connecting=False)
    app._audio.play_connect_sound.assert_called_once()


def test_with_no_link_the_start_enters_the_bt_wait(monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", False)
    app = _app()
    run_in(app, Phase.STARTING)
    app._real_stream.is_connected, app._real_stream._device_address = False, "00:11"
    app._real_stream.start.return_value = True
    assert app._connect_session(app._run, 60)
    assert app._run.phase is Phase.CONNECTING and app._session_manager.state == SessionState.IDLE
    app._live_screen.show_overlay.assert_called_once_with("Connecting to MindWave...")


def test_the_tick_drives_the_wait_until_its_first_data_starts_the_session():
    app = _waiting(_app())
    app._update_tick(0.5)
    assert app._run.phase is Phase.STARTED and app._session_manager.state == SessionState.RUNNING


def test_a_marker_is_placed_only_in_a_running_session():
    app = _app()
    app._on_marker()  # no Start yet
    run = run_in(app, Phase.STARTED)
    app._on_marker()  # nothing running
    assert not run.pending_marker
    app._session_manager.start(threshold=50)
    app._session_manager.pause()
    app._on_marker()
    assert not run.pending_marker
    app._session_manager.resume()
    app._on_marker()
    assert run.pending_marker  # the next recorded tick carries it


def test_a_wait_tick_that_outlived_its_run_ends_nothing(monkeypatch):
    # The tick read its run, then a Cancel and a new Start replaced it: the new run owns the stream now.
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", False)
    app = _app()
    old = run_in(app, Phase.CONNECTING)
    old.connect_start = time.time()
    app._real_stream.is_connected, app._real_stream._running = False, False  # the old wait would give up
    app._real_stream._last_connect_error = "Headset is asleep or off."
    new = run_in(app, Phase.CONNECTING)
    app._follow_bt_wait(old)
    app._ticker.stop.assert_not_called()  # the new run's wait goes on: no abort
    app._real_stream.stop.assert_not_called()
    am.report_soft_error.assert_not_called()  # and no diagnostic for a failure the new run didn't have
    assert app._run is new and new.phase is Phase.CONNECTING and not app._queued
