"""The app's AppContext for an app built with __new__, as build() makes it: each callable reads the app when called, so a
test can set the app's state or swap a method after; the DB is the app's at construction. Any field can be given."""
from unittest.mock import MagicMock

from app.ui.app_context import AppContext, SessionAccess


def make_context(app, **fields) -> AppContext:
    session = fields.pop("session", None) or SessionAccess(
        live=lambda: app._session_pipeline_live(), connecting=lambda: app._connecting(),
        running_id=lambda: app._running_session_id(),
        refused=lambda doing, why="": app._refused_while_session_runs(doing, why),
        discard=lambda: app._discard_running_session())
    defaults = {"db": getattr(app, "_db", None) or MagicMock(), "user_id": lambda: app._current_user_id,
                "activate_user": lambda uid: app._activate_user(uid), "require_user": lambda a: app._require_user(a),
                "on_main": lambda fn: app._on_main(fn), "switch_screen": lambda name: app._switch_screen(name),
                "info": lambda title, message: app._info_popup(title, message),
                "toast": lambda message: app._toast(message), "confirm": lambda *a, **k: app._confirm_action(*a, **k),
                "save_settings": lambda: app._save_user_settings()}
    return AppContext(session=session, **{**defaults, **fields})
