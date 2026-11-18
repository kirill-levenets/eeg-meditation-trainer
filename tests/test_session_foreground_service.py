"""The session's foreground service runs in the app's own process: a foreground service raises only the process hosting
it, and a p4a Python service would get a process of its own."""
import configparser
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import android_jni
from app.config import APP
from app.keep_awake import KeepAwake
from app.storage.database import DatabaseManager

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
    keep_awake = KeepAwake()
    keep_awake._start_service()  # the wake lock's half has its own test (test_android_paths)
    keep_awake.stop_service()
    assert service.start.call_args.args[0] is activity
    service.stop.assert_called_once_with(activity)


def test_the_service_doesnt_stop_when_the_app_is_swiped_away():
    # Swiped away mid-session, the app saves in on_stop; the service must keep the process alive until then, and the
    # session's ending stops it. In the app's process it can't outlive the app.
    java = (ROOT / "android_src" / "org" / "eeg" / "eegmeditation" / "SessionForegroundService.java").read_text()
    assert "onTaskRemoved" not in java


@pytest.mark.parametrize("in_session", [False, True])
def test_closing_the_app_stops_the_service_with_or_without_a_session(build_app, monkeypatch, in_session):
    # A start still waiting for the headset is no running session, so _stop_and_save never runs for it.
    app = build_app()
    stopped, released = [], []
    release = app._session.keep_awake.release
    monkeypatch.setattr(app._session.keep_awake, "stop_service", lambda: stopped.append(True))
    monkeypatch.setattr(app._session.keep_awake, "release", lambda: (released.append(True), release()))
    if in_session:
        app._on_start()
    app.on_stop()
    # The close releases what a session held, its wake lock too: its ending's teardown can't run while the app closes.
    assert (stopped, released) == ([True], [True])
    reopened = DatabaseManager(db_path=APP.DB_PATH)  # the app closed its own
    try:
        assert reopened.count_sessions(app._current_user_id) == int(in_session)  # a running session is saved on the way
    finally:
        reopened.close()
