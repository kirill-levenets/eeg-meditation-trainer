"""The Android-only branches the desktop never runs, reached through android_jni with a fake jnius: the session's wake
lock, the native toast, the Bluetooth permissions and thread priority, the crash report's platform and the Bluetooth
backend (#108)."""
import sys
import types
from unittest.mock import MagicMock

import pytest

from app import android_jni, crash_handler
from app.eeg.neurosky_stream import NeuroSkyStream
from app.ui.app_manager import EEGMeditationApp


def _fake_jnius(monkeypatch, classes):
    jnius = types.ModuleType("jnius")
    jnius.autoclass = classes.__getitem__
    monkeypatch.setitem(sys.modules, "jnius", jnius)


def _fake_run_on_ui_thread(monkeypatch):
    android = types.ModuleType("android")
    runnable = types.ModuleType("android.runnable")
    runnable.run_on_ui_thread = lambda fn: fn
    android.runnable = runnable
    monkeypatch.setitem(sys.modules, "android", android)
    monkeypatch.setitem(sys.modules, "android.runnable", runnable)


def _app():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._wake_lock = None
    return app


def _off_android(monkeypatch):
    monkeypatch.setattr(android_jni, "on_android", lambda: False)
    monkeypatch.setattr(android_jni, "activity", lambda: pytest.fail("looked up the Activity off Android"))


def test_the_wake_lock_is_taken_and_given_back_through_the_activity(monkeypatch):
    monkeypatch.setattr(android_jni, "on_android", lambda: True)
    _fake_run_on_ui_thread(monkeypatch)
    window, lock, power = MagicMock(), MagicMock(), MagicMock()
    power.newWakeLock.return_value = lock
    activity = types.SimpleNamespace(getWindow=lambda: window,
                                     getSystemService=lambda name: power if name == "power" else None)
    _fake_jnius(monkeypatch, {
        "org.kivy.android.PythonActivity": types.SimpleNamespace(mActivity=activity),
        "android.view.WindowManager$LayoutParams": types.SimpleNamespace(FLAG_KEEP_SCREEN_ON=128),
        "android.content.Context": types.SimpleNamespace(POWER_SERVICE="power"),
        "android.os.PowerManager": types.SimpleNamespace(PARTIAL_WAKE_LOCK=1),
    })
    app = _app()
    app._acquire_wake_lock()
    window.addFlags.assert_called_once_with(128)
    power.newWakeLock.assert_called_once_with(1, "eegmeditation:session")
    lock.acquire.assert_called_once_with()
    app._release_wake_lock()
    lock.release.assert_called_once_with()
    window.clearFlags.assert_called_once_with(128)
    assert app._wake_lock is None


def test_off_android_the_wake_lock_does_nothing(monkeypatch):
    _off_android(monkeypatch)
    app = _app()
    app._acquire_wake_lock()
    app._release_wake_lock()
    assert app._wake_lock is None


def test_the_native_toast_gets_the_activity_and_a_java_string(monkeypatch):
    monkeypatch.setattr(android_jni, "on_android", lambda: True)
    _fake_run_on_ui_thread(monkeypatch)
    shown = []

    class _Toast:
        LENGTH_SHORT = 0

        @staticmethod
        def makeText(activity, text, length):
            shown.append((activity, text, length))
            return types.SimpleNamespace(show=lambda: shown.append("show"))

    activity = object()
    _fake_jnius(monkeypatch, {
        "org.kivy.android.PythonActivity": types.SimpleNamespace(mActivity=activity),
        "android.widget.Toast": _Toast,
        "java.lang.String": lambda text: ("JString", text),
    })
    _app()._android_toast("Saved")
    assert shown == [(activity, ("JString", "Saved"), 0), "show"]


def test_off_android_the_native_toast_is_a_logged_no_op(monkeypatch):
    _off_android(monkeypatch)
    _app()._android_toast("Saved")


def test_bluetooth_permissions_are_asked_through_the_activity(monkeypatch):
    monkeypatch.setattr("app.eeg.neurosky_stream.time.sleep", lambda _s: None)
    asked = []
    activity = types.SimpleNamespace(checkSelfPermission=lambda perm: -1,
                                     requestPermissions=lambda perms, code: asked.append((list(perms), code)))
    _fake_jnius(monkeypatch, {
        "org.kivy.android.PythonActivity": types.SimpleNamespace(mActivity=activity),
        "android.content.pm.PackageManager": types.SimpleNamespace(PERMISSION_GRANTED=0),
        "android.os.Build$VERSION": types.SimpleNamespace(SDK_INT=33),
    })
    NeuroSkyStream._request_bt_permissions()
    [(perms, code)] = asked
    assert code == 1 and "android.permission.BLUETOOTH_CONNECT" in perms and len(perms) == 5


def test_the_reader_thread_is_raised_only_on_android(monkeypatch):
    calls = []
    _fake_jnius(monkeypatch, {"android.os.Process": types.SimpleNamespace(setThreadPriority=calls.append)})
    monkeypatch.setattr(android_jni, "on_android", lambda: False)
    NeuroSkyStream._boost_thread_priority()
    assert calls == []
    monkeypatch.setattr(android_jni, "on_android", lambda: True)
    NeuroSkyStream._boost_thread_priority()
    assert calls == [-8]


def test_the_crash_report_names_android_when_android_jni_says_so(monkeypatch):
    monkeypatch.setattr(android_jni, "on_android", lambda: True)
    assert crash_handler._platform_string().startswith("Android (")
    monkeypatch.setattr(android_jni, "on_android", lambda: False)
    assert not crash_handler._platform_string().startswith("Android (")


def test_the_scan_and_the_connect_take_the_android_backend(monkeypatch):
    monkeypatch.setattr(android_jni, "on_android", lambda: True)
    monkeypatch.setattr(NeuroSkyStream, "_scan_paired_android",
                        staticmethod(lambda: [{"name": "MindWave", "address": "AA"}]))
    assert NeuroSkyStream.scan_paired_devices() == [{"name": "MindWave", "address": "AA"}]
    stream = NeuroSkyStream.__new__(NeuroSkyStream)
    stream._device_address = "AA:BB"
    picked = []
    stream._connect_android = lambda: picked.append("android")
    stream._connect_desktop = lambda: picked.append("desktop")
    stream._connect_windows = lambda: picked.append("windows")
    stream._connect_bluetooth()
    assert picked == ["android"]
