"""The session's 2 Hz tick, on a daemon thread: it keeps running while Android's screen is locked, which a Kivy Clock
interval doesn't (compute, audio and DB work go on)."""
import threading
import time
from collections.abc import Callable

from app.config import APP
from app.logger import logger


class TickThread:
    """At most one tick thread runs: start() is a no-op while one is alive, and each thread gets its own stop event."""

    def __init__(self, tick: Callable[[float], None]) -> None:
        self._tick = tick
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event = threading.Event()

    @property
    def running(self) -> bool:
        """Started and not stopped since (the thread may be finishing a tick)."""
        return self._thread is not None

    def start(self) -> None:
        """Start the 2 Hz tick loop in a daemon thread (survives Android screen lock); no-op while one is running."""
        if self._thread is not None and self._thread.is_alive():
            return
        # Each thread gets its own stop event: clearing a shared one revived a thread whose stop join timed out.
        stop = threading.Event()
        self._stop_event = stop
        self._thread = threading.Thread(target=self._loop, args=(stop,), daemon=True, name="SessionTick")
        self._thread.start()
        logger.debug("SessionTick thread started")

    def stop(self) -> None:
        """Signal the tick thread to exit and join briefly.

        Safe to call from the tick thread itself: skips join() in that case
        (joining the current thread raises RuntimeError, which would swallow
        the rest of the calling tick — that bug caused the connect-overlay
        countdown to freeze when BT failure paths called this from inside
        _handle_bt_wait).
        """
        self._stop_event.set()
        t = self._thread
        self._thread = None
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.0)
        logger.debug("SessionTick thread stopped")

    def _loop(self, stop: threading.Event) -> None:
        """Call the tick every UPDATE_FREQUENCY seconds until this thread's stop is set."""
        interval = APP.UPDATE_FREQUENCY
        next_t = time.monotonic()
        while not stop.is_set():
            try:
                self._tick(interval)
            except Exception:  # noqa: BLE001 - one failing tick must not end the session's loop
                logger.exception("Error in session tick loop")
            next_t += interval
            remaining = next_t - time.monotonic()
            if remaining > 0:
                if stop.wait(remaining):
                    break
            else:
                next_t = time.monotonic()
