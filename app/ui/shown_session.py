"""The session the Session screen shows: its graphs and readout, which the running session's events draw, the end card
over them once it has ended, and the profile it belongs to."""
import sqlite3
import time

from app.logger import logger
from app.metrics.series_names import SERIES_NAMES
from app.session.manager import SessionState, elapsed_clock
from app.session.session_events import (
    Alert,
    Connected,
    Connecting,
    Paused,
    ProgramDropped,
    ProgramShown,
    Resumed,
    SegmentStarted,
    Ticked,
    Waiting,
)
from app.session.session_program import PROGRAM_FORMULA_KEYS
from app.ui.app_context import AppContext
from app.ui.graph_series import show_program_series
from app.ui.session_labels import session_title
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
            case Connected(on_mock=on_mock):
                if on_mock:
                    screen.header.update_device_status(True)  # a headset's row is the headset's (Headset.show_selected)
                screen.header.update_state("Running")
                screen.set_start_time(self._session.manager.started_at)
                screen.connect_overlay.hide()  # the session starts its feedback right after (RunningSession._deliver)
            case Paused():
                screen.set_controls_paused()
            case Resumed():
                screen.set_controls_running()
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
                screen.header.update_device_status(False, device_name=name, connecting=True)
                screen.connect_overlay.show(f"Connecting to {name}...")
            case Waiting(message=message):
                screen.connect_overlay.update(message)
            case Alert(message=message):
                screen.show_alert(message)
            case _:
                logger.error(f"No Session screen handler for {event!r}")

    def _show_tick(self, tick: Ticked) -> None:
        screen = self._live_screen
        screen.graph.add_point(tick.metrics, threshold=tick.target, scored=tick.score_key)  # coloured from this point
        screen.stats.update(tick.live)
        screen.header.update_state(tick.metrics.get("state", "Neutral"))
        if tick.shamatha is not None:
            screen.header.set_shamatha(tick.shamatha)
        if tick.scored is not None:
            screen.set_training_series(tick.scored)
        screen.header.update_timer(tick.elapsed)
        screen.add_raw_sample(tick.raw_sample)
        if tick.marked:
            screen.graph.add_marker()
            screen.raw_graph.add_marker()
            screen.band_graph.add_marker()

    def show_retry(self, message: str, device_name: str) -> None:
        """The retry screen of a start whose BT wait ended without a session."""
        self._live_screen.header.update_device_status(False, device_name=device_name)
        self._live_screen.connect_overlay.show_retry(message)

    def lines(self) -> frozenset[str]:
        """The lines the live graph shows now."""
        return frozenset(self._live_screen.graph.visible_keys())

    def update_state(self, state: str) -> None:
        """The Session screen's state line, outside a session: why a Start didn't go ahead, how a start ended."""
        self._live_screen.header.update_state(state)

    def scanning(self) -> None:
        """A Start looks for the profile's headset among the paired devices."""
        self._live_screen.connect_overlay.show("Scanning for MindWave...")
        self._live_screen.set_controls_running()

    def found(self, name: str) -> None:
        self._live_screen.connect_overlay.update(f"Found {name}\nConnecting...")

    def scan_failed(self, message: str) -> None:
        """A Start's scan found no headset to start on: the controls idle, and Retry offered with `message`."""
        self._live_screen.set_controls_idle()
        self._live_screen.connect_overlay.show_retry(message)

    def ready(self) -> None:
        """The idle controls, no overlay: before a Retry's new Start, or while Settings › Device asks which headset."""
        self._live_screen.set_controls_idle()
        self._live_screen.connect_overlay.hide()

    def starting(self) -> None:
        """A session's setup: the running controls, no training mark until a program's first segment."""
        self._live_screen.set_training_series(None)
        self._live_screen.set_controls_running()

    def show_threshold(self, value: float) -> None:
        """The threshold in force, drawn until the ticks step the line."""
        self._live_screen.graph.set_threshold(float(value))

    def hide_overlay(self) -> None:
        self._live_screen.connect_overlay.hide()

    def reload_whole(self) -> None:
        """An ending's, before the session's reset: the whole session on the graphs, and its score."""
        self._reload_graphs()
        self._live_screen.stats.update(self._session.manager.live_score())

    def _reload_graphs(self) -> None:
        """The live graphs reloaded from the mirror with the whole session: a locked stretch never reached them tick by
        tick."""
        try:
            self._live_screen.load_mirror(self.mirror.snapshot())
        except Exception:  # noqa: BLE001 - logged; a failed redraw must not keep the rest of the screen stale
            logger.exception("graph reload from the mirror failed")

    def resumed(self) -> None:
        """Back from a pause (the screen unlocked): a running session's graphs, readout and clock, which its runner kept
        off the screen meanwhile, drawn again in one batch. Not after its ending: the end card covers them, and the
        ending's teardown is that first frame's work (with the reload too it was long enough for an ANR)."""
        if self._session.manager.state != SessionState.RUNNING:
            logger.info("on_resume: session not RUNNING, no graph reload")
            return
        started = time.monotonic()
        self._reload_graphs()
        if self.mirror.last_metrics:  # no tick yet: the readout still shows the start's
            self._live_screen.stats.update(self._session.manager.live_score())
            self._live_screen.header.update_state(self.mirror.last_state)
            self._live_screen.header.set_shamatha(self._session.run.shamatha_active)
        self._live_screen.header.update_timer(self._session.manager.elapsed_formatted)
        logger.info(f"on_resume: refresh complete in {time.monotonic() - started:.3f}s")

    def idle(self) -> None:
        """The screen's part of every teardown: idle controls, no device link, no training mark, no shamatha pill."""
        self._live_screen.set_training_series(None)
        self._live_screen.set_controls_idle()
        self._live_screen.header.update_device_status(False)
        self._live_screen.header.set_shamatha(False)

    def finished(self, stats: dict | None, session_id: int | None) -> None:
        """An ending's last: FINISHED with the saved duration (the clock froze at a lock), History told, and the end card
        of a saved session, titled as its History row."""
        self._live_screen.header.update_state("FINISHED")
        if stats:
            self._live_screen.header.update_timer(elapsed_clock(stats.get("duration", 0)))
        self._history.mark_dirty()
        if not (stats and session_id):
            return
        try:
            saved = self._ctx.db.get_session(session_id)
        except sqlite3.Error:
            logger.exception(f"Session {session_id} saved, but its title couldn't be read for the end card")
            saved = None
        self._saved_notes = ""
        self._live_screen.end_card.show(session_id, stats, title=session_title(saved) if saved else "")

    def on_save_notes(self, *args) -> None:
        if self._live_screen.end_card.notes == self._saved_notes:
            if self._saved_notes:
                self._ctx.toast("Notes saved")  # already saved; say so rather than ignore the tap
            return
        self.flush_notes()

    def flush_notes(self) -> None:
        """Write the card's notes only if they changed since the last save, so an untouched card writes nothing."""
        sid = self._live_screen.end_card.session_id
        notes = self._live_screen.end_card.notes
        if sid and notes != self._saved_notes and self._history.save_notes(sid, notes=notes):
            self._saved_notes = notes

    def on_ok(self, *args) -> None:
        self.close(keep_notes=True)

    def close(self, keep_notes: bool) -> None:
        """Close the end card and stop its bell; its notes are saved only while its session still exists."""
        if keep_notes:
            self.flush_notes()
        self._audio.stop_timer_bell()
        self._live_screen.end_card.hide()

    def on_sessions_deleted(self, ids: list[int]) -> None:
        """History deleted these sessions: the Session screen lets go of one it shows (the end card, its display)."""
        if self._session.recorder.session_id in ids or self._live_screen.end_card.session_id in ids:
            self.drop(keep_notes=False)

    def drop(self, keep_notes: bool) -> None:
        """Take the shown session off the Session screen: its end card, if open, and its display."""
        if self._live_screen.end_card.session_id is not None:
            self.close(keep_notes)
        self.clear()
        self.owner = None

    def on_delete(self, *args) -> None:
        sid = self._live_screen.end_card.session_id
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
