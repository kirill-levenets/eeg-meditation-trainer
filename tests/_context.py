"""An AppContext for a flow built on its own: `stub_context` has no profile and no session, and its UI calls run at
once or are mocks. It takes any field, a SessionAccess field (live, running_id, refused, discard, set_formula) included. The built
app makes its own (`EEGMeditationApp._make_context`): tests/_app.py."""
from unittest.mock import MagicMock

from app.ui.app_context import AppContext, SessionAccess

_SESSION_FIELDS = ("live", "running_id", "refused", "discard", "set_formula")
_FIELDS = (*AppContext.__dataclass_fields__, *_SESSION_FIELDS)


def context_fields(deps: dict) -> dict:
    """Takes a helper's context fields out of its other dependencies."""
    return {k: deps.pop(k) for k in _FIELDS if k in deps}


def _build(defaults: dict, session_defaults: dict, fields: dict) -> AppContext:
    session = fields.pop("session", None) or SessionAccess(
        **{**session_defaults, **{k: fields.pop(k) for k in _SESSION_FIELDS if k in fields}})
    return AppContext(session=session, **{**defaults, **fields})


def stub_context(**fields) -> AppContext:
    """`user_id` given alone is also the profile require_user lets through."""
    user_id = fields.get("user_id", lambda: None)
    session = {"live": lambda: False, "running_id": lambda: None,
               "refused": MagicMock(return_value=False), "discard": MagicMock(), "set_formula": MagicMock()}
    defaults = {"db": MagicMock(), "user_id": user_id, "activate_user": MagicMock(),
                "require_user": lambda _action: user_id(), "on_main": lambda fn: fn(), "switch_screen": MagicMock(),
                "info": MagicMock(), "toast": MagicMock(), "confirm": MagicMock(), "setting": MagicMock(),
                "change_setting": MagicMock(), "save_settings": MagicMock()}
    return _build(defaults, session, fields)
