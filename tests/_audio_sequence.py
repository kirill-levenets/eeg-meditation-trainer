"""Records the audio tests' sequence threads as they start; only those sleep through the test's gate."""
import threading
import time


def record_sequences(monkeypatch) -> list:
    """The sequence threads, kept as they start: a quick one is gone before a search would find it."""
    started, base = [], threading.Thread

    class Recording(base):
        def start(self):
            if getattr(getattr(self, "_target", None), "__name__", "") == "_run_sequence":
                started.append(self)
            super().start()
    monkeypatch.setattr(threading, "Thread", Recording)
    return started


def sequence_sleep(monkeypatch, sequences: list, sleep) -> None:
    """A recorded sequence thread sleeps through `sleep(seconds)`; every other thread through the real time.sleep."""
    real = time.sleep
    monkeypatch.setattr(time, "sleep", lambda s: sleep(s) if threading.current_thread() in sequences else real(s))
