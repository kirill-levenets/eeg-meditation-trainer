"""Whether the phone lets a locked session run: Android's battery optimisation, which the app can check and ask to be
left out of, and the maker's own power manager, which has no API: the app can only say so and open its screen."""
import sys
from collections.abc import Callable

from app.android_jni import java_string
from app.logger import logger
from app.ui.theme import C, StyledButton, cancel_button, make_message_popup

# Makers whose power managers close background apps, foreground services included (dontkillmyapp.com scores them 3 or
# worse of 5; Pixel, Nokia and HTC score 0).
AGGRESSIVE_MAKERS = frozenset({
    "huawei", "honor", "xiaomi", "redmi", "poco", "oneplus", "samsung", "meizu", "asus", "oppo", "realme", "vivo",
    "wiko", "lenovo", "motorola", "blackview", "tecno",
})
# Huawei's Battery › App launch, newest EMUI first; a screen another app may not open falls back to App info.
_APP_LAUNCH_SCREENS = (
    ("com.huawei.systemmanager", "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity"),
    ("com.huawei.systemmanager", "com.huawei.systemmanager.appcontrol.activity.StartupAppControlActivity"),
)
SHOWN_KEY = "power_alert_shown"  # app-wide: it is the phone's setting, whichever profile is using it


def _on_android() -> bool:
    return hasattr(sys, "getandroidapilevel")


def _activity():
    from jnius import autoclass
    return autoclass("org.kivy.android.PythonActivity").mActivity


def manufacturer() -> str:
    from jnius import autoclass
    return str(autoclass("android.os.Build").MANUFACTURER or "").lower()


def is_exempt() -> bool:
    """True when battery optimisation leaves the app alone (always below Android 6, which has none)."""
    if sys.getandroidapilevel() < 23:
        return True
    from jnius import autoclass, cast
    activity = _activity()
    service = activity.getSystemService(autoclass("android.content.Context").POWER_SERVICE)
    return bool(cast("android.os.PowerManager", service).isIgnoringBatteryOptimizations(activity.getPackageName()))


def _settings_intent(action: str, package: bool = True):
    from jnius import autoclass
    Intent = autoclass("android.content.Intent")
    if not package:
        return Intent(java_string(action))
    uri = autoclass("android.net.Uri").parse(java_string(f"package:{_activity().getPackageName()}"))
    return Intent(java_string(action), uri)


def _component_intent(package: str, cls: str):
    from jnius import autoclass
    intent = autoclass("android.content.Intent")()
    intent.setComponent(autoclass("android.content.ComponentName")(java_string(package), java_string(cls)))
    return intent


def _open_first(intents: list, done: Callable[[bool], None]) -> None:
    """Open the first of `intents` that resolves and may be opened; `done(False)` when none could be."""
    from android.runnable import run_on_ui_thread

    @run_on_ui_thread
    def _run():
        activity = _activity()
        for intent in intents:
            try:
                if intent.resolveActivity(activity.getPackageManager()) is None:
                    continue
                activity.startActivity(intent)
                done(True)
                return
            except Exception as e:  # a screen its app didn't export: try the next
                logger.warning(f"Couldn't open {intent.getComponent() or intent.getAction()}: {e}")
        done(False)

    _run()


def maker_screen(maker: str) -> str | None:
    """The maker's own power screen the app can open, as its button names it; None when the maker leaves apps alone."""
    if maker in ("huawei", "honor"):
        return "App launch"
    return "App info" if maker in AGGRESSIVE_MAKERS else None


def advice(exempt: bool, maker: str) -> list[str]:
    """What the user can do, one line each, for the alert and Settings › Device."""
    lines = []
    if not exempt:
        lines.append("Battery: let the app ignore battery optimisation.")
    screen = maker_screen(maker)
    if screen == "App launch":
        lines.append("App launch: set EEG Meditation to Manage manually, with all three switches on.")
    elif screen:
        lines.append("App info: allow EEG Meditation to run in the background, in its battery settings.")
    return lines


