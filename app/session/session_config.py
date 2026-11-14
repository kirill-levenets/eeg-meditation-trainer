"""What a session runs with, read once at its Start: a Settings edit or a profile's reload during the run applies to the
next session."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionConfig:
    """A Start's choices. Only an explicit call changes a running session: the threshold of a simple session (the
    session manager owns it), an edited formula line (`RunningSession.set_formula`) and the lines the live graph shows
    (`RunningSession.set_shown`)."""

    metric: str  # the profile's metric that drives the sound; a program's segment overrides it
    formulas: tuple[dict, ...]  # the Settings slots' {name, formula}, as active_formulas stores them
    timer_minutes: int | None  # None: no timer
    gong: str  # the timer's end sound: "" for the default bell, and with no timer
    mock: bool  # on mock data, else the profile's headset
    device: str  # what the session is named after: the headset's name at Start, or "Mock"
    shown: frozenset[str]  # the live graph's shown lines: its formula lines' are saved with the session
