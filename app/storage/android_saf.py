"""Android Storage Access Framework helpers — user-driven save/open dialogs.

Scoped storage (targetSdk 30+) forbids direct writes to shared storage by path,
so the user picks the destination via the system document picker and bytes are
streamed through the returned content:// URI. No storage permission is needed and
the result survives app uninstall. Desktop uses Kivy's own FileChooser instead.

All jnius imports are function-local so this module imports cleanly off-Android.
"""

import hashlib
import os
import queue
import threading

from app import android_jni
from app.logger import logger
from app.storage.fileops import discard_file

# Request codes for startActivityForResult (must fit in 16 bits).
_REQ_CREATE = 9011
_REQ_OPEN = 9012

_pending: dict[int, object] = {}  # request_code -> on_result(uri_str | None)
_bound = False

_imports: queue.SimpleQueue = queue.SimpleQueue()
_importer: threading.Thread | None = None
_importer_lock = threading.Lock()


def is_available() -> bool:
    return android_jni.on_android()


def create_document(display_name: str, on_result) -> None:
    """Launch the system 'Save as' dialog. `on_result(uri_str | None)` later."""
    _ensure_bound()
    _pending[_REQ_CREATE] = on_result
    _launch(_REQ_CREATE, ("application/octet-stream",), display_name)


def open_document(on_result, mime_types: tuple[str, ...] = ("*/*",)) -> None:
    """Launch the system 'Open' dialog, listing documents of these types. `on_result(uri_str | None)` later."""
    _ensure_bound()
    _pending[_REQ_OPEN] = on_result
    _launch(_REQ_OPEN, mime_types, None)


def write_file_to_uri(uri_str: str, src_path: str) -> bool:
    """Stream `src_path` into the content:// URI via ContentResolver."""
    from jnius import autoclass

    Uri = autoclass("android.net.Uri")
    resolver = android_jni.activity().getContentResolver()
    out = resolver.openOutputStream(Uri.parse(uri_str))
    if out is None:
        logger.error("SAF openOutputStream returned None")
        return False
    try:
        with open(src_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                out.write(chunk)
        out.flush()
    finally:
        out.close()
    return True


def read_uri_to_file(uri_str: str, dst_path: str) -> bool:
    """Stream the content:// URI into `dst_path` via ContentResolver."""
    from jnius import autoclass

    Uri = autoclass("android.net.Uri")
    FileOutputStream = autoclass("java.io.FileOutputStream")
    resolver = android_jni.activity().getContentResolver()
    inp = resolver.openInputStream(Uri.parse(uri_str))
    if inp is None:
        logger.error("SAF openInputStream returned None")
        return False
    try:
        fos = FileOutputStream(dst_path)
        try:
            try:
                # FileUtils.copy avoids Python<->byte[] juggling (API 29+).
                autoclass("android.os.FileUtils").copy(inp, fos)
            except Exception:
                buf = bytearray(8192)
                while True:
                    n = inp.read(buf)
                    if n == -1:
                        break
                    fos.write(buf, 0, n)
            fos.flush()
        finally:
            fos.close()
    finally:
        inp.close()
    return True


def query_display_name(uri_str: str) -> str | None:
    """The document's file name as its provider shows it."""
    from jnius import autoclass

    Uri = autoclass("android.net.Uri")
    OpenableColumns = autoclass("android.provider.OpenableColumns")
    cursor = android_jni.activity().getContentResolver().query(Uri.parse(uri_str), None, None, None, None)
    if cursor is None:
        return None
    try:
        column = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
        return cursor.getString(column) if column >= 0 and cursor.moveToFirst() else None
    finally:
        cursor.close()


def query_extension(uri_str: str) -> str | None:
    """The usual file extension for the document's type, as its provider reports it."""
    from jnius import autoclass

    Uri = autoclass("android.net.Uri")
    MimeTypeMap = autoclass("android.webkit.MimeTypeMap")
    mime = android_jni.activity().getContentResolver().getType(Uri.parse(uri_str))
    return MimeTypeMap.getSingleton().getExtensionFromMimeType(mime) if mime else None


def import_document(uri_str: str, dest_dir: str, fallback_name: str, on_done) -> None:
    """Copy into dest_dir off the main thread; each on_done runs in the order asked, so the last one asked stays."""
    global _importer
    _imports.put((uri_str, dest_dir, fallback_name, on_done))
    with _importer_lock:
        if _importer is None:
            _importer = threading.Thread(target=_run_imports, name="saf-import", daemon=True)
            _importer.start()


def _run_imports() -> None:
    while True:
        uri_str, dest_dir, fallback_name, on_done = _imports.get()
        try:
            on_done(_copy_in(uri_str, dest_dir, fallback_name))
        except Exception:
            logger.exception("A document import's callback failed")


def _copy_in(uri_str: str, dest_dir: str, fallback_name: str) -> str | None:
    """dest_dir/<content hash>/<its name>: one picked twice is stored once, two sharing a name keep their own bytes."""
    part = os.path.join(dest_dir, ".incoming.part")  # one at a time: a copy cut off by a kill is overwritten next time
    try:
        os.makedirs(dest_dir, exist_ok=True)
        if not read_uri_to_file(uri_str, part):
            return None
        with open(part, "rb") as f:
            folder = os.path.join(dest_dir, hashlib.file_digest(f, "sha256").hexdigest()[:12])
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, _document_name(uri_str, fallback_name))
        os.replace(part, path)
        return path
    except Exception:
        logger.exception("Could not copy the picked document")
        return None
    finally:
        discard_file(part)


def _document_name(uri_str: str, fallback_name: str) -> str:
    """Its provider's file name, kept to one path segment, with an extension from its type when it has none."""
    try:
        name = os.path.basename((query_display_name(uri_str) or "").replace("\\", "/")).strip()
    except Exception:
        logger.exception("Could not read the picked document's name")
        name = ""
    if name in ("", ".", ".."):
        name = fallback_name
    if os.path.splitext(name)[1]:
        return name
    try:
        extension = query_extension(uri_str)
    except Exception:
        logger.exception("Could not read the picked document's type")
        extension = None
    return f"{name}.{extension}" if extension else name


def _ensure_bound() -> None:
    global _bound
    if _bound:
        return
    from android import activity
    activity.bind(on_activity_result=_on_activity_result)
    _bound = True


def _on_activity_result(request_code, result_code, intent):
    cb = _pending.pop(request_code, None)
    if cb is None:
        return
    try:
        from jnius import autoclass
        Activity = autoclass("android.app.Activity")
        if result_code != Activity.RESULT_OK or intent is None:
            cb(None)
            return
        uri = intent.getData()
        cb(uri.toString() if uri is not None else None)
    except Exception:
        logger.exception("SAF activity-result handling failed")
        cb(None)


def _launch(request_code: int, mime_types: tuple[str, ...], title: str | None) -> None:
    from android.runnable import run_on_ui_thread

    @run_on_ui_thread
    def _run():
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")
        action = (Intent.ACTION_CREATE_DOCUMENT if request_code == _REQ_CREATE
                  else Intent.ACTION_OPEN_DOCUMENT)
        intent = Intent(action)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType(mime_types[0] if len(mime_types) == 1 else "*/*")
        if len(mime_types) > 1:
            extras = autoclass("android.os.Bundle")()
            extras.putStringArray(Intent.EXTRA_MIME_TYPES, list(mime_types))  # not overloaded, unlike putExtra
            intent.putExtras(extras)
        if title:
            intent.putExtra(Intent.EXTRA_TITLE, android_jni.java_string(title))
        android_jni.activity().startActivityForResult(intent, request_code)

    _run()
