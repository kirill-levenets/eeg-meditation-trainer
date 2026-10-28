"""The app's ProfileGate and Profiles wired to an app built with __new__, as build() wires them: the callbacks read
the app when they run, so a test can swap one after; the DB, the screens and the nav are the app's at construction."""
from app.ui.profiles import ProfileGate, Profiles


def make_gate(app, **deps) -> ProfileGate:
    defaults = {"user_id": lambda: app._current_user_id, "activate": lambda uid: app._activate_user(uid),
                "refresh_profiles": lambda: app._profiles.refresh(),
                "scan_for_new_profile": lambda: app._headset.scan_for_new_profile(),
                "offer_power_exemption": lambda: app._power.offer_once()}
    return ProfileGate(app._db, getattr(app, "_bottom_nav", None), getattr(app, "_sm", None), **{**defaults, **deps})


def make_profiles(app, **deps) -> Profiles:
    defaults = {"user_id": lambda: app._current_user_id, "activate": lambda uid: app._activate_user(uid),
                "deactivate": lambda: app._deactivate_user(), "on_deleted": lambda uid: app._on_profile_deleted(uid),
                "session_live": lambda: app._session_pipeline_live(),
                "discard_running_session": lambda: app._discard_running_session(),
                "refused_while_session_runs": lambda doing: app._refused_while_session_runs(doing),
                "save_settings": lambda: app._save_user_settings(),
                "running_session_id": lambda: app._running_session_id()}
    return Profiles(app._db, getattr(app, "_settings_screen", None), getattr(app, "_gate", None),
                    **{**defaults, **deps})
