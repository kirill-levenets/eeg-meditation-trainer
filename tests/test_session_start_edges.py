"""A session start is one run: Stop and Cancel end it whatever phase it is in, and nothing queued for it runs later
(#52). A session row is dated and named by the session's start."""

import datetime
import threading
import time
from unittest.mock import MagicMock

import pytest

import app.ui.app_manager as am
from app.eeg.neurosky_stream import NeuroSkyStream
from app.session.manager import SessionManager, SessionState
from app.session.session_run import Phase
from app.ui.bt_wait import BtWait
from tests._app import (
    HEADSET,
    HeadsetSession,
    calls_of,
    frames,
    popups,
    program_mode,
    start_connecting,
    start_ticked_by_hand,
)
from tests._headset import fake_paired


@pytest.fixture(autouse=True)
def _reports(monkeypatch):
    """A failed connect files a diagnostic report: here it is recorded (`am.report_soft_error`), not shown."""
    monkeypatch.setattr(am, "report_soft_error", MagicMock())


class _Waiting:
    """The app in a Start's BT wait, connected, the first band data arriving on the wait's next tick. What a tick
    queues for the main thread waits until `frames()`. `audio_starts`, `states` (each state the Session screen was
    given) and `countdowns` record what the start did."""

    def __init__(self, app, monkeypatch) -> None:
        self.app = app
        self.session = HeadsetSession(app, monkeypatch, start=False)
        self.session.connected, self.session.since_packet = True, 0.1
        self.run = app._run
        self.audio_starts = calls_of(monkeypatch, app._audio, "start")
        self.states = calls_of(monkeypatch, app._live_screen, "update_state")
        self.countdowns = calls_of(monkeypatch, app._timer_state, "start_countdown")

    def first_data(self) -> None:
        """The wait's tick that reads the first data."""
        self.app._follow_bt_wait(self.run)

    def ends(self, exit_case: str) -> None:
        """Make the next BT-wait tick end the wait the given way."""
        stream = self.app._real_stream
        if exit_case == "failed":
            self.session.connected, stream._running = False, False
            stream._last_connect_error = "Host is down"
        elif exit_case == "no data":
            self.session.raw = dict.fromkeys(self.session.raw, 0.0)
            self.session.since_packet = 0
            self.run.signal_start = time.time() - BtWait.SIGNAL_TIMEOUT - 1
        else:
            self.session.connected, stream._running = False, True
            self.run.connect_start = time.time() - BtWait.CONNECT_TIMEOUT - 1

    def shown_running(self) -> bool:
        return ("Running",) in self.states


@pytest.fixture
def waiting(fresh_app, monkeypatch) -> _Waiting:
    return _Waiting(fresh_app, monkeypatch)


def _idle(app) -> bool:
    return app._session_manager.state == SessionState.IDLE


def _retry_shown(app) -> bool:
    return app._live_screen._overlay_retry_btn.parent is not None and app._live_screen._overlay.opacity == 1


# ---- Stop decides by the session, not by the wait flag ----


def test_stop_after_a_failed_wait_cleans_up_without_offering_to_save(waiting, monkeypatch):
    app = waiting.app
    waiting.ends("failed")
    waiting.first_data()  # the wait just ended on the tick thread; the controls still show Stop; nothing was started
    tick_stops = calls_of(monkeypatch, app._ticker, "stop")
    app._on_stop()
    assert popups() == []  # no "Stop session? It will be saved" for a session that never existed
    assert not app._live_screen._btn_start.disabled and tick_stops == [] and app._run is None


def test_stop_during_a_running_session_still_asks(fresh_app):
    start_ticked_by_hand(fresh_app)
    fresh_app._on_stop()
    assert [p.title for p in popups()] == ["Stop session?"]


def test_stop_after_the_timer_ended_the_session_leaves_its_teardown_alone(fresh_app, monkeypatch):
    app = fresh_app
    session = HeadsetSession(app, monkeypatch)
    app._timer_state.set_enabled(True)
    app._timer_state.remaining_seconds = 0.1
    session.tick(shown=False)  # the timer: saved on the tick thread; its UI teardown is queued
    assert app._session_manager.state == SessionState.FINISHED
    stream_stops = calls_of(monkeypatch, app._real_stream, "stop")
    states = calls_of(monkeypatch, app._live_screen, "update_state")
    app._on_stop()
    assert stream_stops == [] and popups() == [] and states == []  # the kept-alive headset link stays up


