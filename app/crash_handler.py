"""Global crash handler — installs sys/Kivy/thread exception hooks, pops dialog."""

from __future__ import annotations

import datetime as _dt
import platform as _platform
import sys as _sys  # noqa: F401 — used by Tasks 6/7 hooks
import threading as _threading  # noqa: F401 — used by Task 6 thread hook
import traceback as _traceback

from app.config import APP_VERSION


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
