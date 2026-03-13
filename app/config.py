import os


class SigmoidConfig:
    """Sigmoid normalization parameters for easy calibration."""

    SINKING_K: float = 2.0
    SINKING_MIDPOINT: float = 1.5

    DISTRACTION_K: float = 2.0
    DISTRACTION_MIDPOINT: float = 2.5

    SUBTLE_K: float = 2.0
    SUBTLE_MIDPOINT: float = 0.5

    SHAMATHA_K: float = 2.0
    SHAMATHA_MIDPOINT: float = 1.5


class MetricsConfig:
    """Tunable thresholds and limits for metrics engine."""

    CMAX: float = 4.0
    MEDITATION_SCORE_MAX: float = 200.0

    ROLLING_WINDOW_SIZE: int = 5
    STABILITY_BUFFER_SECONDS: int = 20
    STABILITY_BUFFER_SIZE: int = 40  # 20s * 2Hz

    MEDITATION_THRESHOLD_DEFAULT: int = 50
    STABILITY_LIMIT: float = 30.0
    SINKING_LIMIT: float = 50.0
    DISTRACTION_LIMIT: float = 50.0
    STABILITY_MAX: float = 100.0


class AppConfig:
    """Global application configuration."""

    APP_NAME: str = "EEG Meditation Trainer"
    UPDATE_FREQUENCY: float = 0.5  # 2 Hz = every 0.5 seconds
    GRAPH_WINDOW_SECONDS: int = 300  # 5 minutes
    GRAPH_POINTS_MAX: int = 600  # 5min * 2Hz
    FLUSH_INTERVAL_SECONDS: int = 60
    SIGNAL_BUFFER_SECONDS: int = 120

    DB_NAME: str = "meditation.db"
    DB_PATH: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), DB_NAME)

    MAX_VOLUME: float = 1.0
    WHITE_NOISE_SAMPLE_RATE: int = 22050
    WHITE_NOISE_DURATION: float = 2.0


SIGMOID = SigmoidConfig()
METRICS = MetricsConfig()
APP = AppConfig()
