"""What a running session tells the screen: its runner's events reach the main thread for their run only; the ones its
start and ending raise there are shown at once."""
from dataclasses import dataclass

from app.session.manager import LiveScore
from app.session.session_program import RunnablePlan


@dataclass(frozen=True)
class Connected:
    """The headset's first data started the session."""


@dataclass(frozen=True)
class StartFailed:
    """The BT wait gave up; `message` is the retry screen's."""

    message: str


@dataclass(frozen=True)
class Ended:
    """The run ended: saved with `stats` as `session_id` (both None when the save failed), `alert` saying why if a check
    ended it."""

    stats: dict | None
    session_id: int | None
    alert: str = ""


@dataclass(frozen=True)
class Paused:
    """The session paused."""


@dataclass(frozen=True)
class Resumed:
    """The paused session goes on."""


@dataclass(frozen=True)
class Ticked:
    """A recorded tick, for the live graphs and readout: `shamatha` is the pill's new state (None: unchanged),
    `scored` the series the legend marks from this tick (None: unchanged)."""

    metrics: dict
    raw_sample: dict
    elapsed: str
    marked: bool
    shamatha: bool | None
    scored: str | None
    target: float
    score_key: str
    live: LiveScore


@dataclass(frozen=True)
class SegmentStarted:
    """A program segment began, trained on `key`; `line_name` labels a custom formula's line (None for a built-in)."""

    key: str
    line_name: str | None


@dataclass(frozen=True)
class ProgramShown:
    """A program's Start: the live graph shows exactly its lines."""

    plan: RunnablePlan


@dataclass(frozen=True)
class ProgramDropped:
    """The program's session ended: its lines and labels leave the live graph."""


@dataclass(frozen=True)
class Connecting:
    """The BT wait began, connecting to `name`."""

    name: str


@dataclass(frozen=True)
class Waiting:
    """The BT wait's progress."""

    message: str


@dataclass(frozen=True)
class Alert:
    """A warning to show over the session (low battery, power-line noise)."""

    message: str


@dataclass(frozen=True)
class LinkChanged:
    """The headset's link came up or dropped during the session."""


@dataclass(frozen=True)
class Notice:
    """A message that stays until read: the meditator may not be looking."""

    title: str
    message: str
