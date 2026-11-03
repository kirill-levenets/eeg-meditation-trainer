"""A session ends once. A check that ends it on the tick thread (data gone stale, the recording limit) freezes it there,
so no later tick ends it again while the main thread can't run (a locked phone), and every main-thread finish is for
its own run."""
from unittest.mock import MagicMock

import pytest

from app.config import APP
from app.session.manager import SessionManager, SessionState
from app.session.session_run import Phase, SessionRun
from app.ui.app_manager import EEGMeditationApp
from tests._session_watch import make_watch
from tests.test_resume_mirror import _drive_tick, _make_tick_app, _metrics, _raw_sample


def _locked_app(monkeypatch):
    """A running headset session on a held main thread: what the tick queues for it waits in `queued`."""
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", False)
    app = _make_tick_app(is_paused=True)
    app._session_manager = SessionManager()
    app._session_manager.start(threshold=50)
    app._watch = make_watch(app)
    app._real_stream.seconds_since_last_packet = 0.2  # streaming
    app._ticker = MagicMock(running=True)
    app._timer_state.custom_sound_path = ""
    queued = []
    app._on_main = queued.append
    app._finalize_stop_ui = MagicMock()  # the main thread's teardown: counted, not run
    reasons = []
    persist = app._persist_session_data
    app._persist_session_data = lambda reason: (reasons.append(reason), persist(reason))[1]
    return app, queued, reasons


_TICK_ENDINGS = pytest.mark.parametrize(
    "end", [lambda app, run: app._end_from_tick(run, "stale_data", "No EEG data."), lambda app, run: app._end_by_timer(run)],
    ids=["freeze", "timer"])


def _unlock(queued) -> None:
    while queued:
        queued.pop(0)()


def test_a_timer_end_after_the_data_went_stale_ends_it_once(monkeypatch):
    app, queued, reasons = _locked_app(monkeypatch)
    app._real_stream.seconds_since_last_packet = app._watch.STALE_DATA_THRESHOLD + 1
    _drive_tick(app, _raw_sample(), _metrics())  # the data went stale: the session stops here
    app._timer_state.tick.return_value = True
    _drive_tick(app, _raw_sample(), _metrics())  # a tick that would end it by the timer
    _unlock(queued)
    assert reasons == ["stale_data"]
    app._finalize_stop_ui.assert_called_once()
    assert app._session_manager.state == SessionState.FINISHED


def test_a_stale_stop_freezes_the_session_on_the_tick_thread(monkeypatch):
    # Its duration ends when the data stopped, not when the phone is unlocked; its noise goes quiet meanwhile.
    app, queued, _reasons = _locked_app(monkeypatch)
    app._real_stream.seconds_since_last_packet = app._watch.STALE_DATA_THRESHOLD + 1
    _drive_tick(app, _raw_sample(), _metrics())
    assert app._session_manager.state == SessionState.PAUSED
    app._audio.mute.assert_called_once()
    app._ticker.stop.assert_called_once()
    assert len(queued) == 1


def test_a_stale_stop_saves_its_ticks_before_the_unlock(monkeypatch):
    # Android may close a locked app before the main thread runs: the ticks so far must already be in the DB.
    app, queued, _reasons = _locked_app(monkeypatch)
    app._real_stream.seconds_since_last_packet = app._watch.STALE_DATA_THRESHOLD + 1
    _drive_tick(app, _raw_sample(), _metrics())
    assert queued  # the main thread hasn't run
    app._db.checkpoint_session.assert_called_once()


def test_the_recording_limit_ends_it_once_however_many_ticks_pass_before_the_unlock(monkeypatch):
    app, queued, reasons = _locked_app(monkeypatch)
    monkeypatch.setattr(APP, "SESSION_MAX_SECONDS", 0)
    for _ in range(3):
        _drive_tick(app, _raw_sample(), _metrics())
    _unlock(queued)
    app._audio.play_disconnect_alert.assert_called_once()
    assert reasons == ["user"]
    app._finalize_stop_ui.assert_called_once()


def test_a_timer_finish_for_a_run_already_ended_does_nothing(monkeypatch):
    # The timer saved it on the tick thread; the profile was deleted before the main thread showed its end card.
    app, queued, _reasons = _locked_app(monkeypatch)
    app._timer_state.tick.return_value = True
    _drive_tick(app, _raw_sample(), _metrics())
    app._run = None  # its ending already ran on the main thread
    _unlock(queued)
    app._finalize_stop_ui.assert_not_called()


def test_without_a_stale_stop_the_timer_still_ends_it(monkeypatch):
    app, queued, reasons = _locked_app(monkeypatch)
    app._timer_state.tick.return_value = True
    _drive_tick(app, _raw_sample(), _metrics())
    _unlock(queued)
    assert reasons == ["timer"]
    app._finalize_stop_ui.assert_called_once()


def test_the_unfrozen_session_keeps_its_tick(monkeypatch):
    app, queued, reasons = _locked_app(monkeypatch)
    _drive_tick(app, _raw_sample(), _metrics())
    assert app._session_manager.state == SessionState.RUNNING and reasons == [] and not queued
    app._ticker.stop.assert_not_called()


