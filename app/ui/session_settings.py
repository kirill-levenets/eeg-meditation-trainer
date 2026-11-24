"""Settings as a session's Start and ending use them: what a Start reads into its config and prepares, a program's
threshold lock while it runs, and the program's idle series around it."""
from collections.abc import Callable

from app.logger import logger
from app.session.session_config import SessionConfig
from app.session.session_program import segment_target
from app.ui.app_context import AppContext
from app.ui.formatting import format_count


class SessionSettings:
    """A session reads Settings once, at its Start (`read`); nothing it runs on is read from Settings later."""

    def __init__(self, ctx: AppContext, settings_screen, program_settings, formulas) -> None:
        self._ctx = ctx
        self._settings_screen = settings_screen
        self._program_settings = program_settings
        self._formulas = formulas

    def read(self, *, mock: bool, device: str, lines: Callable[[], frozenset[str]]) -> SessionConfig:
        """The Start's config; `mock` and `device` are its choice of stream. The program's idle series is derived first,
        and only then the live graph's shown lines read (`lines`: the session saves its formula lines' as shown or hidden).
        A program's total drives the timer, so its end reuses the timer-expiry path."""
        self._program_settings.refresh_live_series()
        program = self._program_settings.for_session()
        timer = self._settings_screen.timer
        if program:
            minutes = max(1, int(round(program.total_seconds / 60)))
            logger.info(f"Program session: {format_count(len(program.segments), 'segment')}, "
                        f"{program.total_seconds:.0f}s total drives the end gong")
        else:
            minutes = timer.timer_minutes if timer.timer_enabled else None
        return SessionConfig(metric=self._ctx.setting("audio_metric"), formulas=tuple(self._formulas.active()),
                             timer_minutes=minutes, gong=self._ctx.setting("timer_sound") if minutes else "",
                             mock=mock, device=device, shown=lines(),
                             threshold=segment_target(program.segments[0]) if program else self._settings_screen.threshold,
                             program=program, program_name=self._program_settings.name)

    def started(self, config: SessionConfig, refuse: Callable[[], bool]) -> None:
        """A program's segments own its targets: its threshold controls refuse a touch (`refuse`) until the session ends."""
        self._settings_screen.lock_threshold(refuse if config.program else None)

    def teardown(self) -> None:
        """Every ending's, after the session's reset: the threshold controls free, the idle series derived again (while
        the session still read live, nothing was)."""
        self._settings_screen.lock_threshold(None)
        self._program_settings.sync_picker()

    def saved(self) -> None:
        """A session saved: Settings' profile counts redrawn if it is the screen shown (a timer can end a session there;
        else entering Settings redraws them)."""
        manager = self._settings_screen.manager
        if manager is not None and manager.current == self._settings_screen.name:
            self._settings_screen.refresh_profile_counts()
