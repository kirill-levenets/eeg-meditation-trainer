"""The active profile's scalar settings (`app/settings/registry.py`): one change path that holds, applies and persists a
value, at once or once a continuous input settles, and their load and save. Each setting is defined by what holds it."""
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from kivy.clock import Clock

from app.crash_handler import report_soft_error
from app.logger import logger
from app.settings.registry import Setting, SettingsStore


class UserSettings:
    """A setting the store holds changes only through `change`; one its widget holds is persisted through `changed`
    after the widget changed it. Nothing is persisted while a profile's settings load (`loading`)."""

    SETTLE_S: float = 0.5  # quiet time before a slider drag or typing is written

    def __init__(self, db, user_id: Callable[[], int | None]) -> None:
        self._db = db
        self._user_id = user_id
        self._store: SettingsStore | None = None  # registered once the screens hold their values
        self._loading = False
        self._settle_triggers: dict = {}  # input name -> its settle trigger
        self._settle_fns: dict = {}  # input name -> the latest function given for it

    def register(self, settings: list[Setting]) -> None:
        """Once, before any profile's load: a kept setting's default is its holder's value now, and a load applies
        them in this order."""
        self._store = SettingsStore(self._db, settings)

    def value(self, key: str) -> Any:
        """A held setting's value: its default until a profile's load."""
        return self._store.value(key)

    def change(self, key: str, value: Any) -> None:
        """A held setting's one change path: hold and apply the value, then persist it."""
        self._store.change(key, value)
        self.changed(key)

    def changed(self, key: str) -> None:
        """A setting changed (its widget did, or `change`): persisted now, or once a continuous input settles."""
        if self._loading:
            return
        if self._store.settles(key):
            self.after_settle(key, lambda: self._persist(key))
        else:
            self._persist(key)

    def _persist(self, key: str) -> None:
        try:
            written = self._store.persist(self._user_id(), key)
        except sqlite3.Error as e:
            # The value stays applied in memory; the next batch save retries it.
            report_soft_error("settings_save_failed", f"Couldn't save setting {key!r}: {e}")
            return
        if written is not None:
            logger.info(f"Setting {key} = {written!r}")

    def after_settle(self, name: str, fn: Callable[[], None]) -> None:
        """Run the latest `fn` given for input `name` once it has stopped changing for SETTLE_S."""
        self._settle_fns[name] = fn
        trigger = self._settle_triggers.get(name)
        if trigger is None:
            trigger = self._settle_triggers[name] = Clock.create_trigger(lambda _dt: self._settle_fns[name](),
                                                                         self.SETTLE_S)
        trigger.cancel()  # restart the settle window on every change
        trigger()

    @contextmanager
    def loading(self) -> Iterator[None]:
        """While a profile's settings load (the store's and its owners'): the values they apply are not persisted."""
        self._loading = True
        try:
            yield
        finally:
            self._loading = False

    def load(self, uid: int) -> None:
        """Apply every setting for `uid`: its stored value if present and valid, else its default."""
        self._store.load(uid)

    def save(self, uid: int) -> None:
        """Persist every setting's current value for `uid` in one transaction."""
        self._store.save(uid)
