"""An AudioMetric on its own, for the tests of Settings' metric choice and its lock."""
from unittest.mock import MagicMock

from app.ui.audio_metric import AudioMetric
from tests._context import stub_context
from tests._program_run import make_run


def audio_metric_alone(metric: str = "shamatha_score", *, program_run=None, **ctx_fields) -> AudioMetric:
    """The profile's stored metric is `metric`; no program running unless given."""
    settings = {"audio_metric": metric, "audio_formula_index": 0}
    ctx = stub_context(**{"setting": settings.__getitem__, **ctx_fields})
    return AudioMetric(ctx, program_run or make_run(), MagicMock())