# ---- a run that ended or was replaced starts nothing ----


def test_a_cancel_in_the_frame_the_session_starts_leaves_no_session_running(waiting):
    app = waiting.app
    waiting.first_data()  # data arrived: the session starts and its "Running" UI + audio are queued
    assert app._session_manager.state == SessionState.RUNNING
    app._on_connect_cancel()  # the Cancel tap, handled before the queued callback
    frames()
    assert waiting.audio_starts == [] and _idle(app) and not waiting.shown_running()


def test_without_a_cancel_the_session_starts_its_audio(waiting):
    waiting.first_data()
    frames()
    assert len(waiting.audio_starts) == 1 and waiting.shown_running()


def _tick_held_in_its_read(waiting, monkeypatch) -> tuple[threading.Thread, threading.Event]:
    """The wait's tick, on its own thread, stopped inside the read that gets the first data until `release` is set."""
    in_read, release = threading.Event(), threading.Event()
    monkeypatch.setattr(waiting.app._real_stream, "read_sample",
                        lambda: (in_read.set(), release.wait(2), waiting.session.raw)[2])
    tick = threading.Thread(target=waiting.first_data)
    tick.start()
    assert in_read.wait(2)
    return tick, release


def test_a_cancel_while_the_tick_reads_the_first_data_leaves_no_session_running(waiting, monkeypatch):
    # The Cancel tap is handled while the tick thread is inside the tick that gets the first data.
    app = waiting.app
    tick, release = _tick_held_in_its_read(waiting, monkeypatch)
    monkeypatch.setattr(app._ticker, "stop", lambda: (release.set(), tick.join(2)))  # the real stop joins the tick
    app._on_connect_cancel()
    assert not tick.is_alive()
    frames()
    assert waiting.audio_starts == [] and _idle(app) and not waiting.shown_running()


def test_a_tick_that_outlives_the_cancel_shows_nothing(waiting, monkeypatch):
    # The Cancel's 1 s join timed out: the tick reads the first data after the Cancel has finished, and acts on nothing.
    app = waiting.app
    tick, release = _tick_held_in_its_read(waiting, monkeypatch)
    app._on_connect_cancel()  # the tick loop is the test's: its stop returns without this tick, like a timed-out join
    release.set()
    tick.join(2)
    frames()
    assert waiting.audio_starts == [] and not waiting.shown_running()
    assert _idle(app) and waiting.countdowns == []  # not started: Restore and a switch stay free


def test_a_first_data_tick_that_outlived_its_run_starts_nothing(waiting, monkeypatch):
    app, old = waiting.app, waiting.run
    app._on_connect_cancel()  # a Cancel and a new Start while the tick read the first data
    waiting.session.connected = False  # the Cancel closed the link: the new Start waits for its own
    start_connecting(app, monkeypatch)
    app._ticker.stop()
    new = app._run
    waiting.countdowns.clear()
    waiting.session.connected = True  # what the old tick read
    app._follow_bt_wait(old)
    frames()
    assert _idle(app) and app._run is new and new.phase is Phase.CONNECTING
    assert waiting.countdowns == [] and waiting.audio_starts == []


def test_a_first_data_tick_after_the_cancel_began_starts_nothing(waiting):
    # The tick runs between the Cancel's abort and its teardown, which drops the run: the run is still current.
    app, run = waiting.app, waiting.run
    app._abort_bt_wait()
    waiting.first_data()
    frames()
    assert _idle(app) and run.phase is Phase.ENDED and waiting.countdowns == [] and waiting.audio_starts == []


def test_the_wait_abort_marks_its_run_before_it_joins_the_tick(waiting, monkeypatch):
    app, run, seen = waiting.app, waiting.run, []
    stop = app._ticker.stop
    monkeypatch.setattr(app._ticker, "stop", lambda: (seen.append(app._outlived(run)), stop())[1])
    app._abort_bt_wait()
    assert seen == [True]


@pytest.mark.parametrize("exit_case", ["failed", "no data", "timeout"])
def test_a_wait_exit_queued_before_a_cancel_leaves_the_next_start_alone(waiting, exit_case):
    app = waiting.app
    waiting.ends(exit_case)
    waiting.first_data()  # the wait ended on the tick thread; its retry screen is queued
    app._on_connect_cancel()
    app._change_setting("use_mock", True)
    start_ticked_by_hand(app)  # the next Start, handled before the queued retry screen
    frames()
    assert app._session_manager.state == SessionState.RUNNING and not _retry_shown(app)


