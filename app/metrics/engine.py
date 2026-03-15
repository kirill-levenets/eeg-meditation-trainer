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

    def compute_calmness(self, norms: Dict[str, float]) -> float:
        """calmness = alpha_norm / (beta_norm + gamma_norm + eps)"""
        return norms["alpha_norm"] / (norms["beta_norm"] + norms["gamma_norm"] + 0.001)

    def compute_meditation_score(self, calmness: float) -> float:
        """Meditation score: clamp(200 * calmness / Cmax) in [0, 200]."""
        raw = METRICS.MEDITATION_SCORE_MAX * calmness / METRICS.CMAX
        return max(0.0, min(METRICS.MEDITATION_SCORE_MAX, raw))

    def compute_sinking(self, norms: Dict[str, float]) -> float:
        """Sinking (dullness): sigmoid of (theta_norm + delta_norm) / (alpha_norm + beta_norm + eps)."""
        raw = (norms["theta_norm"] + norms["delta_norm"]) / (norms["alpha_norm"] + norms["beta_norm"] + 0.001)
        return self.sigmoid(raw, SIGMOID.SINKING_K, SIGMOID.SINKING_MIDPOINT)

    def compute_distraction(self, norms: Dict[str, float]) -> float:
        """Gross distraction: sigmoid of (beta_norm + gamma_norm) / (alpha_norm + eps)."""
        raw = (norms["beta_norm"] + norms["gamma_norm"]) / (norms["alpha_norm"] + 0.001)
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
        self, calmness: float, norms: Dict[str, float], stability: float
    ) -> float:
        """Composite shamatha score combining calmness, clarity, stability."""
        clarity = norms["alpha_norm"] / (norms["theta_norm"] + norms["delta_norm"] + 0.001)
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

    # Minimum total power to consider data valid (suppresses startup noise)
    MIN_TOTAL_POWER: float = 100.0

    def process_sample(self, raw_sample: Dict[str, float]) -> Dict[str, float]:
        """Full pipeline: smooth → derive → normalize → compute all metrics."""
        smoothed = self._rolling_buffer.push_sample(raw_sample)
        bands = self.derive_bands(smoothed)
        norms = self.normalize_bands(bands)

        # Suppress metrics when total power is too low (startup / no signal)
        if norms["total_power"] < self.MIN_TOTAL_POWER:
            self._stability_buffer.push(0.0)
            return {
                "timestamp": raw_sample.get("timestamp", 0.0),
                "alpha_norm": 0.0, "beta_norm": 0.0, "gamma_norm": 0.0,
                "theta_norm": 0.0, "delta_norm": 0.0,
                "meditation_score": 0.0, "distraction": 0.0,
                "subtle_distraction": 0.0, "sinking": 0.0,
                "shamatha_score": 0.0, "stability": 0.0,
                "state": "Neutral", "calmness": 0.0,
            }

        calmness = self.compute_calmness(norms)
        meditation_score = self.compute_meditation_score(calmness)
        self._stability_buffer.push(meditation_score)
        stability = self.compute_stability()

        sinking = self.compute_sinking(norms)
        distraction = self.compute_distraction(norms)
        subtle_distraction = self.compute_subtle_distraction(meditation_score, stability)
        shamatha = self.compute_shamatha(calmness, norms, stability)
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

    # NeuroSky-range test data
    samples = [
        {"label": "Relaxed (high alpha)", "timestamp": 1.0,
         "delta": 11158, "theta": 7860, "alpha1": 70533, "alpha2": 31842,
         "beta1": 9686, "beta2": 12795, "gamma1": 3367, "gamma2": 2396},
        {"label": "Drowsy (high delta)", "timestamp": 2.0,
         "delta": 457157, "theta": 26947, "alpha1": 115888, "alpha2": 26465,
         "beta1": 9854, "beta2": 12525, "gamma1": 2678, "gamma2": 4579},
        {"label": "Balanced", "timestamp": 3.0,
         "delta": 32271, "theta": 17149, "alpha1": 29861, "alpha2": 24108,
         "beta1": 12103, "beta2": 6182, "gamma1": 6435, "gamma2": 3383},
        {"label": "Startup (near-zero)", "timestamp": 0.5,
         "delta": 33, "theta": 1, "alpha1": 1, "alpha2": 3,
         "beta1": 1, "beta2": 0, "gamma1": 0, "gamma2": 1},
    ]

    for s in samples:
        label = s.pop("label")
        result = engine.process_sample(s)
        print(f"\n  {label}:")
        print(f"    med={result['meditation_score']:.0f} sham={result['shamatha_score']:.0f} "
              f"sink={result['sinking']:.0f} dist={result['distraction']:.0f} "
              f"state={result['state']}")
    engine.reset()

    print("\nSigmoid tests:")
    print(f"  sigmoid(0, 4, 1.0) = {MetricsEngine.sigmoid(0, 4, 1.0):.2f}")
    print(f"  sigmoid(1.0, 4, 1.0) = {MetricsEngine.sigmoid(1.0, 4, 1.0):.2f}")
    print(f"  sigmoid(3.0, 4, 1.0) = {MetricsEngine.sigmoid(3.0, 4, 1.0):.2f}")
