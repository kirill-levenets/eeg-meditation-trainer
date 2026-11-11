"""A session ends once. A check that ends it on the tick thread (data gone stale, the recording limit) freezes it there,
so no later tick ends it again while the main thread can't run (a locked phone), and every main-thread finish is for
its own run."""
from types import SimpleNamespace

import pytest

from app.config import APP
from app.session.manager import SessionState
from app.session.session_run import Phase, SessionRun
from tests._app import HeadsetSession, calls_of, frames


@pytest.fixture
def locked(fresh_app, monkeypatch):
    """A running headset session on a held main thread (a locked phone): `tick()` runs a tick and leaves what it
    queued for the main thread waiting until `unlock()`. `reasons` is each save's reason, `finishes` each main-thread
    teardown, `sounds` the audio calls and `tick_stops` each stop of the tick loop, in order."""
    app = fresh_app
    session = HeadsetSession(app, monkeypatch)
    app.on_pause()  # the lock
    reasons, persist = [], app._persist_session_data
    monkeypatch.setattr(app, "_persist_session_data", lambda reason: (reasons.append(reason), persist(reason))[1])
    sounds: list = []
    for name in ("mute", "play_disconnect_alert", "play_timer_sound"):
        calls_of(monkeypatch, app._audio, name, sounds, name)
    return SimpleNamespace(app=app, session=session, reasons=reasons, sounds=sounds, run=app._run,
                           finishes=calls_of(monkeypatch, app, "_finalize_stop_ui"),
                           tick_stops=calls_of(monkeypatch, app._ticker, "stop"),
                           tick=lambda: session.tick(shown=False), unlock=frames)


def _goes_stale(locked) -> None:
    locked.session.since_packet = locked.app._session.watch.STALE_DATA_THRESHOLD + 1


def _timer_expires_on_the_next_tick(locked) -> None:
    locked.app._session.timer.set_enabled(True)
    locked.app._session.timer.remaining_seconds = APP.UPDATE_FREQUENCY / 2


def _saved(app) -> list[dict]:
    return app._db.get_all_sessions(app._current_user_id)


_TICK_ENDINGS = pytest.mark.parametrize(
    "end", [lambda app, run: app._end_from_tick(run, "stale_data", "No EEG data."), lambda app, run: app._end_by_timer(run)],
    ids=["freeze", "timer"])


def test_a_timer_end_after_the_data_went_stale_ends_it_once(locked):
    _goes_stale(locked)
    locked.tick()  # the data went stale: the session stops here
    _timer_expires_on_the_next_tick(locked)
    locked.tick()  # a tick that would end it by the timer
    locked.unlock()
    assert locked.reasons == ["stale_data"] and len(locked.finishes) == 1
    assert len(_saved(locked.app)) == 1 and locked.app._run is None


def test_a_stale_stop_freezes_the_session_on_the_tick_thread(locked):
    # Its duration ends when the data stopped, not when the phone is unlocked; its noise goes quiet meanwhile.
    _goes_stale(locked)
    locked.tick()
    assert locked.app._session.manager.state == SessionState.PAUSED
    assert locked.sounds == ["mute"] and len(locked.tick_stops) == 1
    assert locked.finishes == [] and locked.app._run is locked.run  # its finish waits for the main thread


def test_a_stale_stop_saves_its_ticks_before_the_unlock(locked):
    # Android may close a locked app before the main thread runs: the ticks so far must already be in the DB.
    app = locked.app
    locked.tick()
    locked.tick()
    _goes_stale(locked)
    locked.tick()
    assert locked.finishes == []  # the main thread hasn't run
    assert len(app._db.get_session_metrics(app._session.recorder.session_id)) == 2


def test_the_recording_limit_ends_it_once_however_many_ticks_pass_before_the_unlock(locked, monkeypatch):
    monkeypatch.setattr(APP, "SESSION_MAX_SECONDS", 0)
    for _ in range(3):
        locked.tick()
    locked.unlock()
    assert locked.sounds.count("play_disconnect_alert") == 1
    assert locked.reasons == ["user"] and len(locked.finishes) == 1


def test_a_timer_finish_for_a_run_already_ended_does_nothing(locked):
    # The timer saved it on the tick thread; another ending (its profile's delete) ran on the main thread before
    # the timer's own finish did.
    app = locked.app
    _timer_expires_on_the_next_tick(locked)
    locked.tick()
    assert locked.reasons == ["timer"] and locked.finishes == []
    app._discard_running_session()  # the other ending: it drops the run
    assert len(locked.finishes) == 1
    locked.unlock()
    assert len(locked.finishes) == 1 and app._live_screen.summary_session_id is None  # no end card for it


def test_without_a_stale_stop_the_timer_still_ends_it(locked):
    _timer_expires_on_the_next_tick(locked)
    locked.tick()
    locked.unlock()
    assert locked.reasons == ["timer"] and len(locked.finishes) == 1