def test_deleting_the_profile_in_the_frame_the_session_starts_leaves_no_audio_playing(waiting):
    waiting.first_data()  # data arrived: the "Running" UI + audio are queued
    waiting.app._discard_running_session()
    frames()
    assert waiting.audio_starts == [] and not waiting.shown_running()


# ---- Start's own scan for the headset ----


@pytest.fixture
def scanning(fresh_app, monkeypatch):
    """(app, paired): the app in real mode with no headset chosen and one MindWave paired; a Start lists the paired
    devices (`paired.arrive()` lets the result in) and its reader starts without Bluetooth."""
    app = fresh_app
    paired = fake_paired(monkeypatch)
    paired.devices.append({"name": "MindWave Mobile", "address": HEADSET[0]})
    monkeypatch.setattr(app._real_stream, "start", lambda: setattr(app._real_stream, "_running", True) or True)
    app._change_setting("use_mock", False)
    paired.queued.clear()  # a scan the mode change began is not this test's
    return app, paired


def _connecting(app) -> bool:
    return app._run is not None and app._run.phase is Phase.CONNECTING


def test_cancel_during_the_device_scan_does_not_start_the_session(scanning):
    app, paired = scanning
    app._on_start()  # "Scanning for MindWave..."; the scan result is queued
    app._on_connect_cancel()
    paired.arrive()
    assert app._run is None and not _connecting(app) and app._real_stream._device_address is None


def test_a_scan_result_still_starts_the_session_without_a_cancel(scanning):
    app, paired = scanning
    app._on_start()
    paired.arrive()
    assert _connecting(app) and app._real_stream._device_address == HEADSET[0]


def test_a_scan_result_for_a_profile_picked_away_ends_the_start(scanning):
    """The Start was the profile's that pressed it: another one picked while it scanned gets neither its headset nor
    its session (#99)."""
    app, paired = scanning
    other = app._db.create_user("other")
    app._db.set_user_setting(other, "use_mock", "True")
    app._on_start()
    app._profiles.on_switch(other)  # picked in Settings while the scan ran
    paired.arrive()
    assert app._run is None and app._real_stream._device_address is None
    assert app._db.get_user_setting(other, "bt_device_address") is None
    assert app._live_screen._overlay.opacity == 0 and not app._live_screen._btn_start.disabled


def test_a_wait_tick_that_outlived_its_run_ends_nothing(waiting, monkeypatch):
    # The tick read its run, then a Cancel and a new Start replaced it: the new run owns the stream now.
    app, old = waiting.app, waiting.run
    app._on_connect_cancel()
    waiting.session.connected = False
    start_connecting(app, monkeypatch)
    app._ticker.stop()
    new = app._run
    app._real_stream._running = False  # the old wait would give up
    app._real_stream._last_connect_error = "Headset is asleep or off."
    tick_stops = calls_of(monkeypatch, app._ticker, "stop")
    stream_stops = calls_of(monkeypatch, app._real_stream, "stop")
    am.report_soft_error.reset_mock()
    app._follow_bt_wait(old)
    frames()
    assert tick_stops == [] and stream_stops == []  # the new run's wait goes on: no abort
    am.report_soft_error.assert_not_called()  # and no diagnostic for a failure the new run didn't have
    assert app._run is new and new.phase is Phase.CONNECTING and not _retry_shown(app)


# ---- a run's ending undoes its program setup ----

DEEP = [{"minutes": 5, "target": 60, "formula": {"name": "Deep", "formula": "alpha1"}}]


@pytest.fixture
def program_waiting(fresh_app, monkeypatch) -> _Waiting:
    """A program session's Start in its BT wait: the program has begun and shows its lines."""
    program_mode(fresh_app, DEEP)
    waiting = _Waiting(fresh_app, monkeypatch)
    assert fresh_app._program_run.active and fresh_app._live_screen.graph.is_visible("program_formula")
    return waiting


def test_an_ending_derives_the_idle_series_once_the_session_no_longer_reads_live(program_waiting):
    # A Start cancelled in the frame its first data arrived: the session manager is still RUNNING at the teardown.
    app = program_waiting.app
    app._program_settings.on_mode_change("simple")  # while it waits: the idle series is derived at its ending
    program_waiting.first_data()
    assert app._session_manager.state == SessionState.RUNNING and app._live_screen.graph.is_visible("program_formula")
    app._on_connect_cancel()
    graph = app._live_screen.graph
    assert graph.visible_keys() == ["shamatha_score"] and graph.program_keys == frozenset()  # the profile's own


