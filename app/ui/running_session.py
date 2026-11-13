"""The session's machinery, built once and run by every Start on the config that Start read: its state and score, its
way into the database, the metrics engine, its formula lines, a program, the timer, each tick's checks, the BT wait
and what keeps the phone awake; and the one thread that writes all of it while a session runs."""
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.config import APP
from app.crash_handler import report_soft_error
from app.eeg.band_spec import BAND_KEYS
from app.eeg.mock_stream_v2 import MockEEGStream
from app.keep_awake import KeepAwake
from app.logger import logger
from app.metrics.engine import MetricsEngine
from app.metrics.formula_slots import FormulaSlots
from app.session.manager import SessionManager, SessionState
from app.session.recorder import RecordedTick, SessionRecorder
from app.session.scoring import shamatha_transition
from app.session.session_config import SessionConfig
from app.session.session_run import Phase, SessionRun
from app.session.timer_state import TimerState
from app.ui.app_context import AppContext
from app.ui.audio_metric import sound_metric
from app.ui.bt_wait import BtWait
from app.ui.live_mirror import LiveMirror
from app.ui.program_run import ProgramRun
from app.ui.session_labels import start_stamp
from app.ui.session_watch import SessionWatch

_JOIN_SECONDS = 1.0  # how long the main thread waits for the runner to take a command before it acts itself
_TAKEN_SECONDS = 15.0  # how long it waits for a command the runner took: the reader's stop joins for 5 s, a save writes


@dataclass(frozen=True)
class Connected:
    """The headset's first data started the session."""


@dataclass(frozen=True)
class StartFailed:
    """The BT wait gave up; `message` is the retry screen's."""

    message: str


@dataclass(frozen=True)
class Ended:
    """The run ended: saved with `stats` as `session_id` (both None when the save failed), `alert` saying why if a check
    ended it."""

    stats: dict | None
    session_id: int | None
    alert: str = ""


@dataclass(frozen=True)
class Paused:
    """The session paused."""


@dataclass(frozen=True)
class Resumed:
    """The paused session goes on."""


