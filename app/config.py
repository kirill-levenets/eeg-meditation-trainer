import os
import sys


class SigmoidConfig:
    """Sigmoid normalization parameters for easy calibration."""

    SINKING_K: float = 4.0
    SINKING_MIDPOINT: float = 1.0

    DISTRACTION_K: float = 4.0
    DISTRACTION_MIDPOINT: float = 1.0

    SUBTLE_K: float = 2.0
    SUBTLE_MIDPOINT: float = 0.5

    SHAMATHA_K: float = 3.0
    SHAMATHA_MIDPOINT: float = 1.0


class MetricsConfig:
    """Tunable thresholds and limits for metrics engine."""

    CMAX: float = 3.0
    MEDITATION_SCORE_MAX: float = 200.0

    ROLLING_WINDOW_SIZE: int = 5
    STABILITY_BUFFER_SECONDS: int = 20
    STABILITY_BUFFER_SIZE: int = 40  # 20s * 2Hz

    MEDITATION_THRESHOLD_DEFAULT: int = 100
    STABILITY_LIMIT: float = 200.0
    SINKING_LIMIT: float = 50.0
    DISTRACTION_LIMIT: float = 50.0
    STABILITY_MAX: float = 2000.0


class AppConfig:
    """Global application configuration."""

    APP_NAME: str = "EEG Meditation Trainer"
    UPDATE_FREQUENCY: float = 0.5  # 2 Hz = every 0.5 seconds
    GRAPH_WINDOW_SECONDS: int = 300  # 5 minutes
    GRAPH_POINTS_MAX: int = 600  # 5min * 2Hz
    FLUSH_INTERVAL_SECONDS: int = 60
    SIGNAL_BUFFER_SECONDS: int = 120

    DB_NAME: str = "meditation.db"
    _BASE_DIR: str = (
        os.path.dirname(os.path.abspath(sys.executable))
        if getattr(sys, 'frozen', False)
        else os.path.dirname(os.path.dirname(__file__))
    )
    DB_PATH: str = os.path.join(_BASE_DIR, DB_NAME)

    MAX_VOLUME: float = 1.0
    WHITE_NOISE_SAMPLE_RATE: int = 22050
    WHITE_NOISE_DURATION: float = 2.0
    AUDIO_TEST_DURATION: float = 2.0

    SINKING_ALERT_THRESHOLD: float = 60.0
    SINKING_ALERT_COOLDOWN: float = 15.0
    BELL_FREQUENCY: float = 800.0
    BELL_DURATION: float = 0.6

    SUBTLE_ALERT_THRESHOLD: float = 30.0
    SUBTLE_ALERT_COOLDOWN: float = 20.0
    CHIME_FREQUENCY: float = 1200.0
    CHIME_DURATION: float = 0.8

    DISCONNECT_FREQ_LOW: float = 600.0
    DISCONNECT_FREQ_HIGH: float = 900.0
    DISCONNECT_DURATION: float = 0.8
    DISCONNECT_CYCLES: int = 4

    DISCONNECT_ALERT_ENABLED: bool = False
    USE_MOCK_DEVICE: bool = True

    TIMER_ENABLED: bool = False
    TIMER_DEFAULT_MINUTES: int = 20


SIGMOID = SigmoidConfig()
METRICS = MetricsConfig()
APP = AppConfig()
