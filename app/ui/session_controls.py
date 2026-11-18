"""The Session screen's controls and the session they start and end: Start (with its headset scan when none is picked),
the BT wait's Cancel and Retry, Pause, Stop and its confirm, the marker, a profile's discard, the threshold in force,
and the order the app's part of each session event runs in."""
from app.config import APP
from app.logger import logger
from app.session.manager import SessionState
from app.session.session_events import (
    Alert,
    Connected,
    Ended,
    LinkChanged,
    Notice,
    StartFailed,
)
from app.session.session_run import Phase, SessionRun
from app.ui.app_context import AppContext


class SessionControls:
    """Owns no session state: the session (`RunningSession`) holds it, the screen (`ShownSession`) draws it, Settings
    (`SessionSettings`) give its config, `SoundSources` its players, `Headset` its headset; this decides what a control
    or an event does with them, in which order."""

    def __init__(self, ctx: AppContext, session, shown, settings, headset, sounds) -> None:
        self._ctx = ctx
        self._session = session
        self._shown = shown
        self._settings = settings
        self._headset = headset
        self._sounds = sounds
        self._stop_confirm = None  # "Stop session?" while it is open: an ending closes it

    # ---- Start ----

    def start(self) -> None:
        """The Start button: the session starts on the mock data or the profile's headset, else its headset is first
        looked for among the paired devices."""
        uid = self._ctx.user_id()
        if not uid:
            self._shown.update_state("Select a user profile first")
            logger.warning("Session start blocked: no user selected")
            return
        run = self._session.open(uid)
        stream = self._headset.stream
        if APP.USE_MOCK_DEVICE or stream._device_address:  # the profile's headset, or one picked in Settings
            self._session.stream = self._session.mock_stream if APP.USE_MOCK_DEVICE else stream
            self._start()
            return
        self._shown.scanning()
        logger.info("Auto-scanning for BT device before session start")
        self._headset.find_paired(lambda devices: self._after_scan(run, devices))

    def _after_scan(self, run: SessionRun, devices: list[dict]) -> None:
        """Main thread: the Start's scan of the paired devices ended; start on the profile's headset if it found one,
        else say what to do."""
        if run is not self._session.run:
            return  # cancelled while scanning
        if run.user_id != self._ctx.user_id():
            self.cancel("IDLE")  # the Start was the profile picked away while it scanned
            return
        mindwaves = self._headset.adopt(devices)
        if self._headset.stream._device_address:
            self._session.stream = self._headset.stream
            self._shown.found(self._headset.name())
            self._start()
            return
        if mindwaves:
            self._shown.ready()
            self._headset.ask_to_pick(mindwaves)
        elif devices:
            self._shown.scan_failed("No MindWave found among paired devices.\n"
                                    "Pair it in system Bluetooth settings,\nor select manually in Settings tab.")
        else:
            self._shown.scan_failed("No paired Bluetooth devices found.\n"
                                    "Pair your MindWave in system\nBluetooth settings first.")

    def _start(self) -> None:
        """The device is resolved: Settings read into the session's config, the screen made ready, then the session's own
        start."""
        self._shown.take(self._ctx.user_id())
        mock = self._session.stream is self._session.mock_stream  # the stream this Start chose
        config = self._settings.read(mock=mock, device="Mock" if mock else self._headset.name(), lines=self._shown.lines)
        self.put_threshold_in_force(config.threshold)  # this session's, whatever the last one left running
        self._session.prepare(config, self._sounds.prepare_session(config.program, config.gong))
        self._shown.starting()
        self._settings.started(config, self.refuse_program_threshold)
        self._session.connect()  # a refused reader undoes all of the above at once (StartFailed)

    def cancel(self, state: str = "IDLE") -> None:
        """End a start that hasn't become a session: the device scan, the BT wait, or data that arrived in the same frame
        as the Cancel."""
        run = self._session.run
        if run is not None and run.phase is not Phase.STARTING:  # it reached the BT wait (or its give-up, just now)
            self._session.abort()
            self._shown.owner = None  # no session came of the start, which emptied the display
        self._shown.hide_overlay()
        self._undo()  # also resets a session that started in the frame of the Cancel
        self._shown.update_state(state)

    def retry(self) -> None:
        """The retry screen's Retry: a new Start."""
        self._shown.ready()
        self.start()

    def _undo(self) -> None:
        """Main thread: undo what a Start set up, for a session that ended or never started: the session's part (its run
        dropped, so what is still queued for it does nothing), then the screen's, then Settings'."""
        self._session.undo_setup()
        self._shown.idle()
        self._settings.teardown()

    # ---- while it runs, and its ending ----

    def toggle_pause(self) -> None:
        """The Pause / Resume button: the session's runner pauses or resumes it, and its event updates the screen."""
        self._session.toggle_pause()

    def mark(self) -> None:
        """Place a marker on the session's next recorded tick."""
        self._session.mark()

    def stop(self) -> None:
        """The Stop button: a start not yet a session is cancelled; a session asks first, and goes on recording while
        the question is open (Cancel loses nothing, Stop saves up to then)."""
        # Decided by the session, not the run's phase: a wait that has just ended is over before its idle UI shows.
        if self._session.manager.state == SessionState.FINISHED:
            logger.info("Stop ignored: the session has already ended and its teardown is queued")
            return
        if self._session.manager.state not in (SessionState.RUNNING, SessionState.PAUSED):
            self.cancel("Cancelled")
            logger.info("Session cancelled before it started")
            return
        # Every ending saves (the same path as a timer or lost-signal stop); deleting is a confirmed card action.
        self._stop_confirm = self._ctx.confirm(
            "Stop session?", "The session will be saved. You can delete it on the next screen.",
            "Stop", lambda: self.stop_and_save(reason="user"))

    def stop_and_save(self, reason: str = "user") -> None:
        """Stop the session and save it (no dialog): its runner ends and saves it, and its Ended event tears the screen
        down, as every ending does."""
        self._session.stop(reason)

    def discard(self) -> None:
        """Halt a running session and DELETE its data, when its owning profile is deleted: a checkpoint (the 60 s flush,
        leaving the app, a backup) may already have written its row, which would survive as an orphan. The screen
        returns to idle at once, before the profile's delete goes on."""
        self._session.discard()  # waits for the runner: the row is gone when it returns, the players torn down
        self._finish_ui(None, None)

    def refused(self, doing: str, why: str = "") -> bool:
        """True, after telling the user, while a session runs or connects: until it stops it owns its profile, the
        database it saves to, the metric it is scored on and a program's targets."""
        if not self._session.live():
            return False
        self._ctx.info("Session in progress", f"{why} Stop the current session before {doing}.".lstrip())
        return True

    def on_event(self, event) -> None:
        """Main thread: the session's events, its runner's for the current run, and those its start and a program's end
        raise here; the screen's part of each goes to `ShownSession.show`."""
        match event:
            case Connected(on_mock=on_mock):
                if not on_mock:
                    self._headset.show_selected()
                self._shown.show(event)
            case StartFailed(message=message):
                self._shown.owner = None  # no session came of the start, which emptied the display
                self._undo()
                self._shown.show_retry(message, self._headset.name())
            case Ended(stats=stats, session_id=session_id, alert=alert):
                if self._stop_confirm is not None:  # the timer or a check ended it under "Stop session?"
                    self._stop_confirm.dismiss()
                    self._stop_confirm = None
                if alert:
                    self._shown.show(Alert(alert))
                self._finish_ui(stats, session_id)
                logger.info("Session ended and saved" if stats else "Session ended")
            case LinkChanged():
                self._headset.show_selected()
            case Notice(title=title, message=message):
                self._ctx.info(title, message)
            case _:
                self._shown.show(event)

    def _finish_ui(self, stats: dict | None, session_id: int | None) -> None:
        """Main thread, after a session was saved (or discarded): the whole session on the graphs, the session and the
        screen back to idle, then FINISHED and the end card, then Settings' counts."""
        self._shown.reload_whole()  # before the reset: the score is the manager's
        self._undo()
        self._shown.finished(stats, session_id)
        self._settings.saved()

    # ---- the threshold ----

    def on_threshold_slider(self, value: int) -> None:
        """The Settings threshold slider moved: an ended session's line leaves the screen (it is not the threshold the
        next one runs on), the value goes in force once the drag settles, not once per step, and the profile keeps it."""
        if self._shown.mirror.metrics and not self._session.live():
            self._shown.clear()
        self._ctx.after_settle("apply_threshold", lambda: self.apply_threshold(value))
        self._ctx.setting_changed("threshold")

    def put_threshold_in_force(self, value: int) -> None:
        """The session manager owns the threshold; the graph draws it until ticks step the line."""
        self._session.set_threshold(value)  # also what a session waiting for the headset starts with
        self._shown.show_threshold(value)

    def apply_threshold(self, value: int) -> None:
        """Put the Settings threshold in force, unless a running program owns it (a profile reload, a late settle)."""
        if not (self._session.program_run.active and self._session.live()):  # a program's segments own its targets
            self.put_threshold_in_force(value)

    def refuse_program_threshold(self) -> bool:
        """A touch on the threshold controls a program locked: True, after saying why, until the session ends."""
        return self.refused("changing the threshold", why="This program sets its own targets.")
