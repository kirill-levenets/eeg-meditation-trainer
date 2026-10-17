"""The session's foreground service runs in the app's own process (#104): a foreground service raises only the process
hosting it, and a p4a Python service would get a process of its own."""
import configparser
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

from app.ui.app_manager import EEGMeditationApp

ROOT = Path(__file__).resolve().parents[1]
SERVICE = "org.eeg.eegmeditation.SessionForegroundService"


def _spec() -> configparser.SectionProxy:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ROOT / "buildozer.spec")
    return parser["app"]


def test_the_spec_declares_the_java_service_in_the_apps_process():
    app = _spec()
    assert f"--native-service={SERVICE}" in app.get("p4a.extra_args", "")
    assert app.get("android.add_src") == "android_src"
    assert not app.get("services"), "a p4a Python service runs in a process of its own"
    assert (ROOT / "android_src" / "org" / "eeg" / "eegmeditation" / "SessionForegroundService.java").is_file()


def test_on_android_a_session_starts_and_stops_the_service_through_its_static_methods(monkeypatch):
    service = MagicMock()
    activity = object()
    jnius = types.SimpleNamespace(autoclass=lambda name: {
        SERVICE: service, "org.kivy.android.PythonActivity": types.SimpleNamespace(mActivity=activity)}[name])
    monkeypatch.setitem(sys.modules, "jnius", jnius)
    monkeypatch.setattr(sys, "getandroidapilevel", lambda: 29, raising=False)
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._start_session_keep_alive_service()
    app._stop_session_keep_alive_service()
    assert service.start.call_args.args[0] is activity
    service.stop.assert_called_once_with(activity)
