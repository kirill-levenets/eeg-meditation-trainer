"""copy_to_documents on Android reports the file MediaStore stored: a name that clashes with a file already there is
stored as "name (1)", and the export's message names that file."""
import sys
import types

import pytest

from app import android_jni
from app.storage import android_saf, android_share


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


class _Uri:
    def __init__(self, text):
        self.text = text

    def toString(self):
        return self.text


class _Cursor:
    def __init__(self, columns):
        self.columns, self.closed = columns, False

    def getColumnIndex(self, column):
        return list(self.columns).index(column) if column in self.columns else -1

    def moveToFirst(self):
        return True

    def getString(self, index):
        return list(self.columns.values())[index]

    def close(self):
        self.closed = True


class _Resolver:
    def __init__(self, stored=None):
        self.stream, self.stored, self.cursor = _Stream(), stored or {}, None

    def insert(self, _collection, values):
        self.values = values
        return _Uri("content://media/external/file/7")

    def openOutputStream(self, _uri):
        return self.stream

    def query(self, uri, *_rest):
        self.cursor = _Cursor({"_id": 7, "_display_name": self.stored[uri]})
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
            "android.net.Uri": types.SimpleNamespace(parse=lambda text: text),
            "android.provider.OpenableColumns": types.SimpleNamespace(DISPLAY_NAME="_display_name"),
        }
        jnius = types.ModuleType("jnius")
        jnius.autoclass = classes.__getitem__
        monkeypatch.setitem(sys.modules, "jnius", jnius)
        monkeypatch.setattr(android_jni, "on_android", lambda: True)
    return install


def test_a_name_mediastore_changed_is_the_one_reported(android, tmp_path, monkeypatch):
    private = tmp_path / "formulas_user_4.txt"
    private.write_text("alpha1\n")
    resolver = _Resolver()
    android(resolver)
    stored = {"content://media/external/file/7": "formulas_user_4 (1).txt"}
    monkeypatch.setattr(android_saf, "query_display_name", stored.get)  # the one display-name reader
    assert android_share.copy_to_documents(str(private)) == "Documents/EEGMeditation/formulas_user_4 (1).txt"
    assert resolver.stream.data == b"alpha1\n"


def test_the_shared_display_name_reader_reads_mediastores_row(android, tmp_path):
    private = tmp_path / "formulas_user_4.txt"
    private.write_text("alpha1\n")
    resolver = _Resolver(stored={"content://media/external/file/7": "formulas_user_4 (2).txt"})
    android(resolver)
    assert android_share.copy_to_documents(str(private)) == "Documents/EEGMeditation/formulas_user_4 (2).txt"
    assert resolver.cursor.closed


def test_a_failed_name_lookup_reports_the_name_asked_for_not_a_failure(android, tmp_path, monkeypatch):
    private = tmp_path / "session_3.csv"
    private.write_text("t,v\n")
    android(_Resolver())

    def jvm_fails(_uri):
        raise RuntimeError("JVM exception")
    monkeypatch.setattr(android_saf, "query_display_name", jvm_fails)
    assert android_share.copy_to_documents(str(private)) == "Documents/EEGMeditation/session_3.csv"
