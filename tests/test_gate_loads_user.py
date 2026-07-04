"""Resolving the user gate must load the resolved user's per-user settings/UI.

Regression: after deleting the active profile the app re-enters the gate; picking or
creating a user went through _on_wizard_complete, which set _current_user_id but never
called _load_user_settings — so the deleted/previous user's saved-programs list (and
other per-user UI) lingered on screen, and delete-by-index silently no-op'd on the
stale rows. First-run masked it (no prior state)."""
from unittest.mock import MagicMock

from app.ui.app_manager import EEGMeditationApp


def _gate_app(created_uid):
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    db = MagicMock()
    db.create_user.return_value = created_uid
    app._db = db
    for attr in ("_real_stream", "_settings_screen", "_live_screen", "_bottom_nav",
                 "_sm", "_auto_scan_bt", "_refresh_profile", "_load_user_settings"):
        setattr(app, attr, MagicMock())
    return app


def test_gate_create_loads_new_users_settings():
    app = _gate_app(created_uid=5)
    app._on_wizard_complete("NewUser", None, None)
    assert app._current_user_id == 5
    app._load_user_settings.assert_called_once_with(5)


def test_gate_adopt_existing_loads_that_users_settings():
    from app.storage.database import UserExistsError
    app = _gate_app(created_uid=0)
    app._db.create_user.side_effect = UserExistsError(9, "Existing")
    app._on_wizard_complete("Existing", None, None)
    assert app._current_user_id == 9
    app._load_user_settings.assert_called_once_with(9)
