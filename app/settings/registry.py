"""Code-defined per-user settings registry.

One `Setting` descriptor per preference is the single source of truth for its key,
default, type (parse/serialize), and live accessors (read/apply the in-memory field +
its UI widget). `SettingsStore` derives ALL behavior generically:

- load(uid): each setting = parsed stored value, or its default when absent/unparseable
  -> ALWAYS applies a value, so a fresh/partial user can never inherit the previously
  active user's in-memory value (the leak that motivated this module).
- save(uid): serialize every setting's live value.
- persist(uid, key): immediate single-key write, suppressed during load.

Replaces the ~100 hand-written save/load/default sites scattered across app_manager.
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.logger import logger


@dataclass(frozen=True)
class Setting:
    key: str
    default: Any
    parse: Callable[[str], Any]        # DB string -> typed value
    serialize: Callable[[Any], str]    # typed value -> DB string
    get: Callable[[], Any]             # read the live value (in-memory + UI)
    set: Callable[[Any], None]         # apply a value to the in-memory field + UI


# Codecs: (parse, serialize) pairs.
BOOL = (lambda s: s == "True", lambda v: str(bool(v)))
INT = (lambda s: int(s), lambda v: str(int(v)))
FLOAT = (lambda s: float(s), lambda v: str(float(v)))
STR = (lambda s: s, lambda v: "" if v is None else str(v))


class SettingsStore:
    """Generic load/save/persist over a list of Setting descriptors."""

    def __init__(self, db, settings: list[Setting]) -> None:
        self._db = db
        self._settings = list(settings)
        self._by_key = {s.key: s for s in self._settings}
        self._loading = False

    @property
    def loading(self) -> bool:
        return self._loading

    def load(self, uid: int) -> None:
        """Apply each setting for `uid`: stored value if present+valid, else its default."""
        self._loading = True
        try:
            for s in self._settings:
                raw = self._db.get_user_setting(uid, s.key)
                value = s.default
                if raw is not None:
                    try:
                        value = s.parse(raw)
                    except (ValueError, TypeError):
                        logger.warning(f"settings: invalid {s.key!r}={raw!r}; using default")
                s.set(value)
        finally:
            self._loading = False

    def save(self, uid: int) -> None:
        """Persist every setting's current live value for `uid`."""
        for s in self._settings:
            self._db.set_user_setting(uid, s.key, s.serialize(s.get()))

    def persist(self, uid: int, key: str) -> None:
        """Write one setting immediately (change-callback path). No-op with no user or
        while load() is applying values (those callbacks would re-persist what we read)."""
        if self._loading or not uid:
            return
        s = self._by_key.get(key)
        if s is not None:
            self._db.set_user_setting(uid, key, s.serialize(s.get()))
