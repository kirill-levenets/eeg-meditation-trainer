"""The session's machinery, built once and run by every Start on the config that Start read: its state and score, its
way into the database, the metrics engine, its formula lines, a program, the timer, each tick's checks and what keeps
the phone awake."""
from datetime import datetime

from app.eeg.mock_stream_v2 import MockEEGStream
from app.keep_awake import KeepAwake
from app.metrics.engine import MetricsEngine
from app.metrics.formula_slots import FormulaSlots
from app.session.manager import SessionManager
from app.session.recorder import SessionRecorder
from app.session.session_config import SessionConfig
from app.session.timer_state import TimerState
from app.ui.app_context import AppContext
from app.ui.audio_metric import sound_metric
from app.ui.program_run import ProgramRun
from app.ui.session_labels import start_stamp
from app.ui.session_watch import SessionWatch


class RunningSession:
    """Owns the parts a session runs on and answers what it is scored on and saved as, from its config, never a live
    setting. Its questions are safe on the tick thread: they read state, and touch no Kivy widget beyond a graph's
    series names and visibility."""

    def __init__(self, ctx: AppContext, audio, live_screen, headset) -> None:
        self._ctx = ctx
        self._live_screen = live_screen
        self.config: SessionConfig | None = None  # the last Start's
        self.formulas = FormulaSlots()  # its own lines, built from the config: their avg() windows are the session's
        self.mock_stream = MockEEGStream()
        self.engine = MetricsEngine()
        self.manager = SessionManager()
        self.manager.set_audio(audio)
        self.timer = TimerState()
        self.program_run = ProgramRun(ctx, self.manager, audio, live_screen, formula_vars=self.formula_vars)
        self.recorder = SessionRecorder(ctx.db, self.manager, with_score=self.with_score, row_fields=self.row_fields)
        self.watch = SessionWatch(audio, live_screen, headset, on_main=ctx.on_main)
        self.keep_awake = KeepAwake()  # held from a session's setup to its ending

    def begin(self, config: SessionConfig) -> None:
        """A Start: the session runs on `config` until its next Start, with its lines, timer, engine and record new."""
        self.config = config
        self.formulas = FormulaSlots()
        self.formulas.load(list(config.formulas))
        self.timer.set_enabled(config.timer_minutes is not None)
        self.timer.set_duration(config.timer_minutes or 1)
        self.engine.reset()
        self.recorder.begin()

    def set_formula(self, idx: int, name: str, formula: str) -> None:
        """An edited formula line reaches the running session: Settings allows it for a slot the sound isn't set to."""
        self.formulas.assign(idx, name, formula)

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
