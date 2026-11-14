"""A ProgramRun on its own: no program running unless one is given, the formula variables are the raw sample and the
metrics. Its screen events go to `show` and, from the runner, to `emit` (both at once unless given)."""
from unittest.mock import MagicMock

from app.ui.program_run import ProgramRun
from app.ui.shown_session import ShownSession
from tests._context import stub_context


def shown_on(live_screen) -> ShownSession:
    """The Session screen's side of a session, on `live_screen`: what applies the session's screen events."""
    return ShownSession(stub_context(), live_screen, MagicMock(), MagicMock(), MagicMock())


def make_run(*, program=None, name: str = "", audio_key: str = "", session_manager=None, audio=None,
             show=None, emit=None) -> ProgramRun:
    """Mocks for the session manager and the audio unless given; events shown on a mock Session screen unless `show`."""
    show = show or shown_on(MagicMock()).show
    run = ProgramRun(session_manager or MagicMock(), audio or MagicMock(), show=show,
                     emit=emit or (lambda _run, event: show(event)),
                     formula_vars=lambda raw, metrics: {**raw, **metrics})
    run.program = program
    run.name = name
    run.audio_key = audio_key
    return run
