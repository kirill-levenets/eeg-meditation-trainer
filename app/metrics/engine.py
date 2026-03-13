import math
from typing import Dict

from app.config import METRICS, SIGMOID
from app.eeg.buffer import RollingBuffer, VarianceBuffer


class MetricsEngine:
    """Computes all EEG meditation metrics from smoothed band data."""

    def __init__(self) -> None:
        self._rolling_buffer: RollingBuffer = RollingBuffer(
            window_size=METRICS.ROLLING_WINDOW_SIZE
        )
        self._stability_buffer: VarianceBuffer = VarianceBuffer(
            max_size=METRICS.STABILITY_BUFFER_SIZE
        )
        self._meditation_threshold: int = METRICS.MEDITATION_THRESHOLD_DEFAULT

    @property
    def meditation_threshold(self) -> int:
        return self._meditation_threshold

    @meditation_threshold.setter
    def meditation_threshold(self, value: int) -> None:
        self._meditation_threshold = max(0, min(200, value))

    @staticmethod
    def sigmoid(raw: float, k: float, midpoint: float, max_scale: float = 100.0) -> float:
        """Generic sigmoid normalization to [0, max_scale]."""
        return max_scale / (1.0 + math.exp(-k * (raw - midpoint)))

    @staticmethod
    def derive_bands(sample: Dict[str, float]) -> Dict[str, float]:
        """Compute derived bands: alpha, beta, gamma from sub-bands."""
        alpha = sample.get("alpha1", 0.0) + sample.get("alpha2", 0.0)
        beta = sample.get("beta1", 0.0) + sample.get("beta2", 0.0)
        gamma = sample.get("gamma1", 0.0) + sample.get("gamma2", 0.0)
        return {
            "alpha": alpha,
            "beta": beta,
            "gamma": gamma,
            "theta": sample.get("theta", 0.0),
            "delta": sample.get("delta", 0.0),
        }

    @staticmethod
    def normalize_bands(bands: Dict[str, float]) -> Dict[str, float]:
        """Normalize bands by total power."""
        total_power = (
            bands["alpha"]
            + bands["beta"]
            + bands["gamma"]
            + bands["theta"]
            + bands["delta"]
            + 1.0
        )
        return {
            "alpha_norm": bands["alpha"] / total_power,
            "beta_norm": bands["beta"] / total_power,
            "gamma_norm": bands["gamma"] / total_power,
            "theta_norm": bands["theta"] / total_power,
            "delta_norm": bands["delta"] / total_power,
            "total_power": total_power,
        }

    def compute_calmness(self, bands: Dict[str, float]) -> float:
        """calmness = alpha / (beta + gamma + 1)"""
        return bands["alpha"] / (bands["beta"] + bands["gamma"] + 1.0)

    def compute_meditation_score(self, calmness: float) -> float:
        """Meditation score: clamp(200 * calmness / Cmax) in [0, 200]."""
        raw = METRICS.MEDITATION_SCORE_MAX * calmness / METRICS.CMAX
        return max(0.0, min(METRICS.MEDITATION_SCORE_MAX, raw))

    def compute_sinking(self, bands: Dict[str, float]) -> float:
        """Sinking (dullness): sigmoid of (theta + delta) / (alpha + beta + 1)."""
        raw = (bands["theta"] + bands["delta"]) / (bands["alpha"] + bands["beta"] + 1.0)
        return self.sigmoid(raw, SIGMOID.SINKING_K, SIGMOID.SINKING_MIDPOINT)

    def compute_distraction(self, bands: Dict[str, float]) -> float:
        """Gross distraction: sigmoid of (beta + gamma) / (alpha + 1)."""
        raw = (bands["beta"] + bands["gamma"]) / (bands["alpha"] + 1.0)
        return self.sigmoid(raw, SIGMOID.DISTRACTION_K, SIGMOID.DISTRACTION_MIDPOINT)

    def compute_stability(self) -> float:
        """Variance of meditation score over last 20 seconds."""
        return self._stability_buffer.variance()

    def compute_subtle_distraction(
        self, meditation_score: float, stability: float
    ) -> float:
        """Subtle distraction: high meditation but unstable."""
        if (
            meditation_score > self._meditation_threshold
            and stability > METRICS.STABILITY_LIMIT
        ):
            raw = stability / METRICS.STABILITY_MAX
            return self.sigmoid(raw, SIGMOID.SUBTLE_K, SIGMOID.SUBTLE_MIDPOINT)
        return 0.0

    def compute_shamatha(
        self, calmness: float, bands: Dict[str, float], stability: float
    ) -> float:
        """Composite shamatha score combining calmness, clarity, stability."""
        clarity = bands["alpha"] / (bands["theta"] + bands["delta"] + 1.0)
        stability_factor = 1.0 / (1.0 + stability)
        shamatha_raw = (calmness * 0.4) + (clarity * 0.3) + (stability_factor * 0.3)
        return self.sigmoid(
            shamatha_raw, SIGMOID.SHAMATHA_K, SIGMOID.SHAMATHA_MIDPOINT
        )

    def classify_state(
        self,
        meditation_score: float,
        stability: float,
        sinking: float,
        distraction: float,
    ) -> str:
        """Classify current meditation state."""
        if (
            meditation_score >= self._meditation_threshold
            and stability < METRICS.STABILITY_LIMIT
            and sinking < METRICS.SINKING_LIMIT
            and distraction < METRICS.DISTRACTION_LIMIT
        ):
            return "Stable Focus"
        if (
            meditation_score >= self._meditation_threshold
            and stability >= METRICS.STABILITY_LIMIT
        ):
            return "Subtle Distraction"
        if distraction >= METRICS.DISTRACTION_LIMIT:
            return "Gross Distraction"
        if sinking >= METRICS.SINKING_LIMIT:
            return "Sinking"
        return "Neutral"

    def process_sample(self, raw_sample: Dict[str, float]) -> Dict[str, float]:
        """Full pipeline: smooth → derive → normalize → compute all metrics."""
        smoothed = self._rolling_buffer.push_sample(raw_sample)
        bands = self.derive_bands(smoothed)
        norms = self.normalize_bands(bands)

        calmness = self.compute_calmness(bands)
        meditation_score = self.compute_meditation_score(calmness)
        self._stability_buffer.push(meditation_score)
        stability = self.compute_stability()

        sinking = self.compute_sinking(bands)
        distraction = self.compute_distraction(bands)
        subtle_distraction = self.compute_subtle_distraction(meditation_score, stability)
        shamatha = self.compute_shamatha(calmness, bands, stability)
        state = self.classify_state(meditation_score, stability, sinking, distraction)

        return {
            "timestamp": raw_sample.get("timestamp", 0.0),
            "alpha_norm": norms["alpha_norm"],
            "beta_norm": norms["beta_norm"],
            "gamma_norm": norms["gamma_norm"],
            "theta_norm": norms["theta_norm"],
            "delta_norm": norms["delta_norm"],
            "meditation_score": meditation_score,
            "distraction": distraction,
            "subtle_distraction": subtle_distraction,
            "sinking": sinking,
            "shamatha_score": shamatha,
            "stability": stability,
            "state": state,
            "calmness": calmness,
        }

    def reset(self) -> None:
        self._rolling_buffer.reset()
        self._stability_buffer.reset()


if __name__ == "__main__":
    engine = MetricsEngine()

    test_sample = {
        "timestamp": 1.0,
        "delta": 300.0,
        "theta": 200.0,
        "alpha1": 500.0,
        "alpha2": 400.0,
        "beta1": 100.0,
        "beta2": 80.0,
        "gamma1": 30.0,
        "gamma2": 20.0,
        "attention": 50,
        "meditation": 60,
    }

    result = engine.process_sample(test_sample)
    for key, val in sorted(result.items()):
        if isinstance(val, float):
            print(f"  {key}: {val:.4f}")
        else:
            print(f"  {key}: {val}")

    print("\nSigmoid tests:")
    print(f"  sigmoid(0, 2, 1.5) = {MetricsEngine.sigmoid(0, 2, 1.5):.2f}")
    print(f"  sigmoid(1.5, 2, 1.5) = {MetricsEngine.sigmoid(1.5, 2, 1.5):.2f}")
    print(f"  sigmoid(5, 2, 1.5) = {MetricsEngine.sigmoid(5, 2, 1.5):.2f}")
