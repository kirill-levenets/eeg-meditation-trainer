"""Resolving the user gate must load the resolved user's per-user settings/UI.

Regression: after deleting the active profile the app re-enters the gate; picking or
creating a user went through complete_first_run, which set _current_user_id but never
called _load_user_settings — so the deleted/previous user's saved-programs list (and
other per-user UI) lingered on screen, and delete-by-index silently no-op'd on the
stale rows. First-run masked it (no prior state)."""
import sqlite3

import pytest

import app.ui.profiles as profiles
from app.config import APP
from tests._app import frames


@pytest.fixture
def gated(build_app, monkeypatch):
    """The app at its gate: profiles exist, none was last used. `app.mock` (threshold 85, on the mock) and `app.real`
    (threshold 70, real mode, no headset yet) are their ids; `app.scans` holds each headset scan begun."""
    def seed(db):
        mock = db.create_user("M")  # a name too short to type is still pickable
        db.set_user_setting(mock, "threshold", "85")
        db.set_user_setting(mock, "use_mock", "True")
        real = db.create_user("Existing")
        db.set_user_setting(real, "threshold", "70")
        db.set_user_setting(real, "use_mock", "False")
    app = build_app(seed)
    ids = {u["name"]: u["id"] for u in app._db.get_all_users()}
    app.mock, app.real, app.scans = ids["M"], ids["Existing"], []
    monkeypatch.setattr(app._headset, "find_paired", app.scans.append)  # the scan's Bluetooth half
    app._settings_screen.threshold = 33  # what the last profile left on screen
    return app


def _names(app) -> list[str]:
    return sorted(u["name"] for u in app._db.get_all_users())


def test_gate_create_loads_new_users_settings(gated):
    gated._gate.complete_first_run("NewUser")
    frames()
    new = next(u["id"] for u in gated._db.get_all_users() if u["name"] == "NewUser")
    assert gated._current_user_id == new and not gated._gate.active()
    assert gated._settings_screen.threshold not in (33, 70, 85)  # its own (the default), nobody else's
    assert gated._settings_screen._profile_current_label.text == "Current: NewUser"


def test_gate_adopt_existing_loads_that_users_settings(gated):
    gated._gate.complete_first_run("Existing")
    frames()
    assert gated._current_user_id == gated.real and gated._settings_screen.threshold == 70
    assert _names(gated) == ["Existing", "M"]  # picked, not made again


def test_gate_pick_existing_activates_it_by_id_with_its_own_settings(gated):
    gated._gate.pick_existing(gated.real)
    frames()
    assert gated._current_user_id == gated.real and gated._settings_screen.threshold == 70
    assert _names(gated) == ["Existing", "M"]
    assert gated._db.get_user_setting(gated.real, "use_mock") == "False" and APP.USE_MOCK_DEVICE is False  # its mode stays


def test_typing_an_existing_name_at_the_gate_picks_it_without_overwriting_its_mode(gated):
    gated._gate.complete_first_run("Existing")
    frames()
    assert gated._current_user_id == gated.real
    assert gated._db.get_user_setting(gated.real, "use_mock") == "False" and APP.USE_MOCK_DEVICE is False


def test_a_new_profile_is_saved_on_the_mock_before_its_load_then_scanned_for(gated):
    """Its load applies the mock, so it doesn't scan as a real-mode profile; the new profile's scan decides (#99)."""
    gated._gate.pick_existing(gated.real)  # the mode a load without the stored mock would leave behind
    gated.scans.clear()
    gated._gate.complete_first_run("NewUser")
    frames()
    assert gated._db.get_user_setting(gated._current_user_id, "use_mock") == "True" and APP.USE_MOCK_DEVICE is True
    assert len(gated.scans) == 1  # the new profile's own; a load in real mode would have begun another


def test_a_profile_picked_at_the_gate_is_scanned_for_only_by_its_load(gated):
    gated._gate.pick_existing(gated.mock)
    frames()
    assert gated.scans == []  # on the mock: no load scans, and the gate adds none
    gated._gate.pick_existing(gated.real)
    frames()
    assert len(gated.scans) == 1  # a real-mode profile without a headset: its load's scan, alone


def test_a_database_error_at_first_run_create_is_reported_not_raised(gated, monkeypatch):
    reported = []
    monkeypatch.setattr(profiles, "report_soft_error", lambda label, detail, **k: reported.append(label))

    def locked(_name):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(gated._db, "create_user", locked)
    gated._gate.complete_first_run("NewUser")
    assert reported == ["user_create_failed"]
    assert gated._current_user_id is None and gated._settings_screen.threshold == 33  # nothing was loaded
