"""Which screen shows: a bottom tab, a flow's switch (its tab marked), and Android's back key or Esc, which closes what is
open, goes back toward the Session screen, and on it exits on a second press."""
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from kivy.app import App
from kivy.core.window import Window
from kivy.uix.modalview import ModalView

from app.logger import logger
from app.ui.app_context import AppContext


@dataclass(frozen=True)
class ScreenHooks:
    """A screen's own part in navigation: what it refreshes as it is switched to, and what Android's back does on it
    (None: back to the Session screen)."""

    entering: Callable[[], None] | None = None
    back: Callable[[], None] | None = None


class Navigation:
    """The back key never falls through into the app while the profile gate is up, but a double press still exits: a
    first-run user who declines to create a profile must be able to leave. Its collaborators: the context, the screens
    and their tabs, the two overlays a back press closes first (the gate, a fullscreen graph), each screen's hooks."""

    TABS = (("Session", "session", "live_session"), ("History", "history", "history"),
            ("Settings", "settings", "settings"))  # the bottom tabs: label, key, screen
    _SCREEN_OF = {key: screen for _label, key, screen in TABS}
    _EXIT_WINDOW_S = 2.0  # a second back press within this exits

    def __init__(self, ctx: AppContext, sm, bottom_nav, *, gate, fullscreen,
                 screens: Mapping[str, ScreenHooks]) -> None:
        self._ctx = ctx
        self._sm = sm
        self._bottom_nav = bottom_nav
        self._gate = gate
        self._fullscreen = fullscreen
        self._screens = screens
        self._last_back = 0.0

    def on_tab(self, tab_key: str) -> None:
        """A bottom tab pressed."""
        self.switch(self._SCREEN_OF.get(tab_key, tab_key))

    def switch(self, name: str) -> None:
        """Show screen `name`, refreshed as it is entered, with its tab marked."""
        logger.debug(f"Screen switch: {name}")
        self._sm.current = name
        hooks = self._screens.get(name)
        if hooks is not None and hooks.entering is not None:
            hooks.entering()
        for _label, key, screen in self.TABS:
            if screen == name:
                self._bottom_nav.active_tab = key
                break

    def on_keyboard(self, _window, key, *_args) -> bool:
        """Android's back (key 27) or Esc; True consumes it, so Kivy's own exit on escape never fires."""
        if key != 27:
            return False
        if self._gate.active():  # also before its popup opens: the gate is up from the first frame
            return self._exit_on_second_back()
        if any(isinstance(c, ModalView) for c in Window.children):
            return False  # an open popup dismisses itself on escape
        if self._fullscreen.close():
            return True
        current = self._sm.current
        hooks = self._screens.get(current)
        if hooks is not None and hooks.back is not None:
            hooks.back()
            return True
        if current != "live_session":
            self.switch("live_session")
            return True
        return self._exit_on_second_back()

    def _exit_on_second_back(self) -> bool:
        """A second back press within _EXIT_WINDOW_S exits the app; the first says so."""
        now = time.time()
        if now - self._last_back < self._EXIT_WINDOW_S:
            App.get_running_app().stop()
            return True
        self._last_back = now
        self._ctx.toast("Press back again to exit")
        return True
