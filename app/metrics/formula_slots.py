"""The three custom formulas a profile keeps in Settings and plots on the live graph, and what a saved session records
of them."""
import json
from collections.abc import Callable

from app.metrics.custom_formula import (
    CustomFormulaEvaluator,
    compile_formula,
    evaluate_series,
)

FORMULA_KEYS: tuple[str, ...] = ("custom_formula", "custom_formula_2", "custom_formula_3")


def default_name(slot: int) -> str:
    return f"Custom {slot + 1}"


class FormulaSlots:
    """One evaluator and one display name per slot; a slot plots as its series key in FORMULA_KEYS."""

    def __init__(self) -> None:
        self.evaluators: list[CustomFormulaEvaluator] = [CustomFormulaEvaluator() for _ in FORMULA_KEYS]
        self.names: list[str] = [default_name(i) for i in range(len(FORMULA_KEYS))]

    def for_key(self, key: str) -> CustomFormulaEvaluator | None:
        """The evaluator plotted as `key`, or None for a series that isn't a slot."""
        return self.evaluators[FORMULA_KEYS.index(key)] if key in FORMULA_KEYS else None

    def load(self, active: list[dict] | None) -> None:
        """Load an active_formulas list into the slots (names + formulas)."""
        active = active or []
        for i, ev in enumerate(self.evaluators):
            entry = active[i] if i < len(active) and isinstance(active[i], dict) else {}
            self.names[i] = entry.get("name") or default_name(i)
            ev.set_formula(entry.get("formula", "") or "")

    def active(self) -> list[dict]:
        """Every slot's name and formula, as the active_formulas setting stores them."""
        return [{"name": name, "formula": ev.formula} for name, ev in zip(self.names, self.evaluators)]

    def first_empty(self) -> int:
        """First slot with no valid formula; slot 0 if all are full."""
        return next((i for i, ev in enumerate(self.evaluators) if not ev.is_valid), 0)

    def evaluate_into(self, metrics: dict, variables: Callable[[], dict[str, float]]) -> None:
        evaluate_series(dict(zip(FORMULA_KEYS, self.evaluators)), metrics, variables)

    def session_record(self, is_visible: Callable[[str], bool], audio_key: str) -> str:
        """JSON of the valid slots, recorded at save for the session detail to replay.

        `slot` is stored explicitly so a sparse set (e.g. only slots 0 and 2) replays
        onto the correct series keys instead of being packed densely and misaligned.
        """
        return json.dumps([
            {"slot": i, "name": self.names[i], "formula": ev.formula, "visible": is_visible(key),
             "drove_audio": audio_key == key}
            for i, (key, ev) in enumerate(zip(FORMULA_KEYS, self.evaluators)) if ev.is_valid
        ])


def read_active(db, user_id: int) -> list[dict]:
    """The profile's active_formulas, else slot 1 seeded from the single formula kept before there were three."""
    active = db.get_user_json_setting(user_id, "active_formulas")
    if isinstance(active, list):
        return active
    legacy = db.get_user_setting(user_id, "custom_formula")
    return [{"name": default_name(0), "formula": legacy}] if legacy else []


def recorded_formulas(session: dict) -> tuple[dict, dict]:
    """The session's recorded formulas (the snapshot active then, not today's edits): ({series key: evaluator} for
    each valid one, {series key: name} for every slot). Parsing only, no DB."""
    cf_raw = session.get("custom_formulas") or ""
    evaluators: dict[str, CustomFormulaEvaluator] = {}
    # Reset every custom key to its default name so a session without a given
    # slot doesn't inherit the previous session's label.
    names: dict[str, str] = {k: default_name(i) for i, k in enumerate(FORMULA_KEYS)}
    if cf_raw:
        try:
            defs = json.loads(cf_raw)
        except (ValueError, TypeError):
            defs = []
        for pos, d in enumerate(defs):
            if not isinstance(d, dict):
                continue
            slot = d.get("slot", pos)  # explicit slot; fall back to position for old records
            if not isinstance(slot, int) or not 0 <= slot < len(FORMULA_KEYS):
                continue
            key = FORMULA_KEYS[slot]
            ev, _ = compile_formula(d.get("formula", "") or "")
            if ev is not None:
                evaluators[key] = ev
                names[key] = d.get("name") or default_name(slot)
    return evaluators, names
