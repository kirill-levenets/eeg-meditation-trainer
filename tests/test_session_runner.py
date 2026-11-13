"""A run's runner thread is the one writer of the session's state: the main thread's commands run on it, it ticks at
the tick rate, and it ends with its run."""
import threading
import time

import pytest

from app.config import APP
from app.session.manager import SessionState
from tests._app import frames, frames_until, popups, runner_alive, start_connecting

_INTERVAL = 0.05


@pytest.fixture
def running(fresh_app, monkeypatch):
    """A mock session on its real runner, ticking every _INTERVAL s; `ticks` counts the runner's ticks."""
    monkeypatch.setattr(APP, "UPDATE_FREQUENCY", _INTERVAL)
    app, ticks = fresh_app, []
    tick = app._session.tick
    monkeypatch.setattr(app._session, "tick", lambda run: (ticks.append(threading.current_thread().name), tick(run)))
    app._on_start()
    frames_until(lambda: len(ticks) >= 2, 2.0)  # returns on timeout too: each wait's condition is asserted after it
    assert len(ticks) >= 2
    app.ticks = ticks
    return app


def _ticks_during(app, seconds: float) -> int:
    before = len(app.ticks)
    time.sleep(seconds)
    return len(app.ticks) - before


def test_the_runner_ticks_once_per_interval_on_its_own_thread(running):
    count = _ticks_during(running, 10 * _INTERVAL)
    assert 5 <= count <= 15, f"{count} ticks in ten intervals: stalled, or more than one writer"
    assert set(running.ticks) == {"SessionRunner"}


def test_a_command_runs_on_the_runner(running, monkeypatch):
    app, threads = running, []
    pause = app._session.manager.pause
    monkeypatch.setattr(app._session.manager, "pause", lambda: (threads.append(threading.current_thread().name), pause()))
    app._on_pause()
    frames_until(lambda: app._session.manager.state == SessionState.PAUSED, 2.0)
    assert app._session.manager.state == SessionState.PAUSED and threads == ["SessionRunner"]


def test_a_paused_session_records_nothing_until_it_resumes(running):
    app = running
    app._on_pause()
    frames_until(lambda: app._live_screen._btn_pause.text == "Resume", 2.0)  # its Paused event reached the screen
    assert app._live_screen._btn_pause.text == "Resume" and app._session.manager.state == SessionState.PAUSED
    recorded = len(app._shown.mirror.metrics)
    time.sleep(6 * _INTERVAL)
    assert len(app._shown.mirror.metrics) == recorded
    app._on_pause()
    frames_until(lambda: len(app._shown.mirror.metrics) > recorded, 2.0)
    assert len(app._shown.mirror.metrics) > recorded and app._session.manager.state == SessionState.RUNNING


def test_the_session_records_while_the_stop_dialog_is_open(running):
    # Cancel loses nothing; Stop saves up to then.
    app = running
    app._on_stop()
    (confirm,) = popups()
    recorded = len(app._shown.mirror.metrics)
    frames_until(lambda: len(app._shown.mirror.metrics) >= recorded + 3, 2.0)
    assert len(app._shown.mirror.metrics) >= recorded + 3
    confirm.dismiss()  # Cancel
    assert app._session.manager.state == SessionState.RUNNING and runner_alive(app)


def test_the_runner_ends_with_its_run_and_a_late_command_does_nothing(running):
    app = running
    run = app._session.run
    app._stop_and_save()
    frames_until(lambda: app._session.run is None and not runner_alive(app), 2.0)
    assert app._session.run is None and not runner_alive(app) and run.phase.name == "ENDED"
    app._on_pause()  # a tap that came after the end
    frames()
    assert app._session.manager.state == SessionState.IDLE and app._live_screen._btn_pause.text == "Pause"