def test_a_cancelled_program_session_derives_the_idle_series_and_leaves_no_program_state(program_waiting):
    app = program_waiting.app
    app._on_connect_cancel()
    assert not app._program_run.active and app._run is None
    assert app._live_screen.graph.is_visible("program_formula")  # program mode still: its preview, derived again


@pytest.mark.parametrize("exit_case", ["failed", "no data", "timeout"])
def test_a_wait_that_ends_on_its_own_undoes_the_program_setup(program_waiting, exit_case):
    app = program_waiting.app
    program_waiting.ends(exit_case)
    program_waiting.first_data()
    frames()
    assert not app._program_run.active and app._run is None and _retry_shown(app)


# ---- a session row is dated and named by its start ----


def test_a_session_row_is_dated_and_named_at_the_session_start(fresh_app):
    app = fresh_app
    start_ticked_by_hand(app, ticks=1)
    started = time.time() - 3 * 3600  # the first checkpoint lands well after the start
    app._session_manager._start_time = started
    app._checkpoint_or_report()
    row = app._db.get_session(app._recorder.session_id)
    assert row["date_time"][:19] == datetime.datetime.fromtimestamp(started).isoformat()[:19]
    assert row["session_name"] == time.strftime("%Y-%m-%d %H:%M", time.localtime(started)) + " - Mock"


def test_a_reset_session_has_no_start_time():
    sm = SessionManager()
    sm.start()
    sm.stop()
    sm.reset()
    assert sm.started_at == 0.0


def test_a_name_made_before_the_start_uses_the_current_time(fresh_app):
    before = time.strftime("%Y-%m-%d %H:%M")
    name = fresh_app._make_session_name()
    assert name in (before + " - Mock", time.strftime("%Y-%m-%d %H:%M") + " - Mock")


# ---- how a headset session starts ----


def test_the_header_start_time_is_when_the_data_arrived(waiting, monkeypatch):
    app = waiting.app
    shown = calls_of(monkeypatch, app._live_screen, "set_start_time")
    waiting.first_data()
    started = app._session_manager.started_at
    real_time = time.time
    monkeypatch.setattr(am.time, "time", lambda: real_time() + 600)  # the queued UI runs after a 10-min screen lock
    frames()
    assert shown == [(started,)]


def test_a_link_kept_from_the_last_session_starts_the_session_at_once(fresh_app, monkeypatch):
    app = fresh_app
    monkeypatch.setattr(NeuroSkyStream, "is_connected", property(lambda _stream: True))
    reader_starts = calls_of(monkeypatch, app._real_stream, "start")
    resets = calls_of(monkeypatch, app._real_stream, "reset_sample_state")
    connect_sounds = calls_of(monkeypatch, app._audio, "play_connect_sound")
    app._change_setting("use_mock", False)
    app._real_stream.set_device(*HEADSET)
    app._ticker.start = lambda: None  # no tick thread: nothing is read from the stand-in link
    try:
        app._on_start()
    finally:
        del app._ticker.start
    assert app._run.phase is Phase.STARTED and app._session_manager.state == SessionState.RUNNING
    assert reader_starts == []  # no BT wait
    assert len(resets) == 1  # the last session's sample can't start this one
    assert app._live_screen._device_label.text == f"[{HEADSET[1]}] *" and len(connect_sounds) == 1


def test_with_no_link_the_start_enters_the_bt_wait(fresh_app, monkeypatch):
    app = fresh_app
    start_connecting(app, monkeypatch)
    assert app._run.phase is Phase.CONNECTING and _idle(app)
    assert app._live_screen._overlay_status.text == f"Connecting to {HEADSET[1]}..."


def test_the_tick_drives_the_wait_until_its_first_data_starts_the_session(waiting):
    app = waiting.app
    app._update_tick(0.5)
    assert waiting.run.phase is Phase.STARTED and app._session_manager.state == SessionState.RUNNING


def test_a_marker_is_placed_only_in_a_running_session(fresh_app):
    app = fresh_app
    app._on_marker()  # no Start yet
    start_ticked_by_hand(app)
    run = app._run
    app._on_pause()
    app._on_marker()  # paused
    assert not run.pending_marker
    app._on_pause()  # resumed
    app._ticker.stop()
    app._on_marker()
    assert run.pending_marker  # the next recorded tick carries it
