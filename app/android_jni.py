"""pyjnius helpers; jnius is imported inside functions so this module imports off-Android."""
import sys
from collections.abc import Callable

from app.logger import logger


def java_string(text: str):
    """A real java.lang.String: pyjnius resolves a Python str to a char[] overload, and never to CharSequence."""
    from jnius import autoclass

    return autoclass("java.lang.String")(text)


def on_android() -> bool:
    """The one Android check: it needs no Kivy, so config.py can ask before Kivy loads; read at call time, so a test
    fakes it here."""
    return hasattr(sys, "getandroidapilevel")


def activity():
    """The app's Activity, the one lookup of it."""
    from jnius import autoclass
    return autoclass("org.kivy.android.PythonActivity").mActivity


def content_resolver():
    return activity().getContentResolver()


def language() -> str:
    """The device's language as an ISO 639 code ("uk", "en", ...)."""
    from jnius import autoclass
    return str(autoclass("java.util.Locale").getDefault().getLanguage() or "")


def manufacturer() -> str:
    from jnius import autoclass
    return str(autoclass("android.os.Build").MANUFACTURER or "").lower()


def ignores_battery_optimisation() -> bool:
    """Android's answer for this app; below Android 6 there is no battery optimisation to be in."""
    if sys.getandroidapilevel() < 23:
        return True
    from jnius import autoclass, cast
    app = activity()
    service = app.getSystemService(autoclass("android.content.Context").POWER_SERVICE)
    return bool(cast("android.os.PowerManager", service).isIgnoringBatteryOptimizations(app.getPackageName()))


def settings_intent(action: str, package: bool = True):
    """An Intent for a Settings screen, about this app when `package`."""
    from jnius import autoclass
    Intent = autoclass("android.content.Intent")
    if not package:
        return Intent(java_string(action))
    uri = autoclass("android.net.Uri").parse(java_string(f"package:{activity().getPackageName()}"))
    return Intent(java_string(action), uri)


def component_intent(package: str, cls: str):
    from jnius import autoclass
    intent = autoclass("android.content.Intent")()
    intent.setComponent(autoclass("android.content.ComponentName")(java_string(package), java_string(cls)))
    return intent


def open_first(intents: list, done: Callable[[bool], None]) -> None:
    """Open the first of `intents` that opens, on Android's UI thread; no resolveActivity, which Android 11 blinds."""
    from android.runnable import run_on_ui_thread

    @run_on_ui_thread
    def _run():
        try:
            app = activity()
        except Exception:
            logger.exception("Couldn't reach the app's activity")
            done(False)
            return
        for intent in intents:
            try:
                app.startActivity(intent)
                done(True)
                return
            except Exception as e:  # not on this phone, or not exported: try the next
                logger.warning(f"Couldn't open {intent.getComponent() or intent.getAction()}: {e}")
        done(False)

    _run()
