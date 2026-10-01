"""At most one SessionTick thread: two doubled every tick (timer, stats, saved rows, graph) for the rest of the session."""

import threading
import time
from unittest.mock import MagicMock

from app.session.manager import SessionState
from app.ui.app_manager import EEGMeditationApp


def _live_ticks() -> int:
    return sum(1 for t in threading.enumerate() if t.name == "SessionTick" and t.is_alive())


def _app(update_tick):
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._tick_stop_event = threading.Event()
    app._tick_thread = None
    app._session_manager = MagicMock()
    app._session_manager.state = SessionState.RUNNING
    app._session_manager.pause.side_effect = lambda: setattr(app._session_manager, "state", SessionState.PAUSED)
    app._session_manager.resume.side_effect = lambda: setattr(app._session_manager, "state", SessionState.RUNNING)
    app._live_screen = MagicMock()
    app._audio = MagicMock()
    app._update_tick = update_tick
    return app


def test_stop_then_cancel_while_paused_then_resume_runs_one_tick_thread():
    ticks = []
    app = _app(lambda dt: ticks.append(1) if app._session_manager.state == SessionState.RUNNING else None)
    base = _live_ticks()
    try:
        app._start_tick_thread()
        app._on_pause()                 # Pause
        app._stop_tick_thread()         # Stop: the confirm dialog opens with the tick stopped
        app._cancel_stop()               # Cancel while still paused
        assert _live_ticks() == base, "a paused session must not get its tick back from Cancel"
        app._on_pause()                 # Resume
        assert _live_ticks() == base + 1
        ticks.clear()
        time.sleep(2.0)
        assert len(ticks) <= 5, f"{len(ticks)} ticks in 2 s: more than one tick thread"
    finally:
        app._stop_tick_thread()


def test_cancel_while_running_restarts_the_tick():
    app = _app(lambda dt: None)
    base = _live_ticks()
    try:
        app._start_tick_thread()
        app._stop_tick_thread()
        app._cancel_stop()
        assert _live_ticks() == base + 1
    finally:
        app._stop_tick_thread()


def test_starting_twice_keeps_one_thread():
    app = _app(lambda dt: None)
    base = _live_ticks()
    try:
        app._start_tick_thread()
        app._start_tick_thread()
        assert _live_ticks() == base + 1
    finally:
        app._stop_tick_thread()


def test_a_restart_cannot_revive_a_thread_whose_stop_timed_out():
    slow = threading.Event()

    def update_tick(dt):
        if not slow.is_set():
            slow.set()
            time.sleep(1.6)  # longer than _stop_tick_thread's 1 s join

    app = _app(update_tick)
    base = _live_ticks()
    try:
        app._start_tick_thread()
        slow.wait(1.0)
        app._stop_tick_thread()         # join times out; the old thread is still inside its slow tick
        app._start_tick_thread()        # restart: the old thread must still see its own stop
        time.sleep(1.2)                 # the slow tick has returned by now
        assert _live_ticks() == base + 1
    finally:
        app._stop_tick_thread()
