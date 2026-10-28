"""The app's ShownSession wired to an app built with __new__, as build() wires it: the callbacks read the app when they
run; the Session screen, the mirror and the audio are the app's at construction."""
from app.ui.shown_session import ShownSession


def make_shown(app, **deps) -> ShownSession:
    defaults = {"save_notes": lambda sid, notes: app._history.save_notes(sid, notes=notes),
                "delete_sessions": lambda ids: app._history.delete_sessions(ids),
                "confirm": lambda *a, **k: app._confirm_action(*a, **k), "toast": lambda message: app._toast(message),
                "last_session_id": lambda: app._recorder.session_id}
    return ShownSession(app._live_screen, getattr(app, "_mirror", None), getattr(app, "_audio", None),
                        **{**defaults, **deps})
