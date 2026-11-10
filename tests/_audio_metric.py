"""An AudioMetric on its own, for the tests of which metric drives the sound."""
from unittest.mock import MagicMock

from app.metrics.formula_slots import FormulaSlots
from app.ui.audio_metric import AudioMetric
from tests._context import stub_context
from tests._program_run import make_run


def audio_metric_alone(metric: str = "shamatha_score", *, program_run=None, formulas=None, **ctx_fields) -> AudioMetric:
    """The profile's stored metric is `metric`; no program running and empty formula slots unless given."""
    settings = {"audio_metric": metric, "audio_formula_index": 0}
    ctx = stub_context(**{"setting": settings.__getitem__, **ctx_fields})
    return AudioMetric(ctx, formulas or FormulaSlots(), program_run or make_run(), MagicMock())
