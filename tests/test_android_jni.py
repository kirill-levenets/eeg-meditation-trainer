"""A str crosses pyjnius as java.lang.String: a bare str made putExtra store a char[], so the save dialog's name came up blank."""

import pathlib
import re
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
    EXTRA_MIME_TYPES = "android.intent.extra.MIME_TYPES"
    last = None

    def __init__(self, action):
        self.action = action
        self.type = None
        self.extras = {}
        _Intent.last = self

    def addCategory(self, _c):
        pass

    def setType(self, t):
        self.type = t

    def putExtra(self, key, value):
        self.extras[key] = value

    def putExtras(self, bundle):
        self.extras.update(bundle.values)


class _Bundle:
    def __init__(self):
        self.values = {}

    def putStringArray(self, key, value):
        self.values[key] = value


def _install_fake_android(monkeypatch):
    activity = types.SimpleNamespace(startActivityForResult=lambda intent, code: None)
    classes = {
        "java.lang.String": _JavaString,
        "android.content.Intent": _Intent,
        "android.os.Bundle": _Bundle,
        "org.kivy.android.PythonActivity": types.SimpleNamespace(mActivity=activity),
    }
    monkeypatch.setitem(sys.modules, "jnius", types.SimpleNamespace(autoclass=classes.__getitem__))
    runnable = types.ModuleType("android.runnable")
    runnable.run_on_ui_thread = lambda fn: fn
    monkeypatch.setitem(sys.modules, "android", types.ModuleType("android"))
    monkeypatch.setitem(sys.modules, "android.runnable", runnable)


def test_save_dialog_title_is_a_java_string(monkeypatch):
    _install_fake_android(monkeypatch)
    android_saf._launch(android_saf._REQ_CREATE, ("application/octet-stream",), "eeg_backup_carl_2026-09-29_17-49.db")
    title = _Intent.last.extras[_Intent.EXTRA_TITLE]
    assert isinstance(title, _JavaString)
    assert title.text == "eeg_backup_carl_2026-09-29_17-49.db"


def test_open_dialog_sets_no_title(monkeypatch):
    _install_fake_android(monkeypatch)
    android_saf._launch(android_saf._REQ_OPEN, ("*/*",), None)
    assert _Intent.EXTRA_TITLE not in _Intent.last.extras


def test_an_open_dialog_for_one_type_lists_that_type(monkeypatch):
    _install_fake_android(monkeypatch)
    android_saf._launch(android_saf._REQ_OPEN, ("audio/*",), None)
    assert _Intent.last.type == "audio/*" and _Intent.EXTRA_MIME_TYPES not in _Intent.last.extras


def test_an_open_dialog_for_several_types_lists_them_all(monkeypatch):
    _install_fake_android(monkeypatch)
    android_saf._launch(android_saf._REQ_OPEN, ("audio/*", "application/ogg"), None)
    assert _Intent.last.type == "*/*"
    assert _Intent.last.extras[_Intent.EXTRA_MIME_TYPES] == ["audio/*", "application/ogg"]


_APP = pathlib.Path(__file__).resolve().parent.parent
_INLINE_ANDROID = [
    (re.compile(r"PythonActivity"), "the app's Activity: android_jni.activity()"),
    (re.compile(r"getandroidapilevel"), "the Android check: android_jni.on_android()"),
    (re.compile(r"""platform\s*[!=]=\s*["']android["']|["']android["']\s*[!=]=\s*\w*platform"""),
     "the Android check: android_jni.on_android()"),
]


def test_android_is_reached_only_through_android_jni():
    """One Android check and one Activity lookup, read at call time, so a test fakes Android in one place (#108)."""
    found = []
    for path in [*(_APP / "app").rglob("*.py"), _APP / "main.py"]:
        if path.name == "android_jni.py":
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            found += [f"{path.relative_to(_APP)}:{number}: use {use}" for pattern, use in _INLINE_ANDROID
                      if pattern.search(line)]
    assert not found, "\n".join(found)
