"""A str crosses pyjnius as java.lang.String: a bare str made putExtra store a char[], so the save dialog's name came up blank."""

import sys
import types

from app.storage import android_saf


class _JavaString:
    def __init__(self, text):
        self.text = text


class _Intent:
    ACTION_CREATE_DOCUMENT = "create"
    ACTION_OPEN_DOCUMENT = "open"
    CATEGORY_OPENABLE = "openable"
    EXTRA_TITLE = "android.intent.extra.TITLE"
    last = None

    def __init__(self, action):
        self.action = action
        self.extras = {}
        _Intent.last = self

    def addCategory(self, _c):
        pass

    def setType(self, _t):
        pass

    def putExtra(self, key, value):
        self.extras[key] = value


def _install_fake_android(monkeypatch):
    activity = types.SimpleNamespace(startActivityForResult=lambda intent, code: None)
    classes = {
        "java.lang.String": _JavaString,
        "android.content.Intent": _Intent,
        "org.kivy.android.PythonActivity": types.SimpleNamespace(mActivity=activity),
    }
    monkeypatch.setitem(sys.modules, "jnius", types.SimpleNamespace(autoclass=classes.__getitem__))
    runnable = types.ModuleType("android.runnable")
    runnable.run_on_ui_thread = lambda fn: fn
    monkeypatch.setitem(sys.modules, "android", types.ModuleType("android"))
    monkeypatch.setitem(sys.modules, "android.runnable", runnable)


def test_save_dialog_title_is_a_java_string(monkeypatch):
    _install_fake_android(monkeypatch)
    android_saf._launch(android_saf._REQ_CREATE, "eeg_backup_carl_2026-09-29_17-49.db")
    title = _Intent.last.extras[_Intent.EXTRA_TITLE]
    assert isinstance(title, _JavaString)
    assert title.text == "eeg_backup_carl_2026-09-29_17-49.db"


def test_open_dialog_sets_no_title(monkeypatch):
    _install_fake_android(monkeypatch)
    android_saf._launch(android_saf._REQ_OPEN, None)
    assert _Intent.EXTRA_TITLE not in _Intent.last.extras
