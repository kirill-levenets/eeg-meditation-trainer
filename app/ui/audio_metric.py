"""Which metric drives the feedback sound: the profile's choice (a metric, or one of the formula slots) as Settings shows
it, a running program's segment over it, and the lock while a simple session is scored on it (#51)."""
from app.logger import logger
from app.metrics.formula_slots import FORMULA_KEYS
from app.session.scoring import baseline_audio_metric
from app.settings.registry import INT, Setting
from app.ui.app_context import AppContext


def _parse_slot(raw: str) -> int:
    return max(0, min(int(raw), len(FORMULA_KEYS) - 1))


class AudioMetric:
    """The profile's metric as Settings shows it and its one change path, refused while a simple session is scored on
    it."""

    def __init__(self, ctx: AppContext, program_run, settings_screen) -> None:
        self._ctx = ctx
        self._program_run = program_run
        self._settings_screen = settings_screen

    def scoring_locked(self, doing: str) -> bool:
        """True (after telling the user) while a simple session runs: it is scored on this metric until it stops. A
        program session is scored on its segments' metrics, so the control stays free."""
        return not self._program_run.active and self._ctx.session.refused(doing)

    def formula_scoring_locked(self, key: str, doing: str) -> bool:
        """True (after telling the user) when the formula slot `key` drives the sound of a simple session running."""
        return key == self._ctx.setting("audio_metric") and self.scoring_locked(doing)

    def show(self) -> None:
        """Settings' metric choice and formula-slot buttons show the metric in force."""
        key = self._ctx.setting("audio_metric")
        self._settings_screen.audio_metric = "custom_formula" if key in FORMULA_KEYS else key
        self._settings_screen.audio_formula_index = self._ctx.setting("audio_formula_index")

    def on_change(self, key: str) -> None:
        """Settings' metric choice: a running session keeps the one it is scored on (a switch mixed both metrics into
        one average and streak)."""
        new_key = FORMULA_KEYS[self._ctx.setting("audio_formula_index")] if key == "custom_formula" else key
        if new_key != self._ctx.setting("audio_metric") and self.scoring_locked("changing the metric it is scored on"):
            self.show()
            return
        self._ctx.change_setting("audio_metric", new_key)
        logger.info(f"Audio threshold metric changed to: {new_key}")

    def on_formula_index(self, idx: int) -> None:
        """Settings' formula slot: it drives the sound only while a formula is the metric chosen; otherwise the choice
        is kept for when one is."""
        idx = max(0, min(idx, len(FORMULA_KEYS) - 1))
        metric = self._ctx.setting("audio_metric")
        if (metric in FORMULA_KEYS and FORMULA_KEYS[idx] != metric
                and self.scoring_locked("changing the metric it is scored on")):
            self.show()
            return
        self._ctx.change_setting("audio_formula_index", idx)
        if metric in FORMULA_KEYS:
            # Load derives the index from audio_metric, so persist both or a reload reverts the switch.
            self._ctx.change_setting("audio_metric", FORMULA_KEYS[idx])

    def settings(self) -> list[Setting]:
        """The metric and its formula slot, the slot first: the metric reconciles it. A stored program slot heals to
        the baseline at load."""
        def apply_metric(v):
            if v in FORMULA_KEYS:
                self._ctx.change_setting("audio_formula_index", FORMULA_KEYS.index(v))
            self.show()

        return [Setting("audio_formula_index", 0, _parse_slot, INT[1], None, lambda _v: None),  # shown with the metric
                Setting("audio_metric", "shamatha_score", baseline_audio_metric, baseline_audio_metric, None,
                        apply_metric)]
