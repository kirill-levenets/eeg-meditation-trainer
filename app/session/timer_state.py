"""Pure-Python timer state for meditation sessions.

Replaces the orphan `TimerScreen` UI class — which lived in the screen
manager but had no nav entry, so its file picker / Test Sound / countdown
display were unreachable. The session-tick path now drives this state
object, and the Settings → Timer accordion owns all of the user-visible
controls (enable, duration, custom sound path, browse, test).
"""

from __future__ import annotations

from app.config import APP


class TimerState:
    """Headless timer state used by the session tick loop."""

    def __init__(self) -> None:
        self.enabled: bool = APP.TIMER_ENABLED
        self.duration_minutes: int = APP.TIMER_DEFAULT_MINUTES
        self.remaining_seconds: float = 0.0
        self.custom_sound_path: str = ""

    # --- mutators ---------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def set_duration(self, minutes: int) -> None:
        self.duration_minutes = max(1, int(minutes))

    def set_custom_sound_path(self, path: str) -> None:
        self.custom_sound_path = (path or "").strip()

    # --- lifecycle --------------------------------------------------------

    @property
    def duration_seconds(self) -> float:
        return self.duration_minutes * 60.0

    def start_countdown(self) -> None:
        """Initialise remaining time at session start. No-op if disabled."""
        if not self.enabled:
            return
        self.remaining_seconds = self.duration_seconds

    def tick(self, dt: float) -> bool:
        """Advance the countdown by `dt` seconds. Returns True on expiry."""
        if not self.enabled:
            return False
        self.remaining_seconds -= dt
        if self.remaining_seconds <= 0:
            self.remaining_seconds = 0.0
            return True
        return False

    def reset(self) -> None:
        self.remaining_seconds = 0.0
