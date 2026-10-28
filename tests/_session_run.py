"""A run for an app built with __new__, as the app's Start would make it."""
from app.session.session_run import Phase, SessionRun


def run_in(app, phase: Phase = Phase.STARTED) -> SessionRun:
    run = app._run = SessionRun(getattr(app, "_current_user_id", None))
    run.phase = phase
    return run
