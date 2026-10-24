"""A ProgramRun for an app built with __new__: no program running unless one is given, UI updates run at once, the
formula variables are the raw sample and the metrics."""
from unittest.mock import MagicMock

from app.ui.program_run import ProgramRun


def make_run(app=None, *, program=None, name: str = "", audio_key: str = "", session_manager=None, audio=None,
             live_screen=None, info=None, on_main=None) -> ProgramRun:
    """Its session manager, audio and live screen are the app's when it has them; its popup is the app's, read when
    it shows one."""
    def dep(given, attr):
        if given is None:
            given = getattr(app, attr, None)
        return MagicMock() if given is None else given

    run = ProgramRun(dep(session_manager, "_session_manager"), dep(audio, "_audio"), dep(live_screen, "_live_screen"),
                     on_main=on_main or (lambda fn: fn()), formula_vars=lambda raw, metrics: {**raw, **metrics},
                     info=info or (MagicMock() if app is None else lambda title, msg: app._info_popup(title, msg)))
    run.program = program
    run.name = name
    run.audio_key = audio_key
    return run
