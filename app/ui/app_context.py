"""What a flow reaches the app through: its database, the active profile, the main thread, navigation, the user's dialogs,
the profile's settings and the running session. Built once by the app; a flow takes it and then only what is its own."""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.storage.database import DatabaseManager


@dataclass(frozen=True)
class SessionAccess:
    """What a flow may know of the running session, and what it may change in it: end it (its profile deleted), and an
    edited formula line, which a session takes mid-run (it runs on what its Start read otherwise)."""

    live: Callable[[], bool]  # runs, is paused, or waits for the headset
    running_id: Callable[[], int | None]  # its row, once checkpointed, while it runs
    refused: Callable[..., bool]  # (doing, why=""): True, after telling the user, while it runs
    discard: Callable[[], None]
    set_formula: Callable[[int, str, str], None]  # (slot index, name, formula): the session's line follows the slot


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
    setting: Callable[[str], Any]  # a held setting's value for the active profile
    change_setting: Callable[[str, Any], None]  # a held setting's one change path: hold, apply, persist
    save_settings: Callable[[], None]
    session: SessionAccess
