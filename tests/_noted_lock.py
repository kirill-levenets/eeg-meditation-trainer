"""A lock for tests of lock discipline: a real lock that notes whether it is held and how often it was taken."""
import threading


class NotedLock:
    def __init__(self) -> None:
        self._lock, self.held, self.takes = threading.Lock(), False, 0

    def __enter__(self) -> None:
        self._lock.acquire()
        self.held = True
        self.takes += 1

    def __exit__(self, *exc) -> None:
        self.held = False
        self._lock.release()
