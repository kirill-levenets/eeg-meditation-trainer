"""File copies for app data: bytes only, never metadata, and never a partly written target."""

import os
import shutil
import tempfile

from app.logger import logger


def copy_file_atomic(src: str, dst: str) -> None:
    """Copy bytes + mode via a temp file and os.replace (dst untouched or complete); no xattrs: Android's SELinux label copy raises EACCES in Python 3.11."""
    dst = os.path.realpath(dst)  # a symlinked target is written through, as copy2 did
    with open(src, "rb") as fsrc:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dst) or ".", prefix=".", suffix=".part")
        try:
            with os.fdopen(fd, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst)
                fdst.flush()
                os.fsync(fdst.fileno())
            shutil.copymode(src, tmp)
            os.replace(tmp, dst)
        except BaseException:
            discard_file(tmp)
            raise


def discard_file(path: str) -> None:
    """Remove a temp or leftover file; a missing file is fine, any other failure is logged."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning(f"Could not remove {path}: {e}")
