"""Global crash handler — installs sys/Kivy/thread exception hooks, pops dialog.

Also exposes `report_soft_error(label, detail)` for handled-but-significant
errors that aren't fatal but that we still want the user to be able to copy
into a bug report. These reuse the same dialog with a non-fatal banner and
without exiting the app on dismiss.
"""

from __future__ import annotations

import datetime as _dt
import platform as _platform
import sys as _sys
import threading as _threading
import time as _time
import traceback as _traceback
from typing import Any

from app.config import APP_VERSION
from app.logger import logger

# Per-label cooldown for soft errors so one flaky subsystem can't spam dialogs.
_SOFT_ERROR_COOLDOWN_S: float = 60.0
_SOFT_ERROR_LAST: dict[str, float] = {}


def _kivy_version() -> str:
    try:
        import kivy  # noqa: PLC0415
        return kivy.__version__
    except Exception:  # noqa: BLE001
        return "unknown"


def _platform_string() -> str:
    try:
        from kivy.utils import platform as kplat  # noqa: PLC0415
        if kplat == "android":
            return f"Android ({_platform.release()})"
    except Exception:  # noqa: BLE001
        pass
    try:
        return _platform.platform()
    except Exception:  # noqa: BLE001
        return _platform.system() or "unknown"


def _device_name(app) -> str:
    """Best-effort device display name from app state."""
    try:
        from app.config import APP  # noqa: PLC0415
        if getattr(APP, "USE_MOCK_DEVICE", False):
            return "Mock EEG"
        real_stream = getattr(app, "_real_stream", None)
        if real_stream is not None:
            name = getattr(real_stream, "_device_name", None)
            if name:
                return str(name)
            return "Real EEG"
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def _session_state(app) -> str:
    """Best-effort session state string from app state."""
    try:
        mgr = getattr(app, "_session_manager", None)
        if mgr is None:
            return "unknown"
        state = getattr(mgr, "state", None)
        if state is None:
            return "unknown"
        # Handle enums cleanly
        name = getattr(state, "name", None)
        if name:
            return str(name)
        return str(state)
    except Exception:  # noqa: BLE001
        return "unknown"


def _format_report(exc_type, exc_value, tb, source: str, app) -> str:
    session_state = _session_state(app)
    device_name = _device_name(app)
    timestamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tb_lines = "".join(_traceback.format_exception(exc_type, exc_value, tb))

    return (
        f"### EEG Meditation Trainer crash report\n\n"
        f"- **App:** {APP_VERSION}\n"
        f"- **Platform:** {_platform_string()}\n"
        f"- **Python:** {_platform.python_version()}\n"
        f"- **Kivy:** {_kivy_version()}\n"
        f"- **Device:** {device_name}\n"
        f"- **Session:** {session_state}\n"
        f"- **Source:** {source}\n"
        f"- **Timestamp:** {timestamp}\n\n"
        f"<details><summary>Traceback</summary>\n\n"
        f"```\n{tb_lines}```\n\n"
        f"</details>\n"
    )


_STATE = {"in_dialog": False, "app": None}


