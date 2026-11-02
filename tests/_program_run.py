"""A ProgramRun for an app built with __new__: no program running unless one is given, UI updates run at once, the
formula variables are the raw sample and the metrics."""
from unittest.mock import MagicMock

from app.ui.program_run import ProgramRun
from tests._context import make_context, stub_context


def make_run(app=None, *, program=None, name: str = "", audio_key: str = "", session_manager=None, audio=None,
             live_screen=None, info=None, on_main=None) -> ProgramRun:
    """Its session manager, audio and live screen are the app's when it has them; its popup is the app's, read when
    it shows one."""
    def dep(given, attr):
        if given is None:
            given = getattr(app, attr, None)
        return MagicMock() if given is None else given

    fields = {"on_main": on_main or (lambda fn: fn()), **({"info": info} if info else {})}
    ctx = stub_context(**fields) if app is None else make_context(app, **fields)
    run = ProgramRun(ctx, dep(session_manager, "_session_manager"), dep(audio, "_audio"),
                     dep(live_screen, "_live_screen"), formula_vars=lambda raw, metrics: {**raw, **metrics})
    run.program = program
    run.name = name
    run.audio_key = audio_key
    return run
