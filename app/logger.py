import logging
import os
import sys
import time
from contextlib import contextmanager

logger = logging.getLogger("eeg_meditation")
logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
handler.setFormatter(formatter)
logger.addHandler(handler)

# Perf instrumentation: log [PERF] block timings. Off by default; set EEG_PERF=1
# to enable, then grep logs for "[PERF]".
PERF_ENABLED = os.environ.get("EEG_PERF", "0") == "1"


@contextmanager
def timed(label: str):
    """Log wall-time of a block as `[PERF] label: N.Nms` when PERF_ENABLED."""
    if not PERF_ENABLED:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        logger.info("[PERF] %s: %.1fms", label, (time.perf_counter() - t0) * 1000.0)


__all__ = ["logger", "timed"]
