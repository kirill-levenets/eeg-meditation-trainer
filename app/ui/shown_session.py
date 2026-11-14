"""The session the Session screen shows: its graphs and readout, which the running session's events draw, the end card
over them once it has ended, and the profile it belongs to."""
from app.logger import logger
from app.metrics.series_names import SERIES_NAMES
from app.session.session_events import (
    Alert,
    Connecting,
    ProgramDropped,
    ProgramShown,
    SegmentStarted,
    Ticked,
    Waiting,
)
from app.session.session_program import PROGRAM_FORMULA_KEYS
from app.ui.app_context import AppContext
from app.ui.program_run import show_program_series
from app.ui.theme import C


class ShownSession:
    """The Session screen shows one profile's session: its owner is set at Start, and picking another profile drops it.
    The end card only adds notes to its session or deletes it (every ending has saved it); every close goes through
    `close`, and the card's notes are written only when they changed since the last save."""

    def __init__(self, ctx: AppContext, live_screen, audio, history, session) -> None:
        self._ctx = ctx
        self._live_screen = live_screen
        self._audio = audio
        self._history = history  # the card's notes and delete go through History's one path
        self._session = session  # its record's session_id, kept after its stop, and its mirror of the live graphs
        self.owner: int | None = None  # the profile whose session the Session screen shows: set at Start
        self._saved_notes = ""  # notes last written from the card for the session it shows

    @property
    def mirror(self):
        """The display's graphs, kept by the session's runner through a screen lock."""
        return self._session.mirror

    def take(self, uid: int | None) -> None:
        """A Start: the display empties for the new session, which belongs to `uid`."""
        self.clear()
        self.owner = uid

    def show(self, event) -> None:
        """Main thread: what the running session's event changes on the Session screen."""
        screen = self._live_screen
        match event:
            case Ticked():
                self._show_tick(event)
            case SegmentStarted(key=key, line_name=line_name):
                if line_name is not None:  # a custom segment's line: labelled and shown
                    screen.graph.set_series_name(key, line_name)
                    screen.graph.set_visible(key, True)
                screen.set_training_series(key)  # bold + » on the trained series
            case ProgramShown(plan=plan):
                show_program_series(screen.graph, plan)
            case ProgramDropped():
                for slot in PROGRAM_FORMULA_KEYS:
                    screen.graph.set_series_name(slot, SERIES_NAMES.get(slot, "Program"))  # drop stale labels
                    screen.graph.set_visible(slot, False)  # never linger as a user selection
                screen.graph.set_program_lines()
            case Connecting(name=name):
                screen.update_device_status(False, device_name=name, connecting=True)
                screen.show_overlay(f"Connecting to {name}...")
            case Waiting(message=message):
                screen.update_overlay(message)
            case Alert(message=message):
                screen.show_alert(message)
            case _:
                logger.error(f"No Session screen handler for {event!r}")

    def _show_tick(self, tick: Ticked) -> None:
        screen = self._live_screen
        screen.graph.add_point(tick.metrics, threshold=tick.target, scored=tick.score_key)  # coloured from this point
        screen.update_stats(tick.live)
        screen.update_state(tick.metrics.get("state", "Neutral"))
        if tick.shamatha is not None:
            screen.set_shamatha(tick.shamatha)
        if tick.scored is not None:
            screen.set_training_series(tick.scored)
        screen.update_timer(tick.elapsed)
        screen.add_raw_sample(tick.raw_sample)
        if tick.marked:
            screen.graph.add_marker()
            screen.raw_graph.add_marker()
            screen.band_graph.add_marker()

    def show_retry(self, message: str, device_name: str) -> None:
        """The retry screen of a start whose BT wait ended without a session."""
        self._live_screen.update_device_status(False, device_name=device_name)
        self._live_screen.show_overlay_retry(message)

    def show_end_card(self, session_id: int, stats: dict, title: str) -> None:
        self._saved_notes = ""
        self._live_screen.show_summary(session_id, stats, title=title)

    def on_save_notes(self, *args) -> None:
        if self._live_screen.summary_notes == self._saved_notes:
            if self._saved_notes:
                self._ctx.toast("Notes saved")  # already saved; say so rather than ignore the tap
            return
        self.flush_notes()

    def flush_notes(self) -> None:
        """Write the card's notes only if they changed since the last save, so an untouched card writes nothing."""
        sid = self._live_screen.summary_session_id
        notes = self._live_screen.summary_notes
        if sid and notes != self._saved_notes and self._history.save_notes(sid, notes=notes):
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
        if self._session.recorder.session_id in ids or self._live_screen.summary_session_id in ids:
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
        self._ctx.confirm("Delete session", "Delete this session permanently? This can't be undone.",
                          "Delete", lambda: self._history.delete_sessions([sid]), ok_color=C.DANGER)

    def clear(self) -> None:
        """Empty the Session screen of its session: graphs, their mirrors, threshold steps and the readout."""
        self.mirror.clear()
        self._live_screen.graph.clear_data()
        self._live_screen.raw_graph.clear_data()
        self._live_screen.band_graph.clear_data()
        self._live_screen.graph.set_threshold_steps(None)  # each tick's target steps it, a program's too
        self._live_screen.clear_readout()
