"""Realistic mock EEG stream with frequency-band signal synthesis.

Generates EEG-like signals by:
1. Picking a brain state (relaxed, focused, drowsy, distracted, deep_calm)
2. For each state epoch (5-10s), generating target frequency band power
   values from physiologically realistic Hz ranges
3. Synthesizing a composite raw EEG signal as sum of sinusoids at
   characteristic frequencies with appropriate amplitudes
4. Smoothly transitioning between states over 3-8s
5. Rotating to a new state after the epoch expires

The output matches the interface of MockEEGStream: read_sample() returns
a dict with delta, theta, alpha1, alpha2, beta1, beta2, gamma1, gamma2,
attention, meditation, and timestamp.
"""
import math
import random
import time
from typing import Dict, List, Tuple

from app.logger import logger


# Frequency ranges (Hz) for each EEG band
BAND_FREQ_RANGES: Dict[str, Tuple[float, float]] = {
    "delta": (0.5, 4.0),
    "theta": (4.0, 8.0),
    "alpha1": (8.0, 10.0),
    "alpha2": (10.0, 12.0),
    "beta1": (12.0, 20.0),
    "beta2": (20.0, 30.0),
    "gamma1": (30.0, 50.0),
    "gamma2": (50.0, 70.0),
}

# Base power (µV²-like) per band at rest
BASE_POWER: Dict[str, float] = {
    "delta": 280.0,
    "theta": 180.0,
    "alpha1": 350.0,
    "alpha2": 300.0,
    "beta1": 120.0,
    "beta2": 90.0,
    "gamma1": 40.0,
    "gamma2": 30.0,
}


class BrainStateV2:
    """Brain state definitions with power multipliers per band.

    Each state is (name, multipliers_dict, typical_duration_seconds).
    Multipliers scale the BASE_POWER for each band.
    """

    STATES: List[Tuple[str, Dict[str, float], float]] = [
        ("relaxed", {
            "delta": 0.6, "theta": 0.8, "alpha1": 1.4, "alpha2": 1.3,
            "beta1": 0.4, "beta2": 0.3, "gamma1": 0.2, "gamma2": 0.15,
        }, 8.0),
        ("focused", {
            "delta": 0.3, "theta": 0.5, "alpha1": 0.7, "alpha2": 0.6,
            "beta1": 1.3, "beta2": 1.2, "gamma1": 0.8, "gamma2": 0.6,
        }, 7.0),
        ("drowsy", {
            "delta": 1.5, "theta": 1.4, "alpha1": 0.5, "alpha2": 0.4,
            "beta1": 0.2, "beta2": 0.15, "gamma1": 0.1, "gamma2": 0.08,
        }, 6.0),
        ("distracted", {
            "delta": 0.4, "theta": 0.6, "alpha1": 0.3, "alpha2": 0.25,
            "beta1": 1.5, "beta2": 1.4, "gamma1": 1.2, "gamma2": 1.0,
        }, 5.0),
        ("deep_calm", {
            "delta": 0.8, "theta": 1.2, "alpha1": 1.6, "alpha2": 1.5,
            "beta1": 0.2, "beta2": 0.15, "gamma1": 0.1, "gamma2": 0.08,
        }, 9.0),
    ]


