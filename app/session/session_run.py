"""One Start of a session, from the press to its ending: its phase and the state that lives as long as it does. The app
holds the current run; a callback queued for an earlier one finds it replaced and does nothing."""
from enum import Enum


class Phase(Enum):
    STARTING = "starting"  # Start pressed: finding the profile's headset, setting the session up
    CONNECTING = "connecting"  # the BT wait: the reader is up and the first data starts the session
    STARTED = "started"  # the session runs or is paused (SessionManager's state says which)
    ENDED = "ended"  # a wait abandoned or a session discarded; the main thread's teardown is still to run


class SessionRun:
    """A run's own state, so a new Start begins from nothing the last one left; the app drops it at the ending."""

    def __init__(self, user_id: int | None) -> None:
        self.user_id = user_id  # the profile it started for: a scan's result for another one does nothing
        self.phase = Phase.STARTING
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
        self.bt_connected_notified = False  # Settings was told the headset's link is up
        self.low_battery_warned = False
        self.stale_data_warned = False
