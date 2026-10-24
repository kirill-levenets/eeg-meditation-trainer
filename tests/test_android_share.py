"""copy_to_documents on Android reports the file MediaStore stored: a name that clashes with a file already there is
stored as "name (1)", and the export's message names that file."""
import sys
import types

import pytest

from app.storage import android_share


class _Values(dict):
    def put(self, key, value):
        self[key] = value


class _Stream:
    def __init__(self):
        self.data = b""

    def write(self, chunk):
        self.data += bytes(chunk)

    def flush(self):
        pass

    def close(self):
        pass


class _Cursor:
    def __init__(self, name):
        self.name, self.closed = name, False

    def moveToFirst(self):
        return self.name is not None

    def getString(self, _column):
        return self.name

    def close(self):
        self.closed = True


class _Resolver:
    def __init__(self, stored, lookup_fails=False):
        self.stored, self.lookup_fails, self.stream, self.cursor = stored, lookup_fails, _Stream(), None

    def insert(self, _collection, values):
        self.values = values
        return "content://media/external/file/7"

    def openOutputStream(self, _uri):
        return self.stream

    def query(self, _uri, projection, *_rest):
        if self.lookup_fails:
            raise RuntimeError("JVM exception")
        assert projection == ["_display_name"]
        self.cursor = _Cursor(self.stored)
        return self.cursor


@pytest.fixture
def android(monkeypatch):
    """Installs a fake pyjnius whose content resolver is the one the test hands it."""
    def install(resolver):
        classes = {
            "org.kivy.android.PythonActivity": types.SimpleNamespace(
                mActivity=types.SimpleNamespace(getContentResolver=lambda: resolver)),
            "android.content.ContentValues": _Values,
            "android.provider.MediaStore$Files": types.SimpleNamespace(getContentUri=lambda _volume: "content://x"),
            "android.os.Environment": types.SimpleNamespace(DIRECTORY_DOCUMENTS="Documents"),
            "android.os.Build$VERSION": types.SimpleNamespace(SDK_INT=33),
        }
        jnius = types.ModuleType("jnius")
        jnius.autoclass = classes.__getitem__
        monkeypatch.setitem(sys.modules, "jnius", jnius)
        monkeypatch.setattr(android_share, "_IS_ANDROID", True)
    return install


def test_a_name_mediastore_changed_is_the_one_reported(android, tmp_path):
    private = tmp_path / "formulas_user_4.txt"
    private.write_text("alpha1\n")
    resolver = _Resolver(stored="formulas_user_4 (1).txt")
    android(resolver)
    assert android_share.copy_to_documents(str(private)) == "Documents/EEGMeditation/formulas_user_4 (1).txt"
    assert resolver.stream.data == b"alpha1\n" and resolver.cursor.closed


def test_a_failed_name_lookup_reports_the_name_asked_for_not_a_failure(android, tmp_path):
    private = tmp_path / "session_3.csv"
    private.write_text("t,v\n")
    android(_Resolver(stored=None, lookup_fails=True))
    assert android_share.copy_to_documents(str(private)) == "Documents/EEGMeditation/session_3.csv"
