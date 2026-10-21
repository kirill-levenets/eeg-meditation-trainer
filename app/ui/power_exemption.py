"""What may close a locked session: Android's battery optimisation and the maker's power manager, which has no API."""
import sys
from collections.abc import Callable

from app.android_jni import (
    component_intent,
    ignores_battery_optimisation,
    manufacturer,
    open_first,
    settings_intent,
)
from app.logger import logger
from app.ui.theme import C, StyledButton, cancel_button, make_message_popup

# dontkillmyapp.com scores these makers 3 of 5 or worse: their power managers close foreground services too.
AGGRESSIVE_MAKERS = frozenset({
    "huawei", "honor", "xiaomi", "redmi", "poco", "oneplus", "samsung", "meizu", "asus", "oppo", "realme", "vivo",
    "wiko", "lenovo", "motorola", "blackview", "tecno",
})
# Huawei's App launch, newest EMUI first; EMUI 12 refuses both to other apps, so its Battery screen follows them.
_APP_LAUNCH_SCREENS = (
    ("com.huawei.systemmanager", "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity"),
    ("com.huawei.systemmanager", "com.huawei.systemmanager.appcontrol.activity.StartupAppControlActivity"),
)
SHOWN_KEY = "power_alert_shown"  # app-wide: it is the phone's setting, whichever profile is using it


def _on_android() -> bool:
    return hasattr(sys, "getandroidapilevel")


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
        lines.append("App launch: in Battery › App launch, set EEG Meditation to Manage manually, with all three "
                     "switches on.")
    elif screen:
        lines.append("App info: allow EEG Meditation to run in the background, in its battery settings.")
    return lines


class PowerExemption:
    """Settings › Device's locked-session row and the first-start alert: they explain; the user decides."""

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
            return ignores_battery_optimisation(), manufacturer()
        except Exception:
            logger.exception("Couldn't read the battery optimisation state")
            return None

    def refresh(self) -> None:
        """Settings › Device's row, at every start and resume: the user may have changed it in between."""
        state = self._state()
        if state is None:
            return
        exempt, maker = state
        lines = advice(exempt, maker)
        # "Android's": EMUI answers exempt while dumpsys deviceidle lists no user app.
        status = ("Android's battery optimisation is off for this app." if exempt else
                  "Android's battery optimisation is on: with the screen locked, the phone may close the app and end a "
                  "session.")
        if lines and exempt:
            status += " The phone's own power manager may still close it."
        self._section.show_power_state(status, battery=not exempt, maker=maker_screen(maker))

    def offer_once(self) -> None:
        """Once, at the first start with something left to allow; the same buttons stay in Settings › Device."""
        if self._db.get_setting(SHOWN_KEY):
            return
        state = self._state()
        if state is None:
            return
        exempt, maker = state
        lines = advice(exempt, maker)
        if not lines:
            return
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
        self._db.set_setting(SHOWN_KEY, "1")  # after it opened: an alert that failed to build comes again next start
        logger.info(f"Locked-session alert shown (exempt={exempt}, maker={maker})")

    def on_battery_settings(self) -> None:
        """Android's own dialog to leave the app out of battery optimisation, or its list where there is no dialog."""
        logger.info("Locked-session settings: battery optimisation")
        self._open([("android.settings.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS", True),
                    ("android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS", False)])

    def on_maker_settings(self) -> None:
        """Huawei's App launch where the phone lets another app open it, else its Battery screen; App info elsewhere."""
        logger.info("Locked-session settings: the maker's power screen")
        if not _on_android():
            return
        try:
            intents = []
            if maker_screen(manufacturer()) == "App launch":
                intents = [component_intent(package, cls) for package, cls in _APP_LAUNCH_SCREENS]
                intents.append(settings_intent("android.intent.action.POWER_USAGE_SUMMARY", package=False))
            intents.append(settings_intent("android.settings.APPLICATION_DETAILS_SETTINGS"))
            open_first(intents, self._opened)
        except Exception:
            logger.exception("Locked-session settings: couldn't build the maker's screens")
            self._opened(False)

    def _open(self, actions: list[tuple[str, bool]]) -> None:
        if not _on_android():
            return
        try:
            open_first([settings_intent(action, package) for action, package in actions], self._opened)
        except Exception:
            logger.exception("Locked-session settings: couldn't build the battery screens")
            self._opened(False)

    def _opened(self, ok: bool) -> None:
        if not ok:
            logger.warning("Locked-session settings: no screen could be opened")
            self._main(lambda: self._toast("Couldn't open the phone's settings"))
