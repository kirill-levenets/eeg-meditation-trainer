"""A module's theme tests share one screen per class, handed back in the view it was built with."""
from app.ui.diary_screen import DiaryScreen
from app.ui.history_screen import HistoryScreen
from app.ui.live_session import LiveSessionScreen
from app.ui.settings_screen import SettingsScreen


def sections(screen) -> list:
    """The screen's accordion sections, not those of a widget mounted after it."""
    return [w for w in screen.walk(restrict=True) if type(w).__name__ == "_AccordionSection"]


def _restore_live(s: LiveSessionScreen, state: tuple) -> None:
    s.hide_summary()
    s.hide_overlay()
    s.set_stats_mode(state[1])
    s._set_view(state[0])


def _restore_history(h: HistoryScreen, state: tuple) -> None:
    h.set_select_mode(state[1])
    h.set_view_mode(state[0])


def _restore_settings(s: SettingsScreen, state: tuple) -> None:
    s.timer.set_program_mode(state[0])
    for sec, collapsed in zip(sections(s), state[1], strict=True):
        sec._set_collapsed(collapsed, notify=False)


# Per class: the view state a test may change, and how to put it back.
_VIEW = {
    LiveSessionScreen: (lambda s: (s._active_view, s._stats_mode, s._summary.parent is not None, s._overlay.opacity),
                        _restore_live),
    HistoryScreen: (lambda h: (h._view_mode, h._select_mode), _restore_history),
    DiaryScreen: (lambda d: (d._active_graph_tab,), lambda d, state: d._switch_graph_tab(state[0])),
    SettingsScreen: (lambda s: (s.timer._program_mode, tuple(x._collapsed for x in sections(s))), _restore_settings),
}


class SharedScreens:
    """Building a screen is most of a theme test's time; the view a test leaves is what the next one must not see."""

    def __init__(self):
        self._built: dict = {}

    def __call__(self, cls):
        state, restore = _VIEW[cls]
        if cls not in self._built:
            screen = cls()
            self._built[cls] = screen, state(screen)
            return screen
        screen, as_built = self._built[cls]
        restore(screen, as_built)
        assert state(screen) == as_built, f"{cls.__name__} not back in its built view: {state(screen)} != {as_built}"
        return screen
