import math
from collections import deque

from app.config import METRICS, SIGMOID
from app.eeg.buffer import RollingBuffer, VarianceBuffer


class MetricsEngine:
    """Computes all EEG meditation metrics from smoothed band data."""

    # Stamped on each saved session so stored values stay attributable to the formula set
    # that produced them. 1 = sigmoid distraction/sinking (initial rewrite); 2 = ported
    # original Vernihor distraction/sinking. Bump when a built-in formula changes.
    ENGINE_VERSION: str = "2"

    # Vernihor shamatha formula coefficients (Windows variant)
    # Source: scriptures.ru/yoga/eeg_voprosy_i_otvety.htm#formula2
    # 100 * (avg((a1 + 0.8*a2) / (b2 + b1 + 0.4*t + 0.08*d), 4) * 0.75 - 0.3)
    # Windows version uses offset 0.3 (confirmed by data fitting, MSE=28 vs MSE=487 for 0.1)
    _MED_A2_WEIGHT: float = 0.8
    _MED_THETA_WEIGHT: float = 0.4
    _MED_DELTA_WEIGHT: float = 0.08
    _MED_SCALE: float = 0.75
    # Original split its -30 as a per-sample -10 (survives the 4-average) plus a final -20.
    # s_prime (pre-final-offset) is what the distraction/sinking modulation reads.
    _MED_PER_SAMPLE_OFFSET: float = 10.0
    _MED_FINAL_OFFSET: float = 20.0
    _MED_AVG_WINDOW: int = 4  # 4 unique samples (NeuroSky sends at 1Hz)

    # Distraction / sinking (original Vernihor app); gates use the sqrt-pct-8band 0-100 scale.
    _SHAMATHA_MOD_CEILING: float = 140.0  # both metrics scaled by (140 - s_prime)/100
    _DIST_ALPHA1_GATE: int = 65           # a1p  > 65 -> no distraction
    _SINK_ALPHA1_GATE: int = 65           # a1p >= 65 -> no sinking
    _SINK_ALPHA2_GATE: int = 45           # a2p >= 45 -> no sinking; also the (45 - a2p) intercept
    _SINK_SLOPE: float = 0.26             # sinking = (45 - a2p) / 0.26
    _GAMMA_DAMP_MIN_PCT: int = 10         # gamma damping active when gp >= 10 ...
    _GAMMA_DAMP_RAW_CAP: float = 70000.0  # ... and raw gamma < 70000

    def __init__(self) -> None:
        self._rolling_buffer: RollingBuffer = RollingBuffer(
            window_size=METRICS.ROLLING_WINDOW_SIZE
        )
        self._stability_buffer: VarianceBuffer = VarianceBuffer(
            max_size=METRICS.STABILITY_BUFFER_SIZE
        )
        self._meditation_threshold: int = METRICS.MEDITATION_THRESHOLD_DEFAULT
        self._med_ratio_buffer: deque = deque(maxlen=self._MED_AVG_WINDOW)
        self._ticks_above_threshold: int = 0
        self._recent_med_buffer: deque = deque(maxlen=10)
        self._last_s_prime: float = 0.0

    @property
    def last_s_prime(self) -> float:
        """Shamatha before the final -20 offset and clamp; drives distraction/sinking."""
        return self._last_s_prime

    @property
    def meditation_threshold(self) -> int:
        return self._meditation_threshold

    @meditation_threshold.setter
    def meditation_threshold(self, value: int) -> None:
        self._meditation_threshold = max(0, min(100, value))

    @staticmethod
    def sigmoid(raw: float, k: float, midpoint: float, max_scale: float = 100.0) -> float:
        """Generic sigmoid normalization to [0, max_scale]."""
        return max_scale / (1.0 + math.exp(-k * (raw - midpoint)))

    @staticmethod
    def derive_bands(sample: dict[str, float]) -> dict[str, float]:
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
    def normalize_bands(bands: dict[str, float]) -> dict[str, float]:
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

    def compute_calmness(self, norms: dict[str, float]) -> float:
        """calmness = alpha_norm / (beta_norm + gamma_norm + eps)"""
        return norms["alpha_norm"] / (norms["beta_norm"] + norms["gamma_norm"] + 0.001)

    @staticmethod
    def compute_sqrt_relative_bands(
        sample: dict[str, float],
    ) -> dict[str, float]:
        """Compute sqrt-normalized relative band units.

        For each of the 6 bands (delta, theta, alpha1, alpha2, beta1, beta2):
        result = sqrt(abs_value / sum_all_6)
        """
        keys = ("delta", "theta", "alpha1", "alpha2", "beta1", "beta2")
        values = {k: max(sample.get(k, 0.0), 0.0) for k in keys}
        total = sum(values.values())
        if total < 1.0:
            return dict.fromkeys(keys, 0.0)
        return {k: math.sqrt(v / total) for k, v in values.items()}

    _PCT8_BANDS: tuple[str, ...] = (
        "delta", "theta", "alpha1", "alpha2", "beta1", "beta2", "gamma1", "gamma2"
    )
    _PCT8_OUT: tuple[str, ...] = ("alpha1", "alpha2", "gamma1", "gamma2")

    @classmethod
    def sqrt_pct_8band(cls, sample: dict[str, float]) -> dict[str, int]:
        """8-band sqrt-relative percent the original distraction/sinking gates use.

        round(sqrt(raw_band / P8) * 100), P8 = sum of all 8 raw bands. Integer
        0-100. Half-away-from-zero rounding; values are >=0 so int(x+0.5) matches.
        """
        vals = {k: max(sample.get(k, 0.0), 0.0) for k in cls._PCT8_BANDS}
        p8 = sum(vals.values())
        if p8 <= 0.0:
            return dict.fromkeys(cls._PCT8_OUT, 0)
        return {k: int(math.sqrt(vals[k] / p8) * 100.0 + 0.5) for k in cls._PCT8_OUT}

    def compute_meditation_score(self, bands_sqrt: dict[str, float]) -> float:
        """Vernihor shamatha formula (Windows variant).

        Formula: max(0, avg(ratio, 4) * 0.75 - 0.3) * 100
        Band values are sqrt-normalized relative units.
        The avg window is 4 unique NeuroSky samples (1Hz).
        Duplicate samples (from our 2Hz polling) are skipped.
        """
        a1 = bands_sqrt.get("alpha1", 0.0)
        a2 = bands_sqrt.get("alpha2", 0.0)
        b1 = bands_sqrt.get("beta1", 0.0)
        b2 = bands_sqrt.get("beta2", 0.0)
        t = bands_sqrt.get("theta", 0.0)
        d = bands_sqrt.get("delta", 0.0)

        denom = b2 + b1 + self._MED_THETA_WEIGHT * t + self._MED_DELTA_WEIGHT * d
        if denom < 1e-6:
            ratio = 0.0
        else:
            ratio = (a1 + self._MED_A2_WEIGHT * a2) / denom

        # Skip duplicate samples: only push if ratio changed (NeuroSky 1Hz vs our 2Hz)
        if not self._med_ratio_buffer or abs(ratio - self._med_ratio_buffer[-1]) > 1e-9:
            self._med_ratio_buffer.append(ratio)

        avg_ratio = sum(self._med_ratio_buffer) / len(self._med_ratio_buffer)

        s_prime = avg_ratio * self._MED_SCALE * 100.0 - self._MED_PER_SAMPLE_OFFSET
        self._last_s_prime = s_prime
        return max(0.0, s_prime - self._MED_FINAL_OFFSET)

    @classmethod
    def _gamma_damp(cls, sinking: float, gamma_pct: int, gamma_raw: float) -> float:
        """Divide sinking by min(gp-9,10)/25 + 1 when gamma is present (original Vernihor app)."""
        if gamma_pct >= cls._GAMMA_DAMP_MIN_PCT and gamma_raw < cls._GAMMA_DAMP_RAW_CAP:
            return sinking / (min(gamma_pct - 9, 10) / 25.0 + 1.0)
        return sinking

    @classmethod
    def reference_sinking(
        cls,
        alpha1_pct: int,
        alpha2_pct: int,
        gamma1_pct: int,
        gamma2_pct: int,
        gamma1_raw: float,
        gamma2_raw: float,
        s_prime: float,
    ) -> float:
        """Sinking from the original Vernihor app.

        Alpha2-deficit driven, gated by alpha dominance + shamatha, then
        gamma-damped. *_pct = round(sqrt(raw/P8)*100); s_prime = pre-(-20) shamatha.
        """
        if (
            s_prime >= cls._SHAMATHA_MOD_CEILING
            or alpha1_pct >= cls._SINK_ALPHA1_GATE
            or alpha2_pct >= cls._SINK_ALPHA2_GATE
        ):
            return 0.0
        s = (cls._SINK_ALPHA2_GATE - alpha2_pct) / cls._SINK_SLOPE
        s = s * (cls._SHAMATHA_MOD_CEILING - s_prime) / 100.0
        s = cls._gamma_damp(s, gamma1_pct, gamma1_raw)
        s = cls._gamma_damp(s, gamma2_pct, gamma2_raw)
        return max(0.0, min(100.0, s))

    @classmethod
    def reference_distraction(
        cls,
        beta1_raw: float,
        beta2_raw: float,
        alpha1_raw: float,
        alpha1_pct: int,
        s_prime: float,
    ) -> float:
        """Distraction from the original Vernihor app.

        Raw beta/alpha ratio, gated by alpha1 dominance, shamatha-modulated.
        alpha1_pct = round(sqrt(alpha1_raw/P8)*100); s_prime = pre-(-20) shamatha.
        """
        if s_prime >= cls._SHAMATHA_MOD_CEILING or alpha1_pct > cls._DIST_ALPHA1_GATE:
            return 0.0
        if alpha1_raw <= 0.0:  # original divides by raw alpha1 (inf -> clamp 100)
            return 100.0
        d = 100.0 * (beta1_raw + beta2_raw) / alpha1_raw
        d = d * (cls._SHAMATHA_MOD_CEILING - s_prime) / 100.0
        return max(0.0, min(100.0, d))

    def compute_stability(self) -> float:
        """Variance of meditation score over last 20 seconds."""
        return self._stability_buffer.variance()

    def compute_subtle_distraction(
        self, meditation_score: float
    ) -> float:
        """Subtle distraction: meditation above threshold but oscillating.

        Only triggers after meditation has been above threshold for at
        least 10 consecutive ticks (5s), preventing false positives during
        ramp-up.  Uses short-window variance (last 10 ticks / 5s) to
        detect recent oscillations rather than the full 20s buffer.
        """
        self._recent_med_buffer.append(meditation_score)
        if meditation_score > self._meditation_threshold:
            self._ticks_above_threshold += 1
        else:
            self._ticks_above_threshold = 0
            return 0.0

        if self._ticks_above_threshold < 10:
            return 0.0

        if len(self._recent_med_buffer) < 2:
            return 0.0
        n = len(self._recent_med_buffer)
        mean = sum(self._recent_med_buffer) / n
        recent_var = sum((x - mean) ** 2 for x in self._recent_med_buffer) / n

        if recent_var < METRICS.STABILITY_LIMIT:
            return 0.0

        capped = min(recent_var, METRICS.STABILITY_MAX)
        raw = capped / METRICS.STABILITY_MAX
        return self.sigmoid(raw, SIGMOID.SUBTLE_K, SIGMOID.SUBTLE_MIDPOINT)

    def compute_shamatha(self, meditation_score: float) -> float:
        """Shamatha score = meditation score (Vernihor no-levelling formula)."""
        return meditation_score

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

    def process_sample(self, raw_sample: dict[str, float]) -> dict[str, float]:
        """Full pipeline: smooth → derive → normalize → compute all metrics."""
        smoothed = self._rolling_buffer.push_sample(raw_sample)
        bands = self.derive_bands(smoothed)
        norms = self.normalize_bands(bands)

        # Suppress metrics when total power is too low (startup / no signal)
        native_attention = raw_sample.get("attention", 0.0)
        native_meditation = raw_sample.get("meditation", 0.0)

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
                "native_attention": native_attention,
                "native_meditation": native_meditation,
            }

        calmness = self.compute_calmness(norms)
        bands_sqrt = self.compute_sqrt_relative_bands(smoothed)
        meditation_score = self.compute_meditation_score(bands_sqrt)
        self._stability_buffer.push(meditation_score)
        stability = self.compute_stability()

        pct8 = self.sqrt_pct_8band(smoothed)
        s_prime = self._last_s_prime  # set by compute_meditation_score above
        sinking = self.reference_sinking(
            pct8["alpha1"], pct8["alpha2"], pct8["gamma1"], pct8["gamma2"],
            smoothed.get("gamma1", 0.0), smoothed.get("gamma2", 0.0), s_prime,
        )
        distraction = self.reference_distraction(
            smoothed.get("beta1", 0.0), smoothed.get("beta2", 0.0),
            smoothed.get("alpha1", 0.0), pct8["alpha1"], s_prime,
        )
        subtle_distraction = self.compute_subtle_distraction(meditation_score)
        shamatha = self.compute_shamatha(meditation_score)
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
            "native_attention": native_attention,
            "native_meditation": native_meditation,
        }

    def reset(self) -> None:
        self._rolling_buffer.reset()
        self._stability_buffer.reset()
        self._med_ratio_buffer.clear()
        self._ticks_above_threshold = 0
        self._recent_med_buffer.clear()
        self._last_s_prime = 0.0


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
        {"label": "Distracted (high beta)", "timestamp": 4.0,
         "delta": 30000, "theta": 20000, "alpha1": 5000, "alpha2": 3000,
         "beta1": 50000, "beta2": 40000, "gamma1": 20000, "gamma2": 15000},
        {"label": "Startup (near-zero)", "timestamp": 0.5,
         "delta": 33, "theta": 1, "alpha1": 1, "alpha2": 3,
         "beta1": 1, "beta2": 0, "gamma1": 0, "gamma2": 1},
    ]

    for s in samples:
        label = s.pop("label")
        engine.reset()
        result = engine.process_sample(s)

