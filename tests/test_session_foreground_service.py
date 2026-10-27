"""The session's foreground service runs in the app's own process: a foreground service raises only the process hosting
it, and a p4a Python service would get a process of its own."""
import configparser
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

from app import android_jni
from app.session.manager import SessionState
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
    monkeypatch.setattr(android_jni, "on_android", lambda: True)
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._start_session_keep_alive_service()
    app._stop_session_keep_alive_service()
    assert service.start.call_args.args[0] is activity
    service.stop.assert_called_once_with(activity)


def test_the_service_doesnt_stop_when_the_app_is_swiped_away():
    # Swiped away mid-session, the app saves in on_stop; the service must keep the process alive until then, and the
    # session's ending stops it. In the app's process it can't outlive the app.
    java = (ROOT / "android_src" / "org" / "eeg" / "eegmeditation" / "SessionForegroundService.java").read_text()
    assert "onTaskRemoved" not in java


def test_closing_the_app_stops_the_service_with_or_without_a_session(monkeypatch):
    # A start still waiting for the headset is no running session, so _stop_and_save never runs for it.
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._restoring = False
    app._flush_on_leave = MagicMock()
    app._session_manager = MagicMock(state=SessionState.IDLE)
    app._stop_and_save = MagicMock()
    app._audio = MagicMock()
    app._db = MagicMock()
    stopped = []
    monkeypatch.setattr(app, "_stop_session_keep_alive_service", lambda: stopped.append(True))
    app.on_stop()
    app._stop_and_save.assert_not_called()
    assert stopped == [True]
