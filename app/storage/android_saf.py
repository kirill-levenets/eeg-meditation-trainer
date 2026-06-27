"""Android Storage Access Framework helpers — user-driven save/open dialogs.

Scoped storage (targetSdk 30+) forbids direct writes to shared storage by path,
so the user picks the destination via the system document picker and bytes are
streamed through the returned content:// URI. No storage permission is needed and
the result survives app uninstall. Desktop uses Kivy's own FileChooser instead.

All jnius imports are function-local so this module imports cleanly off-Android.
"""

import sys

from app.logger import logger

_IS_ANDROID = hasattr(sys, "getandroidapilevel")

# Request codes for startActivityForResult (must fit in 16 bits).
_REQ_CREATE = 9011
_REQ_OPEN = 9012

_pending: dict[int, object] = {}  # request_code -> on_result(uri_str | None)
_bound = False


def is_available() -> bool:
    return _IS_ANDROID


def create_document(display_name: str, on_result) -> None:
    """Launch the system 'Save as' dialog. `on_result(uri_str | None)` later."""
    _ensure_bound()
    _pending[_REQ_CREATE] = on_result
    _launch(_REQ_CREATE, display_name)


def open_document(on_result) -> None:
    """Launch the system 'Open' dialog. `on_result(uri_str | None)` later."""
    _ensure_bound()
    _pending[_REQ_OPEN] = on_result
    _launch(_REQ_OPEN, None)


def write_file_to_uri(uri_str: str, src_path: str) -> bool:
    """Stream `src_path` into the content:// URI via ContentResolver."""
    from jnius import autoclass

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    Uri = autoclass("android.net.Uri")
    resolver = PythonActivity.mActivity.getContentResolver()
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

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    Uri = autoclass("android.net.Uri")
    FileOutputStream = autoclass("java.io.FileOutputStream")
    resolver = PythonActivity.mActivity.getContentResolver()
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


def _launch(request_code: int, display_name: str | None) -> None:
    from android.runnable import run_on_ui_thread

    @run_on_ui_thread
    def _run():
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Intent = autoclass("android.content.Intent")
        action = (Intent.ACTION_CREATE_DOCUMENT if request_code == _REQ_CREATE
                  else Intent.ACTION_OPEN_DOCUMENT)
        intent = Intent(action)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType("application/octet-stream" if display_name else "*/*")
        if display_name:
            intent.putExtra(Intent.EXTRA_TITLE, display_name)
        PythonActivity.mActivity.startActivityForResult(intent, request_code)

    _run()
