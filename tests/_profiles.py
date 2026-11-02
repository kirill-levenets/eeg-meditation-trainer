"""The app's ProfileGate and Profiles wired to an app built with __new__, as build() wires them: their context reads the
app when used (tests/_context.py); the nav and the Settings screen are the app's at construction."""
from app.ui.profiles import ProfileGate, Profiles
from tests._context import make_context


def make_gate(app, **ctx_fields) -> ProfileGate:
    return ProfileGate(make_context(app, **ctx_fields), getattr(app, "_bottom_nav", None),
                       refresh_profiles=lambda: app._profiles.refresh(),
                       scan_for_new_profile=lambda: app._headset.scan_for_new_profile(),
                       offer_power_exemption=lambda: app._power.offer_once())


def make_profiles(app, **ctx_fields) -> Profiles:
    return Profiles(make_context(app, **ctx_fields), getattr(app, "_settings_screen", None), getattr(app, "_gate", None),
                    deactivate=lambda: app._deactivate_user(), on_deleted=lambda uid: app._on_profile_deleted(uid))
