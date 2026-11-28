"""Android shared storage helper — copy files to Documents via MediaStore.

Uses pyjnius to call Android's ContentResolver.insert() API, which is
the only way to write to shared storage (Documents, Downloads, etc.)
on Android 10+ with scoped storage.

On non-Android platforms, falls back to simple file copy.
"""

import os

from app import android_jni
from app.logger import logger
from app.storage import android_saf
from app.storage.fileops import copy_file_atomic, discard_file


def copy_to_documents(private_path: str, subfolder: str = "EEGMeditation",
                      display_name: str = "") -> str | None:
    """Copy a file from app-private storage to shared Documents folder.

    Args:
        private_path: Full path to the file in app-private storage.
        subfolder: Subfolder under Documents/ (e.g. "EEGMeditation").
        display_name: Filename as shown in file browser. Defaults to basename.

    Returns:
        Human-readable path (e.g. "Documents/EEGMeditation/session_1.csv")
        or None on failure.
    """
    if not os.path.isfile(private_path):
        logger.error(f"copy_to_documents: file not found: {private_path}")
        return None

    if not display_name:
        display_name = os.path.basename(private_path)

    if not android_jni.on_android():
        return _copy_desktop(private_path, subfolder, display_name)

    return _copy_android_mediastore(private_path, subfolder, display_name)


def move_to_documents(private_path: str, display_name: str = "") -> str | None:
    """copy_to_documents, then the private copy removed; a copy that failed leaves it, for the caller to name or
    remove."""
    shared = copy_to_documents(private_path, display_name=display_name)
    if shared:
        discard_file(private_path)
    return shared


def _copy_desktop(private_path: str, subfolder: str, display_name: str) -> str | None:
    """Desktop fallback: copy to ~/Documents/subfolder/."""
    docs = os.path.join(os.path.expanduser("~"), "Documents", subfolder)
    os.makedirs(docs, exist_ok=True)
    dest = os.path.join(docs, display_name)
    copy_file_atomic(private_path, dest)
    logger.info(f"Copied to: {dest}")
    return dest


def _copy_android_mediastore(private_path: str, subfolder: str, display_name: str) -> str | None:
    """Copy the file to Documents/subfolder/ through MediaStore: Android 10+ needs no storage permission for it, and
    the file shows in the system file browser."""
    try:
        uri = _create_entry(subfolder, display_name)
        if uri is None:
            logger.error("MediaStore insert returned None")
            return None
        if not android_saf.write_file_to_uri(uri.toString(), private_path):
            return None
    except Exception as e:
        logger.error(f"MediaStore copy failed: {e}", exc_info=True)
        return None
    shared_path = f"Documents/{subfolder}/{_stored_name(uri) or display_name}"
    logger.info(f"Copied to shared storage: {shared_path}")
    return shared_path


def _create_entry(subfolder: str, display_name: str):
    """A new, empty MediaStore file under Documents/subfolder/ (the Documents root before Android 10): its content://
    URI, or None."""
    from jnius import autoclass  # noqa: PLC0415 - Android only (pyjnius)

    values = autoclass("android.content.ContentValues")()
    values.put("_display_name", display_name)
    values.put("mime_type", _guess_mime(display_name))
    if autoclass("android.os.Build$VERSION").SDK_INT >= 29:
        values.put("relative_path", os.path.join(autoclass("android.os.Environment").DIRECTORY_DOCUMENTS, subfolder))
    collection = autoclass("android.provider.MediaStore$Files").getContentUri("external")
    return android_jni.content_resolver().insert(collection, values)


def _stored_name(uri) -> str | None:
    """The name MediaStore gave the file: one that clashes with a file already there is stored as "name (1).txt"."""
    try:
        return android_saf.query_display_name(uri.toString())
    except Exception as e:  # the file is written: report the name asked for rather than a failure
        logger.warning(f"MediaStore name lookup failed: {e}")
        return None


def _guess_mime(filename: str) -> str:
    """Guess MIME type from filename extension."""
    ext = os.path.splitext(filename)[1].lower()
    return {
        ".csv": "text/csv",
        ".txt": "text/plain",
        ".json": "application/json",
    }.get(ext, "application/octet-stream")
