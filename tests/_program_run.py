"""A ProgramRun on its own: no program running unless one is given, UI updates run at once, the formula variables are
the raw sample and the metrics."""
from unittest.mock import MagicMock

from app.ui.program_run import ProgramRun
from tests._context import stub_context


def make_run(*, program=None, name: str = "", audio_key: str = "", session_manager=None, audio=None,
             live_screen=None, info=None, on_main=None) -> ProgramRun:
    """Mocks for the session manager, the audio and the Session screen unless given."""
    fields = {"on_main": on_main or (lambda fn: fn()), **({"info": info} if info else {})}
    run = ProgramRun(stub_context(**fields), session_manager or MagicMock(), audio or MagicMock(),
                     live_screen or MagicMock(), formula_vars=lambda raw, metrics: {**raw, **metrics})
    run.program = program
    run.name = name
    run.audio_key = audio_key
    return run
