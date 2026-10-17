"""A running session's recorder keeps its row id and its buffer in step with its checkpoints, whichever thread runs them."""
import threading
import time
from unittest.mock import MagicMock

from app.session.manager import SessionState
from app.session.recorder import SessionRecorder


def _recorder(db) -> SessionRecorder:
    sm = MagicMock(state=SessionState.RUNNING)
    sm.compute_statistics.return_value = {"duration": 60}
    return SessionRecorder(db, sm, with_score=lambda stats: stats, row_fields=lambda: {})


def test_a_discard_during_the_first_checkpoint_deletes_the_row_it_writes():
    # The profile is deleted while the tick thread is inside the session's first checkpoint (the tick's 1 s join timed
    # out on a slow write): the discard must wait for it, or the row it writes is left behind under no profile.
    writing, release = threading.Event(), threading.Event()
    db = MagicMock()

    def checkpoint_session(sid, stats, batch, **fields):
        writing.set()
        release.wait(2)
        return 42

    db.checkpoint_session.side_effect = checkpoint_session
    recorder = _recorder(db)
    writer = threading.Thread(target=recorder.checkpoint)
    writer.start()
    assert writing.wait(2)
    discarder = threading.Thread(target=recorder.discard)
    discarder.start()
    time.sleep(0.2)  # the discard arrives while the row is being written
    release.set()
    writer.join(2)
    discarder.join(2)
    db.delete_session.assert_called_once_with(42)
    assert recorder.session_id is None


def test_the_flush_checkpoints_once_its_interval_of_ticks_has_rows():
    db = MagicMock()
    db.checkpoint_session.return_value = 7
    recorder = _recorder(db)
    recorder._buffer = [{"shamatha_score": 1.0}]
    recorder._flush_counter = 119  # 60 s at 2 Hz is 120 ticks
    recorder.flush_tick()
    db.checkpoint_session.assert_called_once()
    assert recorder.session_id == 7 and recorder._buffer == []
