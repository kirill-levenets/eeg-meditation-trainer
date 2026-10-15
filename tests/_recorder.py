"""A SessionRecorder wired to an app built with __new__, as __init__ wires it."""
from app.session.recorder import SessionRecorder


class _AppAttr:
    """Stands for the app's attribute as it is when used: a test may set the app's db or session manager after."""

    def __init__(self, app, name: str) -> None:
        self._app = app
        self._name = name

    def __getattr__(self, item):
        return getattr(getattr(self._app, self._name), item)


def make_recorder(app) -> SessionRecorder:
    return SessionRecorder(_AppAttr(app, "_db"), _AppAttr(app, "_session_manager"),
                           with_score=lambda stats: app._with_score(stats),
                           row_fields=lambda: app._session_row_fields())
