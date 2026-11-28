"""What a graph plots (`GraphKind`), and the app's three kinds, which the Session screen and the session detail both
draw: the metrics, the raw EEG waveform and the band power."""
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.eeg.band_spec import GROUP_NAMES
from app.metrics.series_names import SERIES_NAMES
from app.ui.theme import C
from app.ui.widgets.band_totals import BAND_COLORS, BAND_SCALES


@dataclass(frozen=True)
class GraphKind:
    """What a graph plots and over what: its lines (colour role, scale, name), the seconds it shows at first, its
    sample rate (0: one point per tick), and whether it is centred on zero or scaled to its data."""

    colors: Mapping[str, tuple]
    scales: Mapping[str, float]
    names: Mapping[str, str] = field(default_factory=dict)
    viewport_seconds: int = 60
    sample_rate: float = 0.0
    bipolar: bool = False
    auto_scale: bool = False


METRICS_COLORS = {
    "shamatha_score": C.SHAMATHA,
    "meditation_score": C.MED_SCORE,
    "distraction": C.DISTRACTION,
    "sinking": C.SINKING,
    "subtle_distraction": C.SUBTLE,
    "native_attention": C.ATTENTION,
    "native_meditation": C.MEDITATION,
    "custom_formula": C.CUSTOM,
    "custom_formula_2": C.CUSTOM2,
    "custom_formula_3": C.CUSTOM3,
    # Live lines for a program's custom-formula segments (hidden until a program
    # with custom segments runs); one per distinct custom formula, labels track them.
    "program_formula": C.WARM,
    "program_formula_2": C.WARM2,
    "program_formula_3": C.WARM3,
}

METRICS_SCALES = {
    "shamatha_score": 100.0,
    "meditation_score": 100.0,
    "distraction": 100.0,
    "sinking": 100.0,
    "subtle_distraction": 100.0,
    "native_attention": 100.0,
    "native_meditation": 100.0,
    "custom_formula": 200.0,
    "custom_formula_2": 200.0,
    "custom_formula_3": 200.0,
    "program_formula": 200.0,
    "program_formula_2": 200.0,
    "program_formula_3": 200.0,
}

METRICS = GraphKind(METRICS_COLORS, METRICS_SCALES, SERIES_NAMES)
RAW_EEG = GraphKind({"eeg": C.MEDITATION}, {"eeg": 500.0}, viewport_seconds=10, sample_rate=512.0, bipolar=True)
BAND_POWER = GraphKind(BAND_COLORS, BAND_SCALES, GROUP_NAMES, auto_scale=True)
