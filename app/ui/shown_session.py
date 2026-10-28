"""The session the Session screen shows: its graphs and readout, the end card over them once it has ended, and the
profile it belongs to."""
from collections.abc import Callable

from app.ui.theme import C


class ShownSession:
    """The Session screen shows one profile's session: its owner is set at Start, and picking another profile drops it.
    The end card only adds notes to its session or deletes it (every ending has saved it); every close goes through
    `close`, and the card's notes are written only when they changed since the last save."""

    def __init__(self, live_screen, mirror, audio, *, save_notes: Callable[[int, str], bool],
                 delete_sessions: Callable[[list[int]], None], confirm: Callable[..., None],
                 toast: Callable[[str], None], last_session_id: Callable[[], int | None]) -> None:
        self._live_screen = live_screen
        self._mirror = mirror
        self._audio = audio
        self._save_notes = save_notes
        self._delete_sessions = delete_sessions
        self._confirm = confirm
        self._toast = toast
        self._last_session_id = last_session_id  # the session the display shows, kept after its stop
        self.owner: int | None = None  # the profile whose session the Session screen shows: set at Start
        self._saved_notes = ""  # notes last written from the card for the session it shows

    def take(self, uid: int | None) -> None:
        """A Start: the display empties for the new session, which belongs to `uid`."""
        self.clear()
        self.owner = uid

    def show_end_card(self, session_id: int, stats: dict, title: str) -> None:
        self._saved_notes = ""
        self._live_screen.show_summary(session_id, stats, title=title)

    def on_save_notes(self, *args) -> None:
        if self._live_screen.summary_notes == self._saved_notes:
            if self._saved_notes:
                self._toast("Notes saved")  # already saved; say so rather than ignore the tap
            return
        self.flush_notes()

    def flush_notes(self) -> None:
        """Write the card's notes only if they changed since the last save, so an untouched card writes nothing."""
        sid = self._live_screen.summary_session_id
        notes = self._live_screen.summary_notes
        if sid and notes != self._saved_notes and self._save_notes(sid, notes):
            self._saved_notes = notes

    def on_ok(self, *args) -> None:
        self.close(keep_notes=True)

    def close(self, keep_notes: bool) -> None:
        """Close the end card and stop its bell; its notes are saved only while its session still exists."""
        if keep_notes:
            self.flush_notes()
        self._audio.stop_timer_bell()
        self._live_screen.hide_summary()

    def on_sessions_deleted(self, ids: list[int]) -> None:
        """History deleted these sessions: the Session screen lets go of one it shows (the end card, its display)."""
        if self._last_session_id() in ids or self._live_screen.summary_session_id in ids:
            self.drop(keep_notes=False)

    def drop(self, keep_notes: bool) -> None:
        """Take the shown session off the Session screen: its end card, if open, and its display."""
        if self._live_screen.summary_session_id is not None:
            self.close(keep_notes)
        self.clear()
        self.owner = None

    def on_delete(self, *args) -> None:
        sid = self._live_screen.summary_session_id
        if not sid:
            return  # silent-ok: the card is not showing a session

        # The delete closes the card and stops the gong once the session is gone; a failed one leaves both.
        self._confirm("Delete session", "Delete this session permanently? This can't be undone.",
                      "Delete", lambda: self._delete_sessions([sid]), ok_color=C.DANGER)

    def clear(self) -> None:
        """Empty the Session screen of its session: graphs, their mirrors, threshold steps and the readout."""
        self._mirror.clear()
        self._live_screen.graph.clear_data()
        self._live_screen.raw_graph.clear_data()
        self._live_screen.band_graph.clear_data()
        self._live_screen.graph.set_threshold_steps(None)  # each tick's target steps it, a program's too
        self._live_screen.clear_readout()