class MockEEGStream:
    """Generates simulated EEG with frequency-based synthesis.

    Each epoch (5-10s):
    - A brain state is selected
    - Per-band dominant frequencies are randomly picked from that
      band's Hz range
    - Band power = BASE_POWER * state_multiplier * oscillation_envelope
    - Cross-band interactions model real EEG coupling
    - Smooth hermite transitions between states
    """

    def __init__(self) -> None:
        self._running: bool = False
        self._start_time: float = 0.0
        self._sample_count: int = 0

        # State machine
        self._current_state_idx: int = 0
        self._state_timer: float = 0.0
        self._state_duration: float = 8.0
        self._prev_multipliers: Dict[str, float] = {}
        self._curr_multipliers: Dict[str, float] = {}
        self._transition_progress: float = 1.0
        self._transition_duration: float = 5.0

        # Per-band synthesized frequencies (picked each epoch)
        self._band_frequencies: Dict[str, float] = {}
        self._band_phases: Dict[str, float] = {}

        self._init_state()

    def _init_state(self) -> None:
        """Pick a random starting state and generate initial frequencies."""
        self._current_state_idx = random.randint(0, len(BrainStateV2.STATES) - 1)
        name, mults, dur = BrainStateV2.STATES[self._current_state_idx]
        self._curr_multipliers = dict(mults)
        self._prev_multipliers = dict(mults)
        self._state_duration = dur + random.uniform(-2, 2)
        self._state_timer = 0.0
        self._transition_progress = 1.0
        self._regenerate_frequencies()
        logger.debug(f"MockEEG init state: {name}, duration={self._state_duration:.1f}s")

    def _regenerate_frequencies(self) -> None:
        """Pick a new dominant frequency within each band's Hz range."""
        for band, (lo, hi) in BAND_FREQ_RANGES.items():
            self._band_frequencies[band] = random.uniform(lo, hi)
            self._band_phases[band] = random.uniform(0, 2 * math.pi)

    def start(self) -> None:
        self._running = True
        self._start_time = time.time()
        self._sample_count = 0
        self._state_timer = 0.0
        self._init_state()
        logger.debug("MockEEG stream started")

    def stop(self) -> None:
        self._running = False
        logger.debug("MockEEG stream stopped")

    @property
    def is_connected(self) -> bool:
        return self._running

    def _advance_state(self, dt: float) -> None:
        """Advance brain state machine, trigger transitions."""
        self._state_timer += dt

        if self._transition_progress < 1.0:
            self._transition_progress = min(
                1.0, self._transition_progress + dt / self._transition_duration
            )

        if self._state_timer >= self._state_duration:
            self._state_timer = 0.0
            self._prev_multipliers = self._get_effective_multipliers()

            # Weighted next state: prefer neighbors
            n_states = len(BrainStateV2.STATES)
            weights = [1.0] * n_states
            curr = self._current_state_idx
            for i in range(n_states):
                dist = abs(i - curr)
                if dist == 0:
                    weights[i] = 0.3
                elif dist == 1:
                    weights[i] = 2.0
                else:
                    weights[i] = 0.5

            total = sum(weights)
            r = random.uniform(0, total)
            cumulative = 0.0
            for i, w in enumerate(weights):
                cumulative += w
                if r <= cumulative:
                    self._current_state_idx = i
                    break

            name, mults, dur = BrainStateV2.STATES[self._current_state_idx]
            self._curr_multipliers = dict(mults)
            self._state_duration = dur + random.uniform(-2, 3)
            self._transition_progress = 0.0
            self._transition_duration = random.uniform(3.0, 8.0)
            self._regenerate_frequencies()
            logger.debug(f"MockEEG state → {name}, dur={self._state_duration:.1f}s")

    def _get_effective_multipliers(self) -> Dict[str, float]:
        """Interpolate between previous and current state multipliers."""
        p = self._smooth_step(self._transition_progress)
        result = {}
        for key in BASE_POWER:
            prev = self._prev_multipliers.get(key, 1.0)
            curr = self._curr_multipliers.get(key, 1.0)
            result[key] = prev + (curr - prev) * p
        return result

    @staticmethod
    def _smooth_step(t: float) -> float:
        """Hermite smooth interpolation."""
        t = max(0.0, min(1.0, t))
        return t * t * (3.0 - 2.0 * t)

    def read_sample(self) -> Dict[str, float]:
        """Generate a single mock EEG sample with frequency-based synthesis."""
        t = time.time() - self._start_time if self._running else 0.0
        self._sample_count += 1

        self._advance_state(0.5)

        multipliers = self._get_effective_multipliers()
        sample: Dict[str, float] = {"timestamp": t}

        for band in BASE_POWER:
            base = BASE_POWER[band]
            mult = multipliers[band]
            freq = self._band_frequencies.get(band, 5.0)
            phase = self._band_phases.get(band, 0.0)

            # Sinusoidal oscillation at the band's dominant frequency
            # plus a harmonic for realism
            osc = (
                0.6 * math.sin(2 * math.pi * freq * t + phase)
                + 0.25 * math.sin(2 * math.pi * freq * 1.5 * t + phase * 1.3)
                + 0.15 * math.sin(2 * math.pi * freq * 0.5 * t + phase * 0.7)
            )
            # Envelope: base oscillation maps to [0.5, 1.5] range
            envelope = 1.0 + 0.5 * osc

            # Cross-band interaction: alpha suppressed by high beta
            if band.startswith("alpha"):
                beta_mult = (multipliers.get("beta1", 1.0) + multipliers.get("beta2", 1.0)) / 2
                if beta_mult > 1.0:
                    mult *= max(0.3, 1.0 - (beta_mult - 1.0) * 0.4)

            # Delta/theta boosted when alpha is low (drowsiness)
            if band in ("delta", "theta"):
                alpha_mult = (multipliers.get("alpha1", 1.0) + multipliers.get("alpha2", 1.0)) / 2
                if alpha_mult < 0.6:
                    mult *= 1.0 + (0.6 - alpha_mult) * 0.5

            # Band-specific noise (Gaussian)
            noise_std = base * 0.12
            value = base * mult * envelope + random.gauss(0, noise_std)

            # Occasional burst (5% chance, smaller than before)
            if random.random() < 0.05:
                value += random.uniform(0.5, 1.2) * base * 0.2

            sample[band] = max(0.0, value)

        # Derived attention/meditation from band ratios
        alpha_power = sample.get("alpha1", 0) + sample.get("alpha2", 0)
        beta_power = sample.get("beta1", 0) + sample.get("beta2", 0)
        theta_power = sample.get("theta", 0)
        total = alpha_power + beta_power + theta_power + 1.0

        attention = min(100, max(0, int(60 * beta_power / total + random.gauss(0, 5))))
        meditation = min(100, max(0, int(70 * alpha_power / total + random.gauss(0, 5))))

        sample["attention"] = float(attention)
        sample["meditation"] = float(meditation)
        return sample


if __name__ == "__main__":
    stream = MockEEGStream()
    stream.start()
    print("Frequency-synthesized EEG — 20 samples:")
    print(f"{'t':>5} {'delta':>7} {'theta':>7} {'alpha1':>7} {'alpha2':>7} "
          f"{'beta1':>7} {'beta2':>7} {'gamma1':>7} {'gamma2':>7} {'att':>4} {'med':>4}")
    for i in range(20):
        s = stream.read_sample()
        print(f"{s['timestamp']:5.1f} {s['delta']:7.0f} {s['theta']:7.0f} "
              f"{s['alpha1']:7.0f} {s['alpha2']:7.0f} {s['beta1']:7.0f} "
              f"{s['beta2']:7.0f} {s['gamma1']:7.0f} {s['gamma2']:7.0f} "
              f"{s['attention']:4.0f} {s['meditation']:4.0f}")
        time.sleep(0.1)
    stream.stop()
    print(f"\nConnected after stop: {stream.is_connected}")
