"""Android shared storage helper — copy files to Documents via MediaStore.

Uses pyjnius to call Android's ContentResolver.insert() API, which is
the only way to write to shared storage (Documents, Downloads, etc.)
on Android 10+ with scoped storage.

On non-Android platforms, falls back to simple file copy.
"""

import os
import shutil
import sys

from app.logger import logger

_IS_ANDROID = hasattr(sys, "getandroidapilevel")


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

    if not _IS_ANDROID:
        return _copy_desktop(private_path, subfolder, display_name)

    return _copy_android_mediastore(private_path, subfolder, display_name)


def _copy_desktop(private_path: str, subfolder: str, display_name: str) -> str | None:
    """Desktop fallback: copy to ~/Documents/subfolder/."""
    docs = os.path.join(os.path.expanduser("~"), "Documents", subfolder)
    os.makedirs(docs, exist_ok=True)
    dest = os.path.join(docs, display_name)
    shutil.copy2(private_path, dest)
    logger.info(f"Copied to: {dest}")
    return dest


def _copy_android_mediastore(private_path: str, subfolder: str,
                              display_name: str) -> str | None:
    """Copy file to Documents via Android MediaStore API (pyjnius).

    Works on Android 10+ without any storage permissions.
    File becomes visible in system file browser under Documents/subfolder/.
    """
    try:
        from jnius import autoclass

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        ContentValues = autoclass("android.content.ContentValues")
        MediaStoreFiles = autoclass("android.provider.MediaStore$Files")
        Environment = autoclass("android.os.Environment")
        Build_VERSION = autoclass("android.os.Build$VERSION")

        resolver = activity.getContentResolver()

        # Build metadata for the new file
        values = ContentValues()
        values.put("_display_name", display_name)
        values.put("mime_type", _guess_mime(display_name))

        if Build_VERSION.SDK_INT >= 29:
            # Android 10+: use relative_path for scoped storage
            relative_path = os.path.join(
                Environment.DIRECTORY_DOCUMENTS, subfolder,
            )
            values.put("relative_path", relative_path)
        # On Android <10 the file goes to the root Documents collection

        # Insert into MediaStore — creates the entry and returns a content:// URI
        collection_uri = MediaStoreFiles.getContentUri("external")
        uri = resolver.insert(collection_uri, values)

        if uri is None:
            logger.error("MediaStore insert returned None")
            return None

        # Write file contents through the URI's output stream
        output_stream = resolver.openOutputStream(uri)
        if output_stream is None:
            logger.error("openOutputStream returned None")
            return None

        with open(private_path, "rb") as f:
            chunk_size = 8192
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                output_stream.write(chunk)

        output_stream.flush()
        output_stream.close()

        shared_path = f"Documents/{subfolder}/{display_name}"
        logger.info(f"Copied to shared storage: {shared_path}")
        return shared_path

    except Exception as e:
        logger.error(f"MediaStore copy failed: {e}", exc_info=True)
        return None


def _guess_mime(filename: str) -> str:
    """Guess MIME type from filename extension."""
    ext = os.path.splitext(filename)[1].lower()
    return {
        ".csv": "text/csv",
        ".txt": "text/plain",
        ".json": "application/json",
    }.get(ext, "application/octet-stream")
