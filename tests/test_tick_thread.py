"""At most one SessionTick thread: two doubled every tick (timer, stats, saved rows, graph) for the rest of the session."""

import threading
import time

from app.config import APP
from app.session import tick_thread
from app.session.manager import SessionState
from app.session.tick_thread import TickThread
from tests._app import popups


def _live_ticks() -> int:
    return sum(1 for t in threading.enumerate() if t.name == "SessionTick" and t.is_alive())


def test_stop_then_cancel_while_paused_then_resume_runs_one_tick_thread(fresh_app, monkeypatch):
    interval = 0.1
    monkeypatch.setattr(APP, "UPDATE_FREQUENCY", interval)
    app, ticks = fresh_app, []
    tick = app._update_tick
    monkeypatch.setattr(app, "_update_tick", lambda dt: (ticks.append(1), tick(dt))[1])
    base = _live_ticks()
    app._on_start()
    assert _live_ticks() == base + 1
    app._on_pause()  # Pause
    app._on_stop()  # Stop: the confirm dialog opens with the tick stopped
    (confirm,) = popups()
    confirm.dismiss()  # Cancel while still paused
    assert app._session.manager.state == SessionState.PAUSED
    assert _live_ticks() == base, "a paused session must not get its tick back from Cancel"
    app._on_pause()  # Resume
    assert _live_ticks() == base + 1
    ticks.clear()
    time.sleep(10 * interval)  # one thread ticks at most 11 times, two about 21
    assert len(ticks) >= 5, f"{len(ticks)} ticks in ten intervals: the tick stalled or ran at another interval"
    assert len(ticks) <= 15, f"{len(ticks)} ticks in ten intervals: more than one tick thread"


def test_cancel_while_running_restarts_the_tick(fresh_app):
    app = fresh_app
    base = _live_ticks()
    app._on_start()
    app._on_stop()  # the confirm dialog: the tick waits for the answer
    assert _live_ticks() == base
    (confirm,) = popups()
    confirm.dismiss()  # Cancel
    assert app._session.manager.state == SessionState.RUNNING and _live_ticks() == base + 1


def test_starting_twice_keeps_one_thread():
    ticker = TickThread(lambda dt: None)
    base = _live_ticks()
    try:
        ticker.start()
        ticker.start()
        assert _live_ticks() == base + 1
    finally:
        ticker.stop()


def test_a_restart_cannot_revive_a_thread_whose_stop_timed_out(monkeypatch):
    monkeypatch.setattr(tick_thread, "_STOP_JOIN_SECONDS", 0.2)
    slow = threading.Event()

    def update_tick(dt):
        if not slow.is_set():
            slow.set()
            time.sleep(0.4)  # longer than stop()'s 0.2 s join below

    ticker = TickThread(update_tick)
    base = _live_ticks()
    try:
        ticker.start()
        slow.wait(1.0)
        ticker.stop()         # join times out; the old thread is still inside its slow tick
        ticker.start()        # restart: the old thread must still see its own stop
        deadline = time.monotonic() + 2.0
        while _live_ticks() > base + 1 and time.monotonic() < deadline:
            time.sleep(0.01)       # until the slow tick returns and its thread, stopped, exits
        assert _live_ticks() == base + 1
    finally:
        ticker.stop()