def test_one_failing_tick_does_not_end_the_runner(running, monkeypatch):
    app = running
    process, failed = app._session.engine.process_sample, []

    def fails_once(raw, threshold):
        if not failed:
            failed.append(True)
            raise ValueError("a bad sample")
        return process(raw, threshold)

    monkeypatch.setattr(app._session.engine, "process_sample", fails_once)
    recorded = len(app._shown.mirror.metrics)
    frames_until(lambda: failed and len(app._shown.mirror.metrics) > recorded + 1, 2.0)
    assert failed and len(app._shown.mirror.metrics) > recorded + 1 and runner_alive(app)


def _stuck_in_its_first_read(app, monkeypatch) -> tuple[threading.Event, threading.Event]:
    """The next runner's first session tick stays in its read until `release` is set; `in_read` says it is there."""
    in_read, release, read = threading.Event(), threading.Event(), app._session.mock_stream.read_sample

    def sticks_once():
        if not in_read.is_set():
            in_read.set()
            release.wait(5)
        return read()

    monkeypatch.setattr(app._session.mock_stream, "read_sample", sticks_once)
    return in_read, release


def test_a_stop_ends_and_saves_the_session_even_when_its_runner_is_stuck(fresh_app, monkeypatch):
    # The runner doesn't take the Stop within a second (a read stuck on the link): the Stop ends the run where it was
    # sent, and the runner, once its read returns, records nothing for it.
    monkeypatch.setattr(APP, "UPDATE_FREQUENCY", _INTERVAL)
    app = fresh_app
    in_read, release = _stuck_in_its_first_read(app, monkeypatch)
    app._on_start()
    runner = app._session._runner
    assert in_read.wait(2)
    app._stop_and_save()
    frames()
    assert app._session.run is None and app._db.count_sessions(app._current_user_id) == 1
    release.set()
    runner.join(2)
    assert not runner.is_alive() and app._session.recorder._buffer == []


def test_a_command_the_runner_took_is_waited_to_its_end(running, monkeypatch):
    # A profile's delete goes on only once the session's row is gone, however long the runner takes over it.
    app, deleted = running, []
    discard = app._session.recorder.discard
    monkeypatch.setattr(app._session.recorder, "discard", lambda: (time.sleep(1.5), discard(), deleted.append(True)))
    app._discard_running_session()
    assert deleted == [True]  # once, on the runner, and done before the call returned


def test_an_overrun_tick_is_not_followed_by_a_catch_up_tick(fresh_app, monkeypatch):
    # Two ticks back to back read the same sample: a doubled row, and half a second too many on the timer.
    interval = 0.2  # long enough that a stalled frame in this test's own loop can't pass for a catch-up
    monkeypatch.setattr(APP, "UPDATE_FREQUENCY", interval)
    app, starts = fresh_app, []
    tick = app._session.tick

    def timed(run):
        starts.append(time.monotonic())
        if len(starts) == 2:
            time.sleep(3 * interval)  # this one overruns three ticks
        tick(run)

    monkeypatch.setattr(app._session, "tick", timed)
    app._on_start()
    frames_until(lambda: len(starts) >= 4, 5.0)
    assert len(starts) >= 4
    assert starts[3] - starts[2] >= 0.5 * interval, starts  # the tick after the overrun's: an interval later, not at once


def test_a_stop_does_not_hold_the_screen_through_a_slow_save(running, monkeypatch):
    # The Stop's tap returns once the runner has taken it: a save that waits (the write lock, slow storage) would
    # freeze the screen, and Android closes an app whose touch handler doesn't return.
    app = running
    save = app._db.checkpoint_session
    monkeypatch.setattr(app._db, "checkpoint_session", lambda *a, **k: (time.sleep(1.5), save(*a, **k))[1])
    began = time.monotonic()
    app._stop_and_save()
    assert time.monotonic() - began < 1.0
    frames_until(lambda: app._session.run is None, 4.0)
    assert app._session.run is None and app._db.count_sessions(app._current_user_id) == 1


