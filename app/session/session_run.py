"""One Start of a session, from the press to its ending: its phase and the state that lives as long as it does. The app
holds the current run; a callback queued for an earlier one finds it replaced and does nothing."""
import threading
from enum import Enum

from app.logger import logger


class Phase(Enum):
    STARTING = "starting"  # Start pressed: finding the profile's headset, setting the session up
    CONNECTING = "connecting"  # the BT wait: the reader is up and the first data starts the session
    STARTED = "started"  # the session runs or is paused (SessionManager's state says which)
    ENDED = "ended"  # an ending began (a wait abandoned, a session stopped or discarded); terminal


class SessionRun:
    """A run's own state, so a new Start begins from nothing the last one left; the app drops it at the ending."""

    def __init__(self, user_id: int | None) -> None:
        self.user_id = user_id  # the profile it started for: a scan's result for another one does nothing
        self._phase = Phase.STARTING
        self._phase_lock = threading.Lock()  # the runner ends a run, and the main thread when no runner takes its command
        # The BT wait, per connection: a drop restarts the connect and no-data windows.
        self.connect_start = 0.0  # time.time(): when this connection's connect window began
        self.signal_start: float | None = None  # time.time(): the link came up, the no-data window began
        self.dropped_at = 0.0  # monotonic: the last drop; packets before it don't count
        self.drops = 0
        # The tick.
        self.tick_count = 0
        self.pending_marker = False  # a marker tapped, for the next recorded tick
        self.shamatha_active = False
        self.shamatha_streak = 0
        self.scored_key: str | None = None  # the series the live legend marks as scored
        self.noise_detector = None  # power-line noise, on a headset session
        self.bt_connected_notified = False  # the headset's link as the watch last followed it
        self.low_battery_warned = False
        self.stale_data_warned = False

    @property
    def phase(self) -> Phase:
        return self._phase

    @phase.setter
    def phase(self, phase: Phase) -> None:
        """ENDED is terminal: a tick that passed its check before the ending began can't revive the run."""
        if phase is Phase.ENDED:
            raise ValueError("a run ends through mark_ended(), its one claim")
        with self._phase_lock:
            refused = self._phase is Phase.ENDED
            if not refused:
                self._phase = phase
        if refused:
            logger.debug(f"Run already ended: {phase.value} not set")

    def mark_ended(self) -> bool:
        """An ending began: True for the one call that ended the run, so a single ending claims it."""
        with self._phase_lock:
            if self._phase is Phase.ENDED:
                return False
            self._phase = Phase.ENDED
            return True
