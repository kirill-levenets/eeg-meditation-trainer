"""What a flow reaches the app through: its database, the active profile, the main thread, navigation, the user's dialogs,
the settings save and the running session. Built once by the app; a flow takes it and then only what is its own."""
from collections.abc import Callable
from dataclasses import dataclass

from app.storage.database import DatabaseManager


@dataclass(frozen=True)
class SessionAccess:
    """What a flow may know of the running session, and the one thing it may do to it (end it, its profile deleted)."""

    live: Callable[[], bool]  # runs, is paused, or waits for the headset
    running_id: Callable[[], int | None]  # its row, once checkpointed, while it runs
    refused: Callable[..., bool]  # (doing, why=""): True, after telling the user, while it runs
    discard: Callable[[], None]


@dataclass(frozen=True)
class AppContext:
    db: DatabaseManager
    user_id: Callable[[], int | None]
    activate_user: Callable[[int], None]  # every profile pick: its settings load, History marked dirty
    require_user: Callable[[str], int | None]  # the active profile, or a message saying why the action can't run
    on_main: Callable[[Callable], None]
    switch_screen: Callable[[str], None]
    info: Callable[[str, str], None]
    toast: Callable[[str], None]
    confirm: Callable[..., None]  # (title, message, ok_text, on_ok, ok_color=None, on_cancel=None)
    save_settings: Callable[[], None]
    session: SessionAccess
