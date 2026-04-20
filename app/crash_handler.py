"""Global crash handler — installs sys/Kivy/thread exception hooks, pops dialog."""

from __future__ import annotations

import datetime as _dt
import platform as _platform
import sys as _sys  # noqa: F401 — used by Tasks 6/7 hooks
import threading as _threading  # noqa: F401 — used by Task 6 thread hook
import traceback as _traceback

from app.config import APP_VERSION
from app.logger import logger  # noqa: F401 — used by Task 6 _handle_exception


def _safe_attr(obj, name: str, default: str = "unknown") -> str:
    try:
        val = getattr(obj, name)
    except Exception:  # noqa: BLE001
        return default
    if val is None:
        return default
    return str(val)


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


def _format_report(exc_type, exc_value, tb, source: str, app) -> str:
    session_mgr = getattr(app, "session_manager", None)
    session_state = _safe_attr(session_mgr, "state", "unknown") if session_mgr else "unknown"
    device_name = _safe_attr(session_mgr, "stream_name", "None") if session_mgr else "None"
    timestamp = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
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
