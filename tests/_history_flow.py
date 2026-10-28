"""The app's HistoryFlow and SessionDetailFlow wired to an app built with __new__, as build() wires them: the callbacks
read the app when they run, so a test can swap one after; the DB and the screens are the app's at construction."""
from app.ui.history_flow import HistoryFlow
from app.ui.session_detail_flow import SessionDetailFlow


def make_history_flow(app, **deps) -> HistoryFlow:
    defaults = {"user_id": lambda: app._current_user_id, "on_main": lambda fn: app._on_main(fn),
                "show_loading": lambda *a, **k: app.show_loading(*a, **k), "hide_loading": lambda: app.hide_loading(),
                "info": lambda *a: app._info_popup(*a), "toast": lambda message: app._toast(message),
                "running_session_id": lambda: app._running_session_id(),
                "on_sessions_deleted": lambda ids: app._on_sessions_deleted(ids)}
    return HistoryFlow(app._db, getattr(app, "_history_screen", None), getattr(app, "_formulas", None),
                       **{**defaults, **deps})


def make_detail_flow(app, **deps) -> SessionDetailFlow:
    defaults = {"user_id": lambda: app._current_user_id, "on_main": lambda fn: app._on_main(fn),
                "switch_screen": lambda name: app._switch_screen(name)}
    return SessionDetailFlow(app._db, app._diary_screen, getattr(app, "_history_screen", None), getattr(app, "_sm", None),
                             getattr(app, "_graph_series", None), **{**defaults, **deps})
