"""Per-user settings registry: one Setting descriptor per preference; load always applies a value, so none leak."""
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


def stored_value(db, uid: int | None, s: Setting) -> Any:
    """`s` for `uid`: its stored value if present and valid, else its default."""
    raw = db.get_user_setting(uid, s.key) if uid else None
    if raw is None:
        return s.default
    try:
        return s.parse(raw)
    except (ValueError, TypeError):
        logger.warning(f"settings: invalid {s.key!r}={raw!r}; using default")
        return s.default


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
                s.set(stored_value(self._db, uid, s))
        finally:
            self._loading = False

    def save(self, uid: int) -> None:
        """Persist every setting's current live value for `uid` in one transaction."""
        self._db.set_user_settings(uid, {s.key: s.serialize(s.get()) for s in self._settings})

    def persist(self, uid: int, key: str) -> None:
        """Write one setting now; no-op with no user or while load() applies values it would re-persist."""
        if self._loading or not uid:
            return
        s = self._by_key.get(key)
        if s is not None:
            self._db.set_user_setting(uid, key, s.serialize(s.get()))
