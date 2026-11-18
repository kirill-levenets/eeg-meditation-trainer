"""The program a session runs: its segments step the target, the sound and the trained series as the session crosses
them, and its own lines show on the live graph for the whole session."""
import json
from collections.abc import Callable

from app.logger import logger
from app.metrics.custom_formula import CustomFormulaEvaluator, evaluate_series
from app.session.session_events import (
    Notice,
    ProgramDropped,
    ProgramShown,
    SegmentStarted,
)
from app.session.session_program import (
    PROGRAM_FORMULA_KEYS,
    SessionProgram,
    program_line_name,
    runnable_plan,
    segment_target,
)
from app.session.session_run import SessionRun


class ProgramRun:
    """The program the running session started with; None for a simple session.

    `tick` runs on the session's runner: only thread-safe state there (audio one-shots, SessionManager, pure
    evaluators). What the screen shows goes out as events: `show` on the main thread (its start and end), `emit` from
    the runner, for its run.
    """

    def __init__(self, session_manager, audio, *, show: Callable[[object], None],
                 emit: Callable[[SessionRun, object], None], formula_vars: Callable[[dict, dict], dict]) -> None:
        self._session_manager = session_manager
        self._audio = audio
        self._show = show
        self._emit = emit
        self._formula_vars = formula_vars
        self.program: SessionProgram | None = None
        self.name = ""  # the program's name at the start; Settings may load or save another during the session
        self.audio_key = ""  # the active segment's metric; transient, never written to the user's baseline
        self.formula_evs: dict[str, CustomFormulaEvaluator] = {}  # slot key -> evaluator, one per distinct custom
        self.seg_idx = -1
        self._segment_keys: list[str] = []  # metric key driven by each segment
        self._feedback_ids: list[str] = []  # feedback source of each segment

    @property
    def active(self) -> bool:
        return self.program is not None

    def begin(self, run: SessionRun, prog: SessionProgram | None, feedback_ids: list[str], name: str) -> None:
        """Session start: a simple session (None) runs none. A program shows and marks EXACTLY its metric set on the
        live graph for the whole session, and arms one persistent evaluator per distinct custom formula that
        compiles; one that doesn't runs its segments on shamatha, and a popup names it. Each custom line is shown the
        whole program (not per-segment) and evaluated every tick, so only the legend marker changes as segments
        cross."""
        self.program = prog
        self.name = name if prog is not None else ""
        self.seg_idx = -1
        self.audio_key = ""
        self.formula_evs = {}
        self._segment_keys = []
        self._feedback_ids = feedback_ids
        if prog is None:
            return
        plan = runnable_plan(prog)
        self._show(ProgramShown(plan))
        self._segment_keys, self.formula_evs = plan.segment_keys, plan.evaluators
        if plan.unrunnable:
            logger.warning(f"Program formulas that can't run, their segments use shamatha: {plan.unrunnable}")
            listed = ", ".join(f'"{n}"' for n in plan.unrunnable)
            message = f"Can't run {listed}: Shamatha is used instead.\nSettings › Timer / Program edits the program."
            self._emit(run, Notice("Formula error in this program", message))  # the next frame: the start's setup first

    def end(self) -> None:
        """Drop the program, its custom-formula lines, labels and evaluators, and its mark on the live graph; the
        ending re-derives the graph's idle series (ProgramSettings.refresh_live_series)."""
        self.program = None
        self.name = ""
        self.formula_evs = {}
        self._segment_keys = []
        self._feedback_ids = []
        self.audio_key = ""
        self._show(ProgramDropped())

    def segments_json(self) -> str:
        """JSON of the program that ran this session (empty for a simple session).

        Serializes the snapshot captured at session start, not the live editor —
        a mid-session edit in Settings must not rewrite what actually drove the run.
        """
        prog = self.program
        return json.dumps(prog.segments) if prog else ""

    @staticmethod
    def transition(prev_idx: int, elapsed: float, program: SessionProgram):
        """Pure: (new_idx, segment, crossed). crossed=True when new_idx != prev_idx."""
        idx, seg = program.segment_at(elapsed)
        return (idx, seg, idx != prev_idx)

    def tick(self, run: SessionRun, metrics: dict, raw_sample: dict) -> None:
        """Per-tick program stepping: cross segments, fire cues, evaluate the program's custom formulas."""
        prog = self.program
        if not prog:
            return
        elapsed = self._session_manager.elapsed_seconds
        idx, seg, crossed = self.transition(self.seg_idx, elapsed, prog)
        if seg is None:
            return
        if crossed:
            self._enter_segment(run, prog, self.seg_idx, idx, seg)
            self.seg_idx = idx
        # Every program custom line is evaluated every tick (persistent, shown the whole
        # program) into its own metrics[slot] — so all stages' lines stay live at once.
        evaluate_series(self.formula_evs, metrics, lambda: self._formula_vars(raw_sample, metrics))

    def _enter_segment(self, run: SessionRun, prog: SessionProgram, prev_idx: int, idx: int, seg: dict) -> None:
        """On a boundary crossing: end-cue for the prior segment + repoint target/audio/marker
        to this segment's metric (built-in key or its custom's persistent program line)."""
        # End cue for the segment that just ended (skip on initial entry prev_idx == -1).
        if prev_idx >= 0:
            self._play_end_cue(prog.segments[prev_idx].get("end_sound"))
        metric_key = self._segment_keys[idx]
        formula = seg.get("formula")
        line_name = None
        if isinstance(formula, dict) and metric_key in PROGRAM_FORMULA_KEYS:
            line_name = program_line_name(formula)
        target = segment_target(seg)
        self.audio_key = metric_key
        self._session_manager.start_segment(metric_key, target)  # the sound follows the tick's target from here
        if 0 <= idx < len(self._feedback_ids):
            self._audio.set_active_feedback(self._feedback_ids[idx])
        self._emit(run, SegmentStarted(metric_key, line_name))
        logger.info(f"Program segment {idx}: metric={metric_key} target={target}")

    def _play_end_cue(self, sound_id) -> None:
        """Segment-end cue. v1: chime (default) or 'warble'; richer choices land with #10."""
        try:
            if sound_id == "warble":
                self._audio.play_alert()
            else:
                self._audio.play_transition_cue()
        except Exception:  # noqa: BLE001 - on the runner a failed cue must not end the session
            logger.exception("Program segment end cue failed")