def test_a_stale_stop_still_says_why(monkeypatch):
    app, queued, _reasons = _locked_app(monkeypatch)
    app._real_stream.seconds_since_last_packet = app._watch.STALE_DATA_THRESHOLD + 1
    _drive_tick(app, _raw_sample(), _metrics())
    _unlock(queued)
    assert any("No EEG data" in c.args[0] for c in app._live_screen.show_alert.call_args_list)


def test_a_freeze_mutes_before_its_checkpoint(monkeypatch):
    # The checkpoint may wait on the write lock: the noise must not play on through it.
    app, _queued, _reasons = _locked_app(monkeypatch)
    order = []
    app._audio.mute.side_effect = lambda: order.append("mute")
    app._db.checkpoint_session.side_effect = lambda *a, **k: (order.append("checkpoint"), 7)[1]
    app._real_stream.seconds_since_last_packet = app._watch.STALE_DATA_THRESHOLD + 1
    _drive_tick(app, _raw_sample(), _metrics())
    assert order == ["mute", "checkpoint"]


def test_a_session_tick_that_outlived_its_run_records_nothing(monkeypatch):
    # Its read waited on the reader's lock past the stop's 1 s join; a new Start replaced its run meanwhile.
    app, _queued, _reasons = _locked_app(monkeypatch)
    old, new = app._run, SessionRun(1)
    app._eeg_stream.read_sample.side_effect = lambda: (setattr(app, "_run", new), _raw_sample())[1]
    app._metrics_engine.process_sample.return_value = _metrics()
    EEGMeditationApp._session_tick(app, old)
    assert not app._shown.mirror.metrics and app._recorder._buffer == []


@_TICK_ENDINGS
def test_a_tick_thread_ending_ends_only_its_own_run(monkeypatch, end):
    app, queued, reasons = _locked_app(monkeypatch)
    old = app._run
    app._run = SessionRun(1)  # a newer run, which a late ending must not stop
    end(app, old)
    assert app._session_manager.state == SessionState.RUNNING and reasons == [] and not queued


def test_a_session_tick_whose_stop_began_during_its_read_computes_nothing(monkeypatch):
    # The Stop saved the session while the tick waited on the reader's lock; its teardown, which drops the run, is queued.
    # The recorder already refuses the tick; before it come the metrics, the alerts and a program's step and cue.
    app, _queued, reasons = _locked_app(monkeypatch)
    run = app._run
    app._eeg_stream.read_sample.side_effect = lambda: (app._stop_and_save(reason="user"), _raw_sample())[1]
    app._metrics_engine.process_sample.return_value = _metrics()
    EEGMeditationApp._session_tick(app, run)
    assert app._run is run and reasons == ["user"]
    app._metrics_engine.process_sample.assert_not_called()


def test_a_tick_that_begins_after_an_ending_began_checks_nothing(monkeypatch):
    # It begins between an ending's mark and its stop of the tick loop: no check may alert, show the link, or end it.
    app, queued, reasons = _locked_app(monkeypatch)
    app._real_stream.is_connected = False  # the link dropped
    app._run.bt_connected_notified = True
    app._real_stream.seconds_since_last_packet = app._watch.STALE_DATA_THRESHOLD + 1
    app._mark_run_ended()
    _drive_tick(app, _raw_sample(), _metrics())
    assert reasons == [] and not queued and app._session_manager.state == SessionState.RUNNING
    app._audio.play_disconnect_alert.assert_not_called()


@_TICK_ENDINGS
def test_a_tick_thread_ending_ends_its_run_at_once(monkeypatch, end):
    app, _queued, _reasons = _locked_app(monkeypatch)
    run = app._run
    end(app, run)
    assert run.phase is Phase.ENDED and app._outlived(run)
    run.phase = Phase.STARTED  # a tick that passed its check before the ending began
    assert run.phase is Phase.ENDED


@_TICK_ENDINGS
def test_two_tick_bodies_past_their_checks_end_the_run_once(monkeypatch, end):
    # A late tick of a thread whose stop join timed out overlaps the new thread's; both are past their checks before
    # either marks the run: one ending claims it.
    app, _queued, _reasons = _locked_app(monkeypatch)
    run, entered, mark = app._run, [], app._run.mark_ended

    def second_body_first():
        if not entered:
            entered.append(True)
            end(app, run)
        return mark()
    run.mark_ended = second_body_first
    end(app, run)
    app._audio.mute.assert_called_once()


@pytest.mark.parametrize("ending", ["_stop_and_save", "_discard_running_session"])
def test_a_main_thread_ending_marks_its_run_before_it_joins_the_tick(monkeypatch, ending):
    # A tick still in progress during the stop's join must find its run ended.
    app, _queued, _reasons = _locked_app(monkeypatch)
    run, seen = app._run, []
    app._ticker.stop.side_effect = lambda: seen.append(app._outlived(run))
    getattr(app, ending)()
    assert seen == [True]


def test_a_timer_ending_in_the_tick_a_stop_joins_leaves_the_save_to_the_stop(monkeypatch):
    app, _queued, reasons = _locked_app(monkeypatch)
    run, joined = app._run, []

    def join():  # the tick in progress during the join: its timer expires now
        if not joined:
            joined.append(True)
            EEGMeditationApp._end_by_timer(app, run)
    app._ticker.stop.side_effect = join
    app._stop_and_save("user")
    assert reasons == ["user"]
    app._audio.play_timer_sound.assert_not_called()
