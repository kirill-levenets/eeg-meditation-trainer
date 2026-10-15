"""A ProgramRun for an app built with __new__: no program running unless one is given, UI updates run at once, the
formula variables are the raw sample and the metrics."""
from unittest.mock import MagicMock

from app.ui.program_run import ProgramRun


def make_run(app=None, *, program=None, audio_key: str = "", session_manager=None, audio=None,
             live_screen=None) -> ProgramRun:
    """Its session manager, audio and live screen are the app's when it has them."""
    def dep(given, name):
        if given is None:
            given = getattr(app, name, None)
        return MagicMock() if given is None else given

    run = ProgramRun(dep(session_manager, "_session_manager"), dep(audio, "_audio"), dep(live_screen, "_live_screen"),
                     on_main=lambda fn: fn(), formula_vars=lambda raw, metrics: {**raw, **metrics})
    run.program = program
    run.audio_key = audio_key
    return run