class PowerExemption:
    """Settings › Device's locked-session row and the alert at the first start: it explains and opens the screens, the
    user decides, and nothing changes without them."""

    def __init__(self, db, device_section, *, toast: Callable[[str], None], main: Callable[[Callable], None]) -> None:
        self._db = db
        self._section = device_section
        self._toast = toast
        self._main = main  # runs a callable on Kivy's thread: the screens open on Android's UI thread

    def _state(self) -> tuple[bool, str] | None:
        """(exempt, maker) on Android; None off it or when Android can't be asked."""
        if not _on_android():
            return None
        try:
            return is_exempt(), manufacturer()
        except Exception:
            logger.exception("Couldn't read the battery optimisation state")
            return None

    def refresh(self) -> None:
        """Settings › Device's row, after the start and after every return to the app (the user may have changed it)."""
        state = self._state()
        if state is None:
            return
        exempt, maker = state
        lines = advice(exempt, maker)
        status = ("Battery optimisation is off for this app." if exempt else
                  "Battery optimisation is on: with the screen locked, the phone may close the app and end a session.")
        if lines and exempt:
            status += " The phone's own power manager may still close it."
        self._section.show_power_state(status, battery=not exempt, maker=maker_screen(maker))

    def offer_once(self) -> None:
        """The first start with something left to allow: explain and let the user choose. Shown once; the same buttons
        stay in Settings › Device."""
        if self._db.get_setting(SHOWN_KEY):
            return
        state = self._state()
        if state is None:
            return
        exempt, maker = state
        lines = advice(exempt, maker)
        if not lines:
            return
        self._db.set_setting(SHOWN_KEY, "1")
        logger.info(f"Locked-session alert shown (exempt={exempt}, maker={maker})")
        message = ("To save battery, your phone may close EEG Meditation while the screen is locked, and a session "
                   "then ends early. To let sessions run:\n\n" + "\n".join(f"• {line}" for line in lines)
                   + "\n\nThe same buttons are in Settings › Device.")
        buttons = []
        if not exempt:
            battery = StyledButton(text="Battery", bg_color=C.ACCENT)
            battery.bind(on_release=lambda *_: self.on_battery_settings())
            buttons.append(battery)
        screen = maker_screen(maker)
        if screen:
            maker_btn = StyledButton(text=screen, bg_color=C.ACCENT)
            maker_btn.bind(on_release=lambda *_: self.on_maker_settings())
            buttons.append(maker_btn)
        close = cancel_button("Close")
        buttons.append(close)
        popup = make_message_popup("Locked-screen sessions", message, buttons)
        close.bind(on_release=popup.dismiss)
        popup.open()

    def on_battery_settings(self) -> None:
        """Android's own dialog to leave the app out of battery optimisation, or its list where there is no dialog."""
        logger.info("Locked-session settings: battery optimisation")
        self._open([("android.settings.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS", True),
                    ("android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS", False)])

    def on_maker_settings(self) -> None:
        """Huawei's App launch where the phone lets another app open it, otherwise the app's App info."""
        logger.info("Locked-session settings: the maker's power screen")
        if not _on_android():
            return
        screens = _APP_LAUNCH_SCREENS if maker_screen(manufacturer()) == "App launch" else ()
        intents = [_component_intent(package, cls) for package, cls in screens]
        intents.append(_settings_intent("android.settings.APPLICATION_DETAILS_SETTINGS"))
        _open_first(intents, self._opened)

    def _open(self, actions: list[tuple[str, bool]]) -> None:
        if not _on_android():
            return
        _open_first([_settings_intent(action, package) for action, package in actions], self._opened)

    def _opened(self, ok: bool) -> None:
        if not ok:
            logger.warning("Locked-session settings: no screen could be opened")
            self._main(lambda: self._toast("Couldn't open the phone's settings"))