def test_closing_the_app_waits_for_the_running_sessions_final_save(build_app, monkeypatch):
    # The database closes next: a save still writing then would find it shut and lose the session's last stats.
    monkeypatch.setattr(APP, "UPDATE_FREQUENCY", _INTERVAL)
    app, saves, finished = build_app(), [], []
    save = app._db.checkpoint_session

    def slow_final_save(*args, **kwargs):
        saves.append(True)
        if len(saves) == 2:  # the first is the leave's checkpoint; the second the stop's
            time.sleep(1.5)
        result = save(*args, **kwargs)
        if len(saves) == 2:
            finished.append(True)
        return result

    app._on_start()
    frames_until(lambda: len(app._shown.mirror.metrics) >= 2, 3.0)
    assert len(app._shown.mirror.metrics) >= 2
    monkeypatch.setattr(app._db, "checkpoint_session", slow_final_save)
    app.on_stop()
    assert finished == [True]


def test_a_late_runner_of_an_ended_run_leaves_the_next_runs_runner_in_place(fresh_app, monkeypatch):
    # Its read returned after the next Start: were it to clear the runner, the new session's commands would run on the
    # main thread beside its own runner.
    monkeypatch.setattr(APP, "UPDATE_FREQUENCY", _INTERVAL)
    app, threads = fresh_app, []
    in_read, release = _stuck_in_its_first_read(app, monkeypatch)
    app._on_start()
    old = app._session._runner
    assert in_read.wait(2)
    app._stop_and_save()  # the stuck runner doesn't take it: the Stop ends the run here
    frames()
    app._shown.close(keep_notes=False)
    app._on_start()
    new = app._session._runner
    release.set()
    old.join(2)
    assert not old.is_alive() and app._session._runner is new and new.is_alive()
    pause = app._session.manager.pause
    monkeypatch.setattr(app._session.manager, "pause", lambda: (threads.append(threading.current_thread().name), pause()))
    app._on_pause()
    frames_until(lambda: bool(threads), 2.0)
    assert threads == ["SessionRunner"]


def test_a_start_after_a_stuck_runners_run_ended_puts_its_own_threshold_in_force(fresh_app, monkeypatch):
    # The runner still in its read serves no run: the Start's threshold, queued to it, would wait for the read to
    # return, and the session, waiting for the headset, would start and be scored on what the last one left.
    monkeypatch.setattr(APP, "UPDATE_FREQUENCY", _INTERVAL)
    app = fresh_app
    in_read, release = _stuck_in_its_first_read(app, monkeypatch)
    app._on_start()
    old = app._session._runner
    assert in_read.wait(2)
    app._stop_and_save()  # the stuck runner doesn't take it: the Stop ends the run here
    frames()
    app._shown.close(keep_notes=False)
    setting = app._settings_screen.threshold
    app._session.manager.set_threshold(setting - 20)  # as a program's last segment leaves it
    start_connecting(app, monkeypatch)
    assert old.is_alive() and app._session.manager.threshold == setting
    app._cancel_session_start("IDLE")
    release.set()
    old.join(2)
    assert not old.is_alive()


def test_a_late_runner_drops_what_was_queued_for_its_ended_run(fresh_app, monkeypatch):
    # A threshold queued behind its stuck read would, carried out when the read returns, replace the next session's.
    monkeypatch.setattr(APP, "UPDATE_FREQUENCY", _INTERVAL)
    app = fresh_app
    in_read, release = _stuck_in_its_first_read(app, monkeypatch)
    app._on_start()
    old = app._session._runner
    assert in_read.wait(2)
    app._session.set_threshold(40)  # queued behind the stuck read
    app._stop_and_save()
    frames()
    app._shown.close(keep_notes=False)
    app._on_start()
    in_force = app._session.manager.threshold
    assert in_force != 40
    release.set()
    old.join(2)
    assert not old.is_alive() and app._session.manager.threshold == in_force
