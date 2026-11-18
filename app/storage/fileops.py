"""File copies for app data: bytes only, never metadata, and never a partly written target."""

import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from typing import BinaryIO

from app.logger import logger


def write_file_atomic(dst: str, write: Callable[[BinaryIO], None], mode: int | None = None) -> None:
    """Have `write` fill a temp file beside dst, then os.replace it in: dst is untouched or complete."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dst) or ".", prefix=".", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            write(f)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, dst)
    except BaseException:
        discard_file(tmp)
        raise


def copy_file_atomic(src: str, dst: str) -> None:
    """Copy bytes + mode, atomically; no xattrs: Android's SELinux label copy raises EACCES in Python 3.11."""
    dst = os.path.realpath(dst)  # a symlinked target is written through, as copy2 did
    with open(src, "rb") as fsrc:
        mode = stat.S_IMODE(os.fstat(fsrc.fileno()).st_mode)
        write_file_atomic(dst, lambda fdst: shutil.copyfileobj(fsrc, fdst), mode)


def discard_file(path: str) -> None:
    """Remove a temp or leftover file; a missing file is fine, any other failure is logged."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning(f"Could not remove {path}: {e}")
