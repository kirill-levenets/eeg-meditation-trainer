"""The app's HistoryFlow and SessionDetailFlow wired to an app built with __new__, as build() wires them: their context
reads the app when used (tests/_context.py); the screens and the overlay are the app's at construction."""
from unittest.mock import MagicMock

from app.ui.history_flow import HistoryFlow
from app.ui.session_detail_flow import SessionDetailFlow
from tests._context import make_context


def make_history_flow(app, **ctx_fields) -> HistoryFlow:
    loading = getattr(app, "_loading_overlay", None) or MagicMock()
    return HistoryFlow(make_context(app, **ctx_fields), getattr(app, "_history_screen", None),
                       getattr(app, "_formulas", None), loading,
                       on_sessions_deleted=lambda ids: app._shown.on_sessions_deleted(ids))


def make_detail_flow(app, **ctx_fields) -> SessionDetailFlow:
    return SessionDetailFlow(make_context(app, **ctx_fields), app._diary_screen, getattr(app, "_history_screen", None),
                             getattr(app, "_sm", None), getattr(app, "_graph_series", None))