def _schedule_dialog(report: str, fatal: bool = True, title: str = "") -> None:
    """Show the CrashDialog on the Kivy main thread. Overridden in tests."""
    try:
        from kivy.clock import Clock  # noqa: PLC0415

        Clock.schedule_once(
            lambda dt: CrashDialog.show(
                report, _STATE["app"], fatal=fatal, title=title,
            ),
            0,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to schedule crash dialog; falling back to stderr.")
        _sys.stderr.write(report)


def _handle_exception(exc_type, exc_value, tb, source: str, app) -> None:
    if _STATE["in_dialog"]:
        _sys.stderr.write("Re-entrant exception during crash dialog:\n")
        _traceback.print_exception(exc_type, exc_value, tb)
        return
    _STATE["in_dialog"] = True
    try:
        report = _format_report(exc_type, exc_value, tb, source=source, app=app)
        _schedule_dialog(report)
    except Exception:  # noqa: BLE001
        logger.exception("Crash handler itself failed.")
        _traceback.print_exception(exc_type, exc_value, tb)


def _format_soft_report(label: str, detail: str, app) -> str:
    """Same report shape as a crash, minus the traceback section."""
    timestamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = (
        f"### EEG Meditation Trainer diagnostic report\n\n"
        f"- **App:** {APP_VERSION}\n"
        f"- **Platform:** {_platform_string()}\n"
        f"- **Python:** {_platform.python_version()}\n"
        f"- **Kivy:** {_kivy_version()}\n"
        f"- **Device:** {_device_name(app)}\n"
        f"- **Session:** {_session_state(app)}\n"
        f"- **Source:** soft:{label}\n"
        f"- **Timestamp:** {timestamp}\n"
    )
    if detail:
        body += f"\n<details><summary>Detail</summary>\n\n```\n{detail}\n```\n\n</details>\n"
    return body


def report_soft_error(
    label: str, detail: str = "", *, app=None, force: bool = False,
) -> bool:
    """Surface a non-fatal diagnostic report to the user.

    `label` is a stable category name (e.g. "bt_connect_failed"). The same
    label fires at most once per `_SOFT_ERROR_COOLDOWN_S` so a flaky subsystem
    can't spam dialogs. Returns True if the dialog was scheduled, False if
    suppressed by cooldown or re-entrance.

    Pass `force=True` to bypass the cooldown (use only for user-initiated
    actions like the "Copy diagnostics" button).
    """
    if _STATE["in_dialog"]:
        return False
    now = _time.monotonic()
    if not force:
        last = _SOFT_ERROR_LAST.get(label, 0.0)
        if now - last < _SOFT_ERROR_COOLDOWN_S:
            logger.debug(f"soft-error '{label}' suppressed (cooldown)")
            return False
    _SOFT_ERROR_LAST[label] = now

    target_app = app if app is not None else _STATE["app"]
    try:
        report = _format_soft_report(label, detail, target_app)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to build soft-error report")
        return False

    _STATE["in_dialog"] = True
    try:
        _schedule_dialog(report, fatal=False)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to schedule soft-error dialog")
        _STATE["in_dialog"] = False
        return False
    return True


class CrashDialog:
    """Modal popup that auto-copies the crash report to the clipboard.

    `fatal=True` (default): banner says the app hit an unexpected error and
    Dismiss exits the app — used for true crashes from sys/thread/Kivy hooks.
    `fatal=False`: used for soft errors and on-demand diagnostics; banner is
    informational and Dismiss simply closes the popup without stopping the app.
    """

    _popup: Any = None

    @classmethod
    def show(cls, report: str, app, fatal: bool = True, title: str = "") -> None:
        from kivy.core.clipboard import Clipboard  # noqa: PLC0415
        from kivy.metrics import dp  # noqa: PLC0415
        from kivy.uix.boxlayout import BoxLayout  # noqa: PLC0415
        from kivy.uix.button import Button  # noqa: PLC0415
        from kivy.uix.label import Label  # noqa: PLC0415
        from kivy.uix.popup import Popup  # noqa: PLC0415
        from kivy.uix.scrollview import ScrollView  # noqa: PLC0415
        from kivy.uix.textinput import TextInput  # noqa: PLC0415

        try:
            Clipboard.copy(report)
        except Exception:  # noqa: BLE001
            logger.exception("Clipboard copy failed during crash dialog.")

        root = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(12))
        if fatal:
            banner_text = (
                "The app hit an unexpected error. The report below has been "
                "copied to your clipboard. Paste it into a new GitHub issue at "
                "github.com/kirill-levenets/eeg-meditation-trainer/issues so we "
                "can fix it."
            )
        else:
            banner_text = (
                "Diagnostic report — already copied to your clipboard. Paste it "
                "into Telegram / email / GitHub if you'd like help with this issue. "
                "You can keep using the app."
            )
        banner = Label(
            text=banner_text,
            size_hint_y=None,
            height=dp(72),
            halign="left",
            valign="top",
        )
        banner.bind(size=banner.setter("text_size"))
        root.add_widget(banner)

        scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        text = TextInput(
            text=report,
            readonly=True,
            font_name="Roboto",
            size_hint_y=None,
            # Height driven by content so the whole report renders;
            # ScrollView handles scrolling for overflow.
        )
        text.bind(minimum_height=text.setter("height"))
        scroll.add_widget(text)
        text.cursor = (0, 0)  # show the top of the report, not the end
        root.add_widget(scroll)

        btn_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(48),
            spacing=dp(8),
        )
        btn_copy = Button(text="Copied \u2713")
        btn_dismiss = Button(text="Dismiss & Exit" if fatal else "Close")

        def _on_copy(_btn):
            try:
                Clipboard.copy(report)
                btn_copy.text = "Copied \u2713"
            except Exception:  # noqa: BLE001
                btn_copy.text = "Copy failed"

        def _on_dismiss(_btn):
            try:
                if cls._popup is not None:
                    cls._popup.dismiss()
            except Exception:  # noqa: BLE001
                pass
            _STATE["in_dialog"] = False
            if not fatal:
                return
            try:
                if app is not None:
                    app.stop()
            except Exception:  # noqa: BLE001
                logger.exception("app.stop() failed during crash dismiss.")

        btn_copy.bind(on_release=_on_copy)
        btn_dismiss.bind(on_release=_on_dismiss)
        btn_row.add_widget(btn_copy)
        btn_row.add_widget(btn_dismiss)
        root.add_widget(btn_row)

        if title:
            popup_title = title
        elif fatal:
            popup_title = "Unexpected error"
        else:
            popup_title = "Diagnostic report"

        cls._popup = Popup(
            title=popup_title,
            content=root,
            size_hint=(0.92, 0.92),
            auto_dismiss=False,
        )
        if cls._popup is not None:
            cls._popup.open()


def _sys_hook(exc_type, exc_value, tb) -> None:
    _handle_exception(exc_type, exc_value, tb, source="main", app=_STATE["app"])


def _thread_hook(args) -> None:
    _handle_exception(
        args.exc_type, args.exc_value, args.exc_traceback,
        source=f"thread:{getattr(args.thread, 'name', 'unknown')}",
        app=_STATE["app"],
    )


_KivyExceptionHandler = None  # type: ignore[assignment]


def install_crash_handler(app) -> None:
    """Install sys, Kivy, and thread exception hooks."""
    _STATE["app"] = app

    _sys.excepthook = _sys_hook
    _threading.excepthook = _thread_hook

    try:
        from kivy.base import ExceptionHandler, ExceptionManager  # noqa: PLC0415

        class _Handler(ExceptionHandler):
            def handle_exception(self, inst):
                import sys as _s  # noqa: PLC0415
                exc_type, exc_value, tb = _s.exc_info()
                _handle_exception(
                    exc_type, exc_value, tb, source="kivy-loop", app=_STATE["app"]
                )
                return ExceptionManager.PASS

        # Make the class type discoverable for tests
        global _KivyExceptionHandler
        _KivyExceptionHandler = _Handler

        ExceptionManager.add_handler(_Handler())
    except Exception:  # noqa: BLE001
        logger.exception("Failed to register Kivy ExceptionManager handler.")