def test_the_unfrozen_session_keeps_its_tick(locked):
    locked.tick()
    assert locked.app._session.manager.state == SessionState.RUNNING
    assert locked.reasons == [] and locked.finishes == [] and locked.tick_stops == []


def test_a_stale_stop_still_says_why(locked, monkeypatch):
    alerts = calls_of(monkeypatch, locked.app._live_screen, "show_alert")
    _goes_stale(locked)
    locked.tick()
    locked.unlock()
    assert any("No EEG data" in args[0] for args in alerts)


def test_a_freeze_mutes_before_its_checkpoint(locked, monkeypatch):
    # The checkpoint may wait on the write lock: the noise must not play on through it.
    order = locked.sounds
    calls_of(monkeypatch, locked.app._db, "checkpoint_session", order, "checkpoint")
    _goes_stale(locked)
    locked.tick()
    assert order == ["mute", "checkpoint"]


def test_a_session_tick_that_outlived_its_run_records_nothing(locked, monkeypatch):
    # Its read waited on the reader's lock past the stop's 1 s join; a new Start replaced its run meanwhile.
    app, old = locked.app, locked.run
    new = SessionRun(app._current_user_id)
    monkeypatch.setattr(app._real_stream, "read_sample", lambda: (setattr(app, "_run", new), locked.session.raw)[1])
    app._session_tick(old)
    assert not app._shown.mirror.metrics and app._session.recorder._buffer == []


@_TICK_ENDINGS
def test_a_tick_thread_ending_ends_only_its_own_run(locked, end):
    app, old = locked.app, locked.run
    app._run = SessionRun(app._current_user_id)  # a newer run, which a late ending must not stop
    end(app, old)
    assert app._session.manager.state == SessionState.RUNNING and locked.reasons == [] and locked.finishes == []


def test_a_session_tick_whose_stop_began_during_its_read_computes_nothing(locked, monkeypatch):
    # The Stop saved the session while the tick waited on the reader's lock; its teardown, which drops the run, is queued.
    # The recorder already refuses the tick; before it come the metrics, the alerts and a program's step and cue.
    app, run = locked.app, locked.run
    computed = calls_of(monkeypatch, app._session.engine, "process_sample")
    monkeypatch.setattr(app._real_stream, "read_sample",
                        lambda: (app._stop_and_save(reason="user"), locked.session.raw)[1])
    app._session_tick(run)
    assert locked.reasons == ["user"] and computed == []


def test_a_tick_that_begins_after_an_ending_began_checks_nothing(locked):
    # It begins between an ending's mark and its stop of the tick loop: no check may alert, show the link, or end it.
    app = locked.app
    locked.tick()  # a tick with the link up: the next one would say it dropped
    locked.session.connected = False  # the link dropped
    _goes_stale(locked)
    app._mark_run_ended()
    locked.tick()
    assert locked.reasons == [] and locked.finishes == [] and app._session.manager.state == SessionState.RUNNING
    assert "play_disconnect_alert" not in locked.sounds


@_TICK_ENDINGS
def test_a_tick_thread_ending_ends_its_run_at_once(locked, end):
    app, run = locked.app, locked.run
    end(app, run)
    assert run.phase is Phase.ENDED and app._outlived(run)
    run.phase = Phase.STARTED  # a tick that passed its check before the ending began
    assert run.phase is Phase.ENDED


@_TICK_ENDINGS
def test_two_tick_bodies_past_their_checks_end_the_run_once(locked, monkeypatch, end):
    # A late tick of a thread whose stop join timed out overlaps the new thread's; both are past their checks before
    # either marks the run: one ending claims it.
    app, run, entered, mark = locked.app, locked.run, [], locked.run.mark_ended

    def second_body_first():
        if not entered:
            entered.append(True)
            end(app, run)
        return mark()

    monkeypatch.setattr(run, "mark_ended", second_body_first)
    end(app, run)
    assert locked.sounds.count("mute") == 1


@pytest.mark.parametrize("ending", ["_stop_and_save", "_discard_running_session"])
def test_a_main_thread_ending_marks_its_run_before_it_joins_the_tick(locked, monkeypatch, ending):
    # A tick still in progress during the stop's join must find its run ended.
    app, run, seen = locked.app, locked.run, []
    stop = app._ticker.stop
    monkeypatch.setattr(app._ticker, "stop", lambda: (seen.append(run.phase is Phase.ENDED), stop())[1])
    getattr(app, ending)()
    assert seen and seen[0] is True


def test_a_timer_ending_in_the_tick_a_stop_joins_leaves_the_save_to_the_stop(locked, monkeypatch):
    app, run, joined = locked.app, locked.run, []
    stop = app._ticker.stop

    def join():  # the tick in progress during the join: its timer expires now
        if not joined:
            joined.append(True)
            app._end_by_timer(run)
        stop()

    monkeypatch.setattr(app._ticker, "stop", join)
    app._stop_and_save("user")
    assert locked.reasons == ["user"] and "play_timer_sound" not in locked.sounds