class RunningSession:
    """Owns the parts a session runs on and answers what it is scored on and saved as, from its config, never a live
    setting. While a run's runner thread lives it is the only writer of the session's state: the main thread sends it
    commands, and it hands what the screen must do back as events, on the main thread and for that run only. Without a
    runner of its own run (before its start, after its end, a stuck one's run ended) a command runs where it is sent."""

    def __init__(self, ctx: AppContext, audio, live_screen, headset, *, on_event: Callable[[object], None]) -> None:
        self._ctx = ctx
        self._audio = audio
        self._live_screen = live_screen
        self._on_event = on_event
        self.config: SessionConfig | None = None  # the last Start's
        self.run: SessionRun | None = None  # the current Start, until its ending's teardown on the main thread
        self.formulas = FormulaSlots()  # its own lines, built from the config: their avg() windows are the session's
        self.mock_stream = MockEEGStream()
        self.stream = self.mock_stream  # the one this Start reads: the mock, or the headset's (the link outlives runs)
        self.mirror = LiveMirror()  # the live graphs' data, kept by the runner through a screen lock
        self.ui_paused = False  # the screen is locked: a tick queues no per-tick drawing (it would flood the unlock)
        self.engine = MetricsEngine()
        self.manager = SessionManager()
        self.manager.set_audio(audio)
        self.timer = TimerState()
        self.program_run = ProgramRun(ctx, self.manager, audio, live_screen, formula_vars=self.formula_vars)
        self.recorder = SessionRecorder(ctx.db, self.manager, with_score=self.with_score, row_fields=self.row_fields)
        self.watch = SessionWatch(audio, live_screen, headset, on_main=ctx.on_main)
        self.bt_wait = BtWait(headset.stream, live_screen, headset_name=headset.name, on_main_for=self.on_main_for)
        self.keep_awake = KeepAwake()  # held from a session's setup to its ending
        self._runner: threading.Thread | None = None
        self._commands: queue.Queue | None = None
        self._served: SessionRun | None = None  # the run the runner works for: it takes commands for no other
        self._runner_lock = threading.Lock()  # a runner's start and exit, and a command's choice: queue it or run it

    # ---- what the session runs on and is saved as ----

    def begin(self, config: SessionConfig) -> None:
        """A Start: the session runs on `config` until its next Start, with its lines, timer, engine and record new."""
        self.config = config
        self.formulas = FormulaSlots()
        self.formulas.load(list(config.formulas))
        self.timer.set_enabled(config.timer_minutes is not None)
        self.timer.set_duration(config.timer_minutes or 1)
        self.engine.reset()
        self.recorder.begin()

    def drive_key(self) -> str:
        """The metric that drives the feedback sound now, which the session is scored on."""
        program_key = self.program_run.audio_key if self.program_run.active else ""
        return sound_metric(self.config.metric, program_key, self.formulas)

    def formula_vars(self, raw_sample: dict, metrics: dict) -> dict:
        """Variable dict for custom-formula evaluation (raw + metrics + derived/sqrt bands)."""
        fvars = {**raw_sample, **metrics}
        fvars.update(self.engine.derive_bands(raw_sample))
        sqrt_bands = self.engine.compute_sqrt_relative_bands(raw_sample)
        fvars.update({f"s_{k}": v for k, v in sqrt_bands.items()})
        return fvars

    def with_score(self, stats: dict) -> dict:
        """Stats to save, with the scored metric's display name; a program session is scored per segment."""
        if not stats:
            return stats
        if self.program_run.active:
            return {**stats, "score_metric_key": "program",
                    "score_metric_name": self.program_run.name or "Program", "avg_score": None}
        key = stats.get("score_metric_key") or self.drive_key()  # no scored tick yet: what it would score
        return {**stats, "score_metric_key": key, "score_metric_name": self._live_screen.graph.series_name(key)}

    def row_fields(self) -> dict:
        """The running session's row, apart from its stats and ticks, as a checkpoint writes it."""
        return {"user_id": self._ctx.user_id(), "session_name": self.session_name(),
                "custom_formulas": self.custom_formulas_json(),
                "session_program": self.program_run.segments_json(), "engine_version": MetricsEngine.ENGINE_VERSION,
                "started_at": self.manager.started_at or None}

    def session_name(self) -> str:
        """The session's default name: when it started and on which device."""
        started = self.manager.started_at
        return f"{start_stamp(datetime.fromtimestamp(started) if started else datetime.now())} - {self.config.device}"

    def custom_formulas_json(self) -> str:
        """Its formula lines, with which of them the live graph shows and which drives the sound."""
        return self.formulas.session_record(self._live_screen.graph.is_visible, self.config.metric)

    # ---- what the main thread may ask ----

    def live(self) -> bool:
        """It runs or is paused, or its start waits for the headset: the window in which a restore or its profile's
        delete would drop or orphan it (the state alone misses the wait)."""
        return self.manager.state in (SessionState.RUNNING, SessionState.PAUSED) or self.connecting()

    def connecting(self) -> bool:
        """The BT wait: the reader is up and the first data will start the session."""
        run = self.run
        return run is not None and run.phase is Phase.CONNECTING

    def running_id(self) -> int | None:
        """The running session's row, which History lists and Settings counts only once it ends."""
        return self.recorder.session_id if self.live() else None

    def checkpoint_or_report(self) -> None:
        """Checkpoint a running session where a failure must not stop what follows (leaving the app, a backup)."""
        try:
            self.recorder.checkpoint()
        except Exception as exc:  # noqa: BLE001 - logged and reported; what follows (a leave, a backup) goes on
            logger.exception("Session checkpoint failed")
            report_soft_error("session_checkpoint_failed", f"The running session could not be saved: {exc}")

    # ---- what the main thread may change: each a command for the run it was sent for ----

    def toggle_pause(self) -> None:
        self._send(self._toggle_pause, taken=False)

    def stop(self, reason: str = "user", *, saved: bool = False) -> None:
        """End the run and save it. It returns once the runner has taken it (within a second, else the Stop runs here,
        so it works on a stuck runner) and, with `saved`, once it is saved (the app's exit: its database closes next)."""
        self._send(self._finish, reason, "", finished=saved)

    def discard(self) -> None:
        """End the run and delete its data (its profile is deleted); returns once it is deleted."""
        self._send(self._discard, finished=True)

    def abort(self) -> None:
        """End a start that hasn't become a session (a Cancel); returns once its reader is down."""
        self._send(self._abort, finished=True)

    def mark(self) -> None:
        self._send(self._mark, taken=False)

    def set_threshold(self, value: int) -> None:
        self._send(self._set_threshold, value, taken=False)

    def set_formula(self, idx: int, name: str, formula: str) -> None:
        """An edited formula line reaches the running session: Settings allows it for a slot the sound isn't set to."""
        self._send(self._set_formula, idx, name, formula, taken=False)

    def _send(self, handler: Callable, *args, taken: bool = True, finished: bool = False) -> None:
        """The one way into the session's state: queued to the run's own runner while it lives, else run here. With
        `taken` the call waits until the runner takes the command: one it doesn't take within _JOIN_SECONDS means it is
        stuck (a read on the link), so the command runs here, and the run it was for, ended by it, keeps the late runner
        from acting. With `finished` it also waits for the runner to finish it (up to _TAKEN_SECONDS, then says so)."""
        run = self.run
        was_taken, done = threading.Event(), threading.Event()
        with self._runner_lock:
            commands = self._commands if run is not None and self._served is run else None
            if commands is not None:
                commands.put((handler, run, args, was_taken, done))
        if commands is None:  # outside the lock: only this thread starts a runner, and a handler may send in turn
            handler(run, *args)
            return
        if not (taken or finished):
            return
        if not was_taken.wait(_JOIN_SECONDS):
            logger.warning(f"Session runner didn't take {handler.__name__} in {_JOIN_SECONDS:.0f} s: it runs here")
            handler(run, *args)
        elif finished and not done.wait(_TAKEN_SECONDS):
            logger.error(f"Session runner took {handler.__name__} and hasn't finished it in {_TAKEN_SECONDS:.0f} s")

    def _toggle_pause(self, run: SessionRun | None) -> None:
        if self._outlived(run):
            return
        if self.manager.state == SessionState.RUNNING:
            self.manager.pause()
            self._emit(run, Paused())
            logger.info("Session paused")
        elif self.manager.state == SessionState.PAUSED:
            self.manager.resume()
            self._emit(run, Resumed())
            logger.info("Session resumed")

    def _mark(self, run: SessionRun | None) -> None:
        if not self._outlived(run) and self.manager.state == SessionState.RUNNING:
            run.pending_marker = True
            logger.info("Marker placed")

    def _set_threshold(self, run: SessionRun | None, value: int) -> None:
        self.manager.set_threshold(value)  # also what a session waiting for the headset starts with

    def _set_formula(self, run: SessionRun | None, idx: int, name: str, formula: str) -> None:
        self.formulas.assign(idx, name, formula)

    # ---- the runner ----

    def start_running(self) -> None:
        """The run's runner starts: from here it alone writes the session's state, until the run ends."""
        run = self.run
        with self._runner_lock:
            self._commands, self._served = queue.Queue(), run
            self._runner = threading.Thread(target=self._loop, args=(run, self._commands), daemon=True,
                                            name="SessionRunner")
            self._runner.start()

    def _loop(self, run: SessionRun, commands: queue.Queue) -> None:
        """Every UPDATE_FREQUENCY seconds a tick of the run (a BT wait step, or the session's), the commands in between,
        until the run ends or is replaced. It keeps running while the screen is locked, as a Kivy Clock doesn't."""
        interval = APP.UPDATE_FREQUENCY
        next_tick = time.monotonic() + interval
        while not self._outlived(run):
            try:
                handler, sent_for, args, taken, done = commands.get(timeout=max(0.0, next_tick - time.monotonic()))
            except queue.Empty:
                self._guarded(self.tick, run)
                next_tick += interval
                if next_tick <= time.monotonic():  # it overran: the ticks it missed are dropped, never run back to back
                    next_tick = time.monotonic() + interval
                continue
            taken.set()
            try:
                self._guarded(handler, sent_for, *args)
            finally:
                done.set()
        with self._runner_lock:
            if self._runner is threading.current_thread():
                self._runner, self._commands, self._served = None, None, None
        while not commands.empty():  # sent before the run ended
            handler, sent_for, args, taken, done = commands.get_nowait()
            taken.set()
            if run is self.run:  # a late runner's run was dropped or replaced: its threshold isn't the next session's
                self._guarded(handler, sent_for, *args)
            done.set()

    @staticmethod
    def _guarded(fn: Callable, *args) -> None:
        try:
            fn(*args)
        except Exception:  # noqa: BLE001 - one failing step must not end the session's runner
            logger.exception(f"Session runner: {fn.__name__} failed")

    def _outlived(self, run: SessionRun | None) -> bool:
        """The run ended (an ending claimed it), or was dropped or replaced: nothing acts for it."""
        return run is None or run is not self.run or run.phase is Phase.ENDED

    def on_main_for(self, run: SessionRun, fn: Callable[[], object]) -> None:
        """Queue fn for the main thread as part of `run`; it does nothing once that run was dropped or replaced by another
        Start. A run only marked ended still runs it: its ending queues its own finish."""
        self._ctx.on_main(lambda: fn() if self.run is run else None)

    def _emit(self, run: SessionRun, event: object) -> None:
        self.on_main_for(run, lambda: self._on_event(event))

    # ---- a tick ----

    def tick(self, run: SessionRun | None) -> None:
        """The writer, 2 Hz: a step of the run's BT wait or a tick of its running session; Kivy goes through the main
        thread, while audio, metrics and DB writes are thread-safe."""
        if self._outlived(run):
            return
        if run.phase is Phase.CONNECTING:
            self._follow_bt_wait(run)
            return
        if self.manager.state != SessionState.RUNNING:
            return
        ending = self.watch.check(run, self.manager.elapsed_seconds, on_headset=not self.config.mock)
        if ending:
            self._finish(run, *ending)
            return
        self._session_tick(run)

    def _follow_bt_wait(self, run: SessionRun) -> None:
        """One step of the run's BT wait. Its first data starts the session against the threshold in force (it may have
        moved); a give-up ends this run and undoes the start on the main thread."""
        end = self.bt_wait.tick(run)
        if end is None or self._outlived(run):
            return
        if not end.started:
            if not run.mark_ended():
                return
            if end.report:  # a failed connect's copyable diagnostic (cooldown-gated)
                report_soft_error("bt_connect_failed", end.report)
            self.stream.stop()
            self.keep_awake.release()
            self._emit(run, StartFailed(end.message))
            return
        self.manager.start()
        self.timer.start_countdown()
        run.phase = Phase.STARTED
        self._emit(run, Connected())

    def _session_tick(self, run: SessionRun) -> None:
        """The headset's sample, its metrics and score recorded, sounded and shown; the timer may end it."""
        raw_sample = self.stream.read_sample()  # may wait on the reader's lock
        if self._outlived(run):
            return
        base = self.manager.threshold  # read once, so the engine and the pill are given the same value
        metrics = self.engine.process_sample(raw_sample, base)
        self.watch.check_sample(run, raw_sample)
        run.tick_count += 1
        _log_tick(run, raw_sample, metrics)
        self.formulas.evaluate_into(metrics, lambda: self.formula_vars(raw_sample, metrics))
        # Program vs simple is what the session started as, not the Settings toggle (editable mid-session).
        # The drive key is resolved once: the tick scores and sounds the same metric.
        if self.program_run.active:
            self.program_run.tick(metrics, raw_sample)
            drive_key, mark = self.drive_key(), None
        else:
            drive_key = mark = self._score_on_drive_key()
        tick = self._record_tick(run, raw_sample, metrics)
        if tick is None:
            return
        self._audio.update(metrics.get(drive_key, 0), tick.score["score_target"])  # the tick's target: a segment's or the base
        if run.tick_count > 10:
            self._audio.update_sinking(metrics.get("sinking", 0))
            self._audio.update_subtle_distraction(metrics.get("subtle_distraction", 0))
        self.mirror.record(tick)  # kept even while the screen is locked
        self._show_tick(run, tick, mark, base)
        if self.timer.tick(APP.UPDATE_FREQUENCY):  # a pure counter, no UI
            self._finish(run, "timer")
            return
        self.recorder.flush_tick()  # DB opened with check_same_thread=False

    def _score_on_drive_key(self) -> str:
        """A simple session is scored on the metric that drives the feedback sound (#51), so they can't diverge."""
        key = self.drive_key()
        self.manager.set_active_goal(key)
        return key

    def _record_tick(self, run: SessionRun, raw_sample: dict, metrics: dict) -> RecordedTick | None:
        """Record the tick, raw and computed, with a pending marker in its row before a checkpoint can write it; None if
        the session wasn't running when the tick was read."""
        full_record = {**raw_sample, **metrics}
        marked = run.pending_marker
        if marked:
            run.pending_marker = False
            full_record["marker"] = 1
        score = self.recorder.record(metrics, full_record)
        if score is None:  # not part of the session: the marker goes on the next recorded tick
            run.pending_marker |= marked
            return None
        return RecordedTick(metrics, raw_sample, score, marked)

    def _scored_mark(self, run: SessionRun, key: str | None) -> str | None:
        """The scored series for the legend to mark this tick: only on a change, and only while the screen shows (a
        change during a screen lock is picked up by the first tick after it)."""
        if key is None or key == run.scored_key or self.ui_paused:
            return None
        run.scored_key = key
        return key

    def _show_tick(self, run: SessionRun, tick: RecordedTick, mark: str | None, base: float) -> None:
        """Queue the tick's Session screen update for the main thread, unless the screen is locked; the SHAMATHA pill
        crosses at the base threshold."""
        metrics, score = tick.metrics, tick.score
        elapsed_fmt = self.manager.elapsed_formatted
        # Debounced: only the change is dispatched, so the chip can't restyle every tick.
        sham_prev = run.shamatha_active
        run.shamatha_active, run.shamatha_streak = shamatha_transition(
            sham_prev, metrics.get("shamatha_score", 0.0) >= base, run.shamatha_streak)
        sham_changed = run.shamatha_active != sham_prev
        screen = self._live_screen

        def _ui_update(
            m=metrics, rs=tick.raw_sample, ef=elapsed_fmt, mp=tick.marked,
            sa=run.shamatha_active, sc=sham_changed, sk=self._scored_mark(run, mark), tg=score["score_target"],
            on=score["score_key"], live=self.manager.live_score(),
        ) -> None:
            screen.graph.add_point(m, threshold=tg, scored=on)  # its line coloured from this point
            screen.update_stats(live)
            screen.update_state(m.get("state", "Neutral"))
            if sc:
                screen.set_shamatha(sa)
            if sk is not None:
                screen.set_training_series(sk)
            screen.update_timer(ef)
            screen.add_raw_sample(rs)
            if mp:
                screen.graph.add_marker()
                screen.raw_graph.add_marker()
                screen.band_graph.add_marker()

        # N minutes locked at 2 Hz would queue ~120·N full graph redraws, which froze the screen at the unlock.
        if not self.ui_paused:
            self._ctx.on_main(_ui_update)

    # ---- endings: each on the writer, each claims its run first ----

    def _finish(self, run: SessionRun | None, reason: str, alert: str = "") -> None:
        """End the run and save it, once: silenced at once (setVolume, safe on any thread), saved before anything that
        could block (Android may close a locked app before the unlock), its end handed to the main thread (which tears
        the players down: release() on this thread hangs while the main Looper is paused), a timer's gong last."""
        if run is None or run is not self.run or not run.mark_ended():
            return
        self._audio.mute()
        try:
            stats = self.persist(reason)
        except Exception as exc:  # noqa: BLE001 - reported; the run still ends on screen and lets the phone sleep
            logger.exception("Session final save failed")
            report_soft_error("session_save_failed", f"The session could not be saved: {exc}", force=True)
            stats = None
        self._emit(run, Ended(stats, self.recorder.session_id if stats else None, alert))
        if reason == "timer":
            logger.info("Timer expired: the session ended" + (" and is saved" if stats else ""))
            self._audio.play_timer_sound(self.config.gong)  # a MediaPlayer: it rings through the lock

    def persist(self, reason: str) -> dict:
        """Stop the session and write its final stats and ticks; no Kivy, so any thread may run it."""
        stats = self.with_score(self.manager.stop(reason=reason))
        if self.config.mock:  # the headset's link stays up between sessions: a reconnect can wait on it (EBUSY)
            self.stream.stop()
        if stats:
            self.recorder.checkpoint(stats)
        return stats

    def _discard(self, run: SessionRun | None) -> None:
        """End the run and delete its data, a checkpoint's row included (its profile is deleted)."""
        if run is None or run is not self.run or not run.mark_ended():
            return
        self.manager.stop(reason="user")
        if self.config.mock:
            self.stream.stop()
        self.recorder.discard()  # the caller tears the screen down: it waited for this

    def _abort(self, run: SessionRun | None) -> None:
        """End a start in its BT wait (or whose data arrived in the frame of its Cancel): its reader goes down."""
        if run is None or run is not self.run:
            return
        if run.mark_ended():
            self.stream.stop()
            self.keep_awake.release()


def _log_tick(run: SessionRun, raw_sample: dict, metrics: dict) -> None:
    """Log the raw sample and the metrics every 10 ticks (~5s at 2Hz)."""
    if run.tick_count % 10 != 0:
        return
    bands = {k: f"{raw_sample.get(k, 0):.0f}" for k in BAND_KEYS}
    logger.debug(f"Raw sample #{run.tick_count}: {bands}")
    native_med = raw_sample.get("meditation", -1)
    bat = raw_sample.get("battery", -1)
    bat_str = f" bat={bat}/127" if bat >= 0 else ""
    logger.debug(f"Metrics: med={metrics.get('meditation_score', 0):.0f} "
                 f"sham={metrics.get('shamatha_score', 0):.0f} "
                 f"sink={metrics.get('sinking', 0):.0f} "
                 f"dist={metrics.get('distraction', 0):.0f} "
                 f"native_med={native_med:.0f}{bat_str}")
