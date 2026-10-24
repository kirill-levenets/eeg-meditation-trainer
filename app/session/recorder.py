"""A running session's way into the database: each tick's row buffered with its score, and checkpoints that write the
session's row and the buffered rows in one transaction."""
import threading
from collections.abc import Callable

from app.config import APP
from app.logger import logger
from app.session.manager import SessionState


class SessionRecorder:
    """A session reaches the DB only through checkpoint(): at the 60 s flush, on leaving the app, at a backup and at the
    final save. A process killed between checkpoints keeps the row and the data of the last one, which agree. Any
    thread, no Kivy."""

    def __init__(self, db, session_manager, *, with_score: Callable[[dict], dict],
                 row_fields: Callable[[], dict]) -> None:
        self._db = db
        self._session_manager = session_manager
        self._with_score = with_score
        self._row_fields = row_fields  # the row's profile, name, formulas, program, engine version and start
        # A tick (session stats + buffered row), a checkpoint's snapshot of both, and every reset, one at a time.
        self._lock = threading.Lock()
        self.session_id: int | None = None  # the row, from the session's first checkpoint
        self._buffer: list[dict] = []
        self._flush_counter = 0

    def begin(self) -> None:
        """A new session: no row yet and nothing buffered."""
        with self._lock:
            self._buffer = []
            self._flush_counter = 0
            self.session_id = None

    def record(self, metrics: dict, full_record: dict) -> dict | None:
        """Score a tick and buffer its stamped row, as one step for a checkpoint: what it was scored on (score_key,
        score_value, score_target), or None if not scored."""
        with self._lock:
            score = self._session_manager.add_metric(metrics)
            if not score:
                return None
            full_record.update(score)
            self._buffer.append(full_record)
        return score

    def flush_tick(self) -> None:
        """Every FLUSH_INTERVAL_SECONDS of ticks, checkpoint the session: its row as well as its data."""
        with self._lock:
            self._flush_counter += 1
            due = self._flush_counter >= int(APP.FLUSH_INTERVAL_SECONDS / APP.UPDATE_FREQUENCY) and bool(self._buffer)
        if due:
            self.checkpoint()

    def checkpoint(self, stats: dict | None = None) -> None:
        """Bring the session's row and its buffered ticks into the DB in one transaction: the final save passes the
        stop's `stats`; without them, a session that isn't running or paused has nothing to checkpoint."""
        with self._lock:
            if stats is None:
                if self._session_manager.state not in (SessionState.RUNNING, SessionState.PAUSED):
                    return
                stats = self._with_score(self._session_manager.compute_statistics())
            batch, self._buffer = self._buffer, []
            try:
                sid = self._db.checkpoint_session(self.session_id, stats, batch, **self._row_fields())
            except Exception:
                self._buffer[:0] = batch  # kept for the next checkpoint
                raise
            self._flush_counter = 0
            if sid is None:
                logger.error("Session checkpoint skipped — DB shutting down; session NOT persisted")
                return
            self.session_id = sid

    def discard(self) -> None:
        """Delete the session's row and drop its buffer (its profile was deleted), after a checkpoint still writing."""
        with self._lock:
            if self.session_id is not None:
                self._db.delete_session(self.session_id)
                logger.info(f"Session {self.session_id} discarded (profile deleted)")
                self.session_id = None
            self._buffer = []
