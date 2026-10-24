"""Headless session-program model: ordered timed segments with per-segment
target + driving formula. Pure logic (no Kivy), mirrors timer_state.py."""

from typing import NamedTuple

from app.metrics.custom_formula import CustomFormulaEvaluator, compile_formula


def _minutes(seg: dict) -> int:
    return max(1, int(seg.get("minutes", 0)))


def segment_target(seg: dict) -> int:
    """The target a segment is scored against: a whole number, 50 when it has none or none that reads."""
    try:
        return int(float(seg.get("target", 50)))
    except (TypeError, ValueError):
        return 50


# Segment dict: {minutes:int, target:int, formula:str|{"name","formula"},
# end_sound:str|None, feedback_sound:str|None}
class SessionProgram:
    """An ordered list of timed segments driving per-segment target + formula."""

    def __init__(self, segments) -> None:
        self._segments = [
            s for s in (segments or [])
            if isinstance(s, dict) and int(s.get("minutes", 0)) > 0
        ]

    def __bool__(self) -> bool:
        return bool(self._segments)

    @property
    def segments(self) -> list[dict]:
        return self._segments

    @property
    def total_seconds(self) -> float:
        return sum(_minutes(s) * 60 for s in self._segments)

    def segment_at(self, elapsed_seconds: float) -> tuple[int, dict | None]:
        """(index, segment) active at elapsed; clamps to the last segment past total."""
        if not self._segments:
            return (-1, None)
        for i, end in enumerate(self.boundaries):
            if elapsed_seconds < end:
                return (i, self._segments[i])
        return (len(self._segments) - 1, self._segments[-1])

    @property
    def boundaries(self) -> list[float]:
        out, t = [], 0.0
        for s in self._segments:
            t += _minutes(s) * 60
            out.append(t)
        return out

    def threshold_steps(self, sample_rate: float) -> list[tuple[int, float]]:
        """[(start_tick, target), ...] in tick-index space, for the graph."""
        steps, tick = [], 0
        for s in self._segments:
            steps.append((tick, segment_target(s)))
            tick += int(_minutes(s) * 60 * sample_rate)
        return steps


# Program-driven custom-formula lines: one per distinct custom formula in a program.
PROGRAM_FORMULA_KEYS: tuple[str, ...] = ("program_formula", "program_formula_2", "program_formula_3")


def program_plan(prog: SessionProgram) -> tuple[set[str], list[tuple[str, dict]], list[str]]:
    """Map a program to its series: (program_keys, custom_slots, segment_keys) — the set of series it shows, an ordered
    (slot_key, custom_dict) for each DISTINCT custom formula (capped at PROGRAM_FORMULA_KEYS), and the metric key each
    segment drives (a built-in key or its custom's slot)."""
    builtins: set[str] = set()
    custom_slots: list[tuple[str, dict]] = []
    ident_to_slot: dict[tuple, str] = {}  # (name, formula) -> slot_key
    segment_keys: list[str] = []
    for seg in prog.segments:
        f = seg.get("formula")
        if isinstance(f, dict):
            ident = (f.get("name"), f.get("formula"))
            if ident in ident_to_slot:
                segment_keys.append(ident_to_slot[ident])
            elif len(custom_slots) < len(PROGRAM_FORMULA_KEYS):
                slot = PROGRAM_FORMULA_KEYS[len(custom_slots)]
                custom_slots.append((slot, f))
                ident_to_slot[ident] = slot
                segment_keys.append(slot)
            else:  # > 3 distinct customs (implausible): reuse the last slot
                segment_keys.append(custom_slots[-1][0])
        elif isinstance(f, str) and f:
            builtins.add(f)
            segment_keys.append(f)
        else:
            segment_keys.append("shamatha_score")
    keys = set(builtins) | {s for s, _ in custom_slots}
    return keys, custom_slots, segment_keys


def _compile(customs: list[tuple[str, dict]]) -> dict[str, CustomFormulaEvaluator]:
    """One evaluator per custom formula that compiles, by its series slot, to run on every tick from the start."""
    compiled = {slot: compile_formula(custom.get("formula", "") or "")[0] for slot, custom in customs}
    return {slot: ev for slot, ev in compiled.items() if ev is not None}


class RunnablePlan(NamedTuple):
    keys: set[str]  # the series the program shows
    customs: list[tuple[str, dict]]  # (slot, custom) for each custom formula that runs
    segment_keys: list[str]  # the metric each segment drives and is scored on
    planned_keys: list[str]  # program_plan's: a formula that doesn't compile on its own slot, as older builds drove it
    evaluators: dict[str, CustomFormulaEvaluator]  # slot -> evaluator
    unrunnable: list[str]  # the names of custom formulas that don't compile


def runnable_plan(prog: SessionProgram) -> RunnablePlan:
    """`program_plan` as a session runs it: a custom formula that doesn't compile gets no line, and its segments drive
    and show shamatha; a series nothing computes reads 0, constant maximum noise."""
    keys, customs, planned = program_plan(prog)
    evaluators = _compile(customs)
    dead = {slot for slot, _ in customs} - set(evaluators)
    if not dead:
        return RunnablePlan(keys=keys, customs=customs, segment_keys=planned, planned_keys=planned,
                            evaluators=evaluators, unrunnable=[])
    return RunnablePlan(keys=(keys - dead) | {"shamatha_score"},
                        customs=[(slot, c) for slot, c in customs if slot not in dead],
                        segment_keys=["shamatha_score" if k in dead else k for k in planned], planned_keys=planned,
                        evaluators=evaluators,
                        unrunnable=[c.get("name") or c.get("formula", "") for slot, c in customs if slot in dead])
