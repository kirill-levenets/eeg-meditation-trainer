"""A str crosses pyjnius as java.lang.String: a bare str made putExtra store a char[], so the save dialog's name came up blank."""

import ast
import pathlib
import sys
import types

import pytest

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
_ACTIVITY_CLASS = "org.kivy.android.PythonActivity"


def _android_reaches(source: str) -> list[tuple[int, str]]:
    """Each place `source` reaches Android itself: the Activity's class, the API-level probe or Kivy's platform name."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and node.value in (_ACTIVITY_CLASS, "getandroidapilevel"):
            found.append((node.lineno, repr(node.value)))
        elif isinstance(node, ast.Attribute) and node.attr == "getandroidapilevel":
            found.append((node.lineno, "getandroidapilevel"))
        elif isinstance(node, ast.Compare) and any(
                isinstance(part, ast.Constant) and part.value == "android" for part in ast.walk(node)):
            found.append((node.lineno, 'a comparison with "android"'))
        elif isinstance(node, ast.ImportFrom) and node.module == "kivy.utils" and any(
                alias.name == "platform" for alias in node.names):
            found.append((node.lineno, "kivy.utils.platform"))
    return found


def test_android_is_reached_only_through_android_jni():
    """One Android check and one Activity lookup, read at call time, so a test fakes them in one place (#108). Kivy's
    platform stays in kivy_providers, which asks it for Linux."""
    files = [path for path in (_APP / "app").rglob("*.py") if path.name != "android_jni.py"] + [_APP / "main.py"]
    assert len(files) > 60  # the scan found the app
    found = [f"{path.relative_to(_APP)}:{line}: {what} -- use android_jni.on_android() / android_jni.activity()"
             for path in files for line, what in _android_reaches(path.read_text())
             if not (path.name == "kivy_providers.py" and what == "kivy.utils.platform")]
    assert not found, "\n".join(found)


@pytest.mark.parametrize("source", [
    'activity = autoclass("org.kivy.android.PythonActivity").mActivity',
    'on_android = hasattr(sys, "getandroidapilevel")',
    "level = sys.getandroidapilevel()",
    'from kivy.utils import platform as kplat\nif kplat == "android": pass',
    'if "android" == platform: pass',
    'if plat in ("android", "ios"): pass',
    'if platform != "android": pass',
])
def test_the_guard_finds_each_way_of_reaching_android(source):
    assert _android_reaches(source)


@pytest.mark.parametrize("source", [
    '"""Looks the PythonActivity up through android_jni."""',
    'windows = sys.platform == "win32"',
    'name = "android_share" if shared else ""',
    'if module == "android_share": pass',
])
def test_the_guard_passes_what_doesnt_reach_android(source):
    assert not _android_reaches(source)
