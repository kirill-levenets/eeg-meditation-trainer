"""AppContexts for tests. `make_context` is the app's, for an app built with __new__, as build() makes it: each callable
reads the app when called, so a test can set the app's state or swap a method after; the DB is the app's at
construction. `stub_context` stands alone: no profile, no session, UI calls run at once or are mocks. Either takes any
field, a SessionAccess field (live, running_id, refused, discard) included."""
from unittest.mock import MagicMock

from app.ui.app_context import AppContext, SessionAccess

_SESSION_FIELDS = ("live", "running_id", "refused", "discard")
_FIELDS = (*AppContext.__dataclass_fields__, *_SESSION_FIELDS)


def context_fields(deps: dict) -> dict:
    """Takes a helper's context fields out of its other dependencies."""
    return {k: deps.pop(k) for k in _FIELDS if k in deps}


def _build(defaults: dict, session_defaults: dict, fields: dict) -> AppContext:
    session = fields.pop("session", None) or SessionAccess(
        **{**session_defaults, **{k: fields.pop(k) for k in _SESSION_FIELDS if k in fields}})
    return AppContext(session=session, **{**defaults, **fields})


def make_context(app, **fields) -> AppContext:
    session = {"live": lambda: app._session_pipeline_live(), "running_id": lambda: app._running_session_id(),
               "refused": lambda doing, why="": app._refused_while_session_runs(doing, why),
               "discard": lambda: app._discard_running_session()}
    defaults = {"db": getattr(app, "_db", None) or MagicMock(), "user_id": lambda: app._current_user_id,
                "activate_user": lambda uid: app._activate_user(uid), "require_user": lambda a: app._require_user(a),
                "on_main": lambda fn: app._on_main(fn), "switch_screen": lambda name: app._switch_screen(name),
                "info": lambda title, message: app._info_popup(title, message),
                "toast": lambda message: app._toast(message), "confirm": lambda *a, **k: app._confirm_action(*a, **k),
                "save_settings": lambda: app._save_user_settings()}
    return _build(defaults, session, fields)


def stub_context(**fields) -> AppContext:
    """`user_id` given alone is also the profile require_user lets through."""
    user_id = fields.get("user_id", lambda: None)
    session = {"live": lambda: False, "running_id": lambda: None,
               "refused": MagicMock(return_value=False), "discard": MagicMock()}
    defaults = {"db": MagicMock(), "user_id": user_id, "activate_user": MagicMock(),
                "require_user": lambda _action: user_id(), "on_main": lambda fn: fn(), "switch_screen": MagicMock(),
                "info": MagicMock(), "toast": MagicMock(), "confirm": MagicMock(), "save_settings": MagicMock()}
    return _build(defaults, session, fields)
