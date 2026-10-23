"""At most one SessionTick thread: two doubled every tick (timer, stats, saved rows, graph) for the rest of the session."""

import threading
import time
from unittest.mock import MagicMock

from app.config import APP
from app.session import tick_thread
from app.session.manager import SessionState
from app.session.tick_thread import TickThread
from app.ui.app_manager import EEGMeditationApp


def _live_ticks() -> int:
    return sum(1 for t in threading.enumerate() if t.name == "SessionTick" and t.is_alive())


def _app(update_tick):
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._ticker = TickThread(lambda dt: app._update_tick(dt))
    app._session_manager = MagicMock()
    app._session_manager.state = SessionState.RUNNING
    app._session_manager.pause.side_effect = lambda: setattr(app._session_manager, "state", SessionState.PAUSED)
    app._session_manager.resume.side_effect = lambda: setattr(app._session_manager, "state", SessionState.RUNNING)
    app._live_screen = MagicMock()
    app._audio = MagicMock()
    app._update_tick = update_tick
    return app


def test_stop_then_cancel_while_paused_then_resume_runs_one_tick_thread(monkeypatch):
    interval = 0.1
    monkeypatch.setattr(APP, "UPDATE_FREQUENCY", interval)
    ticks = []
    app = _app(lambda dt: ticks.append(1) if app._session_manager.state == SessionState.RUNNING else None)
    base = _live_ticks()
    try:
        app._ticker.start()
        app._on_pause()                 # Pause
        app._ticker.stop()         # Stop: the confirm dialog opens with the tick stopped
        app._cancel_stop()               # Cancel while still paused
        assert _live_ticks() == base, "a paused session must not get its tick back from Cancel"
        app._on_pause()                 # Resume
        assert _live_ticks() == base + 1
        ticks.clear()
        time.sleep(10 * interval)  # one thread ticks at most 11 times, two about 21
        assert len(ticks) >= 5, f"{len(ticks)} ticks in ten intervals: the tick stalled or ran at another interval"
        assert len(ticks) <= 15, f"{len(ticks)} ticks in ten intervals: more than one tick thread"
    finally:
        app._ticker.stop()


def test_cancel_while_running_restarts_the_tick():
    app = _app(lambda dt: None)
    base = _live_ticks()
    try:
        app._ticker.start()
        app._ticker.stop()
        app._cancel_stop()
        assert _live_ticks() == base + 1
    finally:
        app._ticker.stop()


def test_starting_twice_keeps_one_thread():
    app = _app(lambda dt: None)
    base = _live_ticks()
    try:
        app._ticker.start()
        app._ticker.start()
        assert _live_ticks() == base + 1
    finally:
        app._ticker.stop()


def test_a_restart_cannot_revive_a_thread_whose_stop_timed_out(monkeypatch):
    monkeypatch.setattr(tick_thread, "_STOP_JOIN_SECONDS", 0.2)
    slow = threading.Event()

    def update_tick(dt):
        if not slow.is_set():
            slow.set()
            time.sleep(0.4)  # longer than stop()'s 0.2 s join below

    app = _app(update_tick)
    base = _live_ticks()
    try:
        app._ticker.start()
        slow.wait(1.0)
        app._ticker.stop()         # join times out; the old thread is still inside its slow tick
        app._ticker.start()        # restart: the old thread must still see its own stop
        deadline = time.monotonic() + 2.0
        while _live_ticks() > base + 1 and time.monotonic() < deadline:
            time.sleep(0.01)       # until the slow tick returns and its thread, stopped, exits
        assert _live_ticks() == base + 1
    finally:
        app._ticker.stop()
