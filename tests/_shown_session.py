"""The app's ShownSession wired to an app built with __new__, as build() wires it: its context reads the app when used
(tests/_context.py); the Session screen, audio, history flow and recorder are the app's at construction, so a test
builds those first, as build() does."""
from app.ui.shown_session import ShownSession
from tests._context import make_context


def make_shown(app, **ctx_fields) -> ShownSession:
    return ShownSession(make_context(app, **ctx_fields), app._live_screen, getattr(app, "_audio", None),
                        getattr(app, "_history", None), getattr(app, "_recorder", None))
