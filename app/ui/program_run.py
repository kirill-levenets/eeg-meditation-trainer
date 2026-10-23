"""The program a session runs: its segments step the target, the sound and the trained series as the session crosses
them, and its own lines show on the live graph for the whole session."""
import json
from collections.abc import Callable

from app.logger import logger
from app.metrics.custom_formula import CustomFormulaEvaluator, evaluate_series
from app.session.session_program import (
    PROGRAM_FORMULA_KEYS,
    RunnablePlan,
    SessionProgram,
    runnable_plan,
    segment_target,
)
from app.ui.live_session import SERIES_NAMES


def program_line_name(custom: dict) -> str:
    """The live graph's label of a program's custom formula line."""
    name = custom.get("name")
    return f"Program: {name}" if name else "Program"


def show_program_series(graph, plan: RunnablePlan) -> None:
    """Set the graph to EXACTLY the program's metric set and label each program custom line. Shared by a program
    session's start and the idle preview."""
    for slot, custom in plan.customs:
        graph.set_series_name(slot, program_line_name(custom))
    for k in graph.series_keys():
        graph.set_visible(k, k in plan.keys)


class ProgramRun:
    """The program the running session started with; None for a simple session.

    `tick` runs on the daemon tick thread: only thread-safe state there (audio set_threshold/one-shot, SessionManager,
    pure evaluators). Kivy widget changes go through `on_main`.
    """

    def __init__(self, session_manager, audio, live_screen, *, on_main: Callable[[Callable[[], object]], None],
                 formula_vars: Callable[[dict, dict], dict], warn: Callable[[str, str], None]) -> None:
        self._session_manager = session_manager
        self._audio = audio
        self._live_screen = live_screen
        self._on_main = on_main
        self._formula_vars = formula_vars
        self._warn = warn  # (title, message): a popup that stays until read, as the meditator may not be looking
        self.program: SessionProgram | None = None
        self.name = ""  # the program's name at the start; Settings may load or save another during the session
        self.audio_key = ""  # the active segment's metric; transient, never written to the user's baseline
        self.formula_evs: dict[str, CustomFormulaEvaluator] = {}  # slot key -> evaluator, one per distinct custom
        self.seg_idx = -1
        self._segment_keys: list[str] = []  # metric key driven by each segment
        self.unrunnable: list[str] = []  # the program's custom formulas that don't compile: their segments use shamatha
        self._feedback_ids: list[str] = []  # feedback source of each segment
        self._prev_visibility: dict[str, bool] = {}  # live-graph visibility before the program

    @property
    def active(self) -> bool:
        return self.program is not None

    def computes(self, key: str) -> bool:
        """True for a program line the running program evaluates every tick."""
        return self.active and key in self.formula_evs

    def begin(self, prog: SessionProgram | None, feedback_ids: list[str], name: str) -> None:
        """Session start: a simple session (None) runs none. A program snapshots the graph's visibility, shows EXACTLY
        its metric set for the whole session, and arms one persistent evaluator per distinct custom formula. Each custom
        line is shown the whole program (not per-segment) and evaluated every tick, so only the legend marker changes
        as segments cross."""
        self.program = prog
        self.name = name if prog is not None else ""
        self.seg_idx = -1
        self.audio_key = ""
        self.formula_evs = {}
        self._segment_keys = []
        self.unrunnable = []
        self._feedback_ids = feedback_ids
        if prog is None:
            return
        graph = self._live_screen.graph
        # Snapshot every catalog key's visibility so stop restores exactly.
        self._prev_visibility = {k: graph.is_visible(k) for k in graph.series_keys()}
        plan = runnable_plan(prog)
        show_program_series(graph, plan)
        self._segment_keys, self.formula_evs, self.unrunnable = plan.segment_keys, plan.evaluators, plan.unrunnable
        if self.unrunnable:
            logger.warning(f"Program formulas that can't run, their segments use shamatha: {self.unrunnable}")
            listed = ", ".join(f'"{name}"' for name in self.unrunnable)
            self._warn("Formula error in this program", f"Can't run {listed}: Shamatha is used instead.\n"
                                                        "Settings › Timer / Program edits the program.")

    def end(self) -> None:
        """Restore the live graph to its pre-program visibility and drop the program custom-formula
        lines/labels/evaluators."""
        graph = self._live_screen.graph
        for slot in PROGRAM_FORMULA_KEYS:
            graph.set_series_name(slot, SERIES_NAMES.get(slot, "Program"))  # drop stale labels
        self.program = None
        self.name = ""
        self.formula_evs = {}
        self._segment_keys = []
        self.unrunnable = []
        self._feedback_ids = []
        self.audio_key = ""
        prev = self._prev_visibility or dict.fromkeys(PROGRAM_FORMULA_KEYS, False)
        for k, on in prev.items():
            graph.set_visible(k, on)
        for slot in PROGRAM_FORMULA_KEYS:
            graph.set_visible(slot, False)  # never linger as a user selection
        self._prev_visibility = {}

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

    def tick(self, metrics: dict, raw_sample: dict) -> None:
        """Per-tick program stepping: cross segments, fire cues, evaluate the program's custom formulas."""
        prog = self.program
        if not prog:
            return
        elapsed = self._session_manager.elapsed_seconds
        idx, seg, crossed = self.transition(self.seg_idx, elapsed, prog)
        if seg is None:
            return
        if crossed:
            self._enter_segment(prog, self.seg_idx, idx, seg)
            self.seg_idx = idx
        # Every program custom line is evaluated every tick (persistent, shown the whole
        # program) into its own metrics[slot] — so all stages' lines stay live at once.
        evaluate_series(self.formula_evs, metrics, lambda: self._formula_vars(raw_sample, metrics))

    def _enter_segment(self, prog: SessionProgram, prev_idx: int, idx: int, seg: dict) -> None:
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
        self._session_manager.set_active_goal(metric_key, target)
        self._audio.set_threshold(target)
        if 0 <= idx < len(self._feedback_ids):
            self._audio.set_active_feedback(self._feedback_ids[idx])
        self._on_main(lambda k=metric_key, nm=line_name: self._segment_ui(k, nm))
        logger.info(f"Program segment {idx}: metric={metric_key} target={target}")

    def _segment_ui(self, metric_key: str, line_name: str | None) -> None:
        """Main-thread UI for a segment switch: ensure a custom segment's line is labelled
        + visible, and move the legend marker (the ticks step the threshold line). Program lines'
        visibility is owned by `begin` (shown the whole program), so a
        built-in segment no longer hides anything — only the » marker moves."""
        graph = self._live_screen.graph
        if line_name is not None:
            graph.set_series_name(metric_key, line_name)
            graph.set_visible(metric_key, True)
        self._live_screen.set_training_series(metric_key)  # bold + » on the trained series

    def _play_end_cue(self, sound_id) -> None:
        """Segment-end cue. v1: chime (default) or 'warble'; richer choices land with #10."""
        try:
            if sound_id == "warble":
                self._audio.play_alert()
            else:
                self._audio.play_transition_cue()
        except Exception:  # noqa: BLE001 - on the tick thread a failed cue must not end the session
            logger.exception("Program segment end cue failed")
