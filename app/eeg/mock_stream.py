import math
import random
import time
from typing import Dict, List, Tuple


class BrainState:
    """Defines amplitude multipliers for each frequency band per brain state.

    Real EEG patterns:
    - Relaxed/meditation: high alpha, moderate theta, low beta
    - Focused attention: high beta, low-mid alpha, low theta
    - Drowsy/sinking: high theta + delta, suppressed alpha/beta
    - Distracted/anxious: high beta + gamma, suppressed alpha
    - Deep calm: high alpha + theta, very low beta/gamma
    """

    STATES: List[Tuple[str, Dict[str, float], float]] = [
        ("relaxed", {
            "delta": 0.6, "theta": 0.8, "alpha1": 1.4, "alpha2": 1.3,
            "beta1": 0.4, "beta2": 0.3, "gamma1": 0.2, "gamma2": 0.15,
        }, 30.0),
        ("focused", {
            "delta": 0.3, "theta": 0.5, "alpha1": 0.7, "alpha2": 0.6,
            "beta1": 1.3, "beta2": 1.2, "gamma1": 0.8, "gamma2": 0.6,
        }, 20.0),
        ("drowsy", {
            "delta": 1.5, "theta": 1.4, "alpha1": 0.5, "alpha2": 0.4,
            "beta1": 0.2, "beta2": 0.15, "gamma1": 0.1, "gamma2": 0.08,
        }, 25.0),
        ("distracted", {
            "delta": 0.4, "theta": 0.6, "alpha1": 0.3, "alpha2": 0.25,
            "beta1": 1.5, "beta2": 1.4, "gamma1": 1.2, "gamma2": 1.0,
        }, 15.0),
        ("deep_calm", {
            "delta": 0.8, "theta": 1.2, "alpha1": 1.6, "alpha2": 1.5,
            "beta1": 0.2, "beta2": 0.15, "gamma1": 0.1, "gamma2": 0.08,
        }, 35.0),
    ]


class MockEEGStream:
    """Generates simulated EEG data mimicking realistic frequency band activity.

    Simulates brain state transitions (relaxed, focused, drowsy, distracted,
    deep_calm) with smooth interpolation. Each band has its own characteristic
    oscillation frequency, amplitude envelope, and noise profile.
    """

    # Base amplitudes (µV-like) per band — typical resting EEG
    BASE_AMPLITUDES: Dict[str, float] = {
        "delta": 280.0,   # 0.5-4 Hz, high during sleep/drowsiness
        "theta": 180.0,   # 4-8 Hz, meditation/drowsiness
        "alpha1": 350.0,  # 8-10 Hz, relaxation, eyes closed
        "alpha2": 300.0,  # 10-12 Hz, calm alertness
        "beta1": 120.0,   # 12-20 Hz, active thinking
        "beta2": 90.0,    # 20-30 Hz, intense focus
        "gamma1": 40.0,   # 30-50 Hz, cognitive processing
        "gamma2": 30.0,   # 50-70 Hz, high-level cognition
    }

    # Characteristic oscillation rates (Hz) for amplitude modulation
    MODULATION_RATES: Dict[str, float] = {
        "delta": 0.03,
        "theta": 0.06,
        "alpha1": 0.10,
        "alpha2": 0.12,
        "beta1": 0.25,
        "beta2": 0.30,
        "gamma1": 0.45,
        "gamma2": 0.50,
    }

    # Noise standard deviation as fraction of base amplitude
    NOISE_FRACTION: Dict[str, float] = {
        "delta": 0.15,
        "theta": 0.12,
        "alpha1": 0.10,
        "alpha2": 0.10,
        "beta1": 0.18,
        "beta2": 0.20,
        "gamma1": 0.25,
        "gamma2": 0.28,
    }

    def __init__(self) -> None:
        self._running: bool = False
        self._start_time: float = 0.0
        self._current_state_idx: int = 0
        self._state_timer: float = 0.0
        self._state_duration: float = 30.0
        self._prev_multipliers: Dict[str, float] = {}
        self._curr_multipliers: Dict[str, float] = {}
        self._transition_progress: float = 1.0
        self._transition_duration: float = 5.0
        self._phase_offsets: Dict[str, float] = {
            k: random.uniform(0, 2 * math.pi) for k in self.BASE_AMPLITUDES
        }
        self._init_state()

    def _init_state(self) -> None:
        """Initialize with a random starting brain state."""
        self._current_state_idx = random.randint(0, len(BrainState.STATES) - 1)
        state_name, mults, dur = BrainState.STATES[self._current_state_idx]
        self._curr_multipliers = dict(mults)
        self._prev_multipliers = dict(mults)
        self._state_duration = dur + random.uniform(-5, 5)
        self._state_timer = 0.0
        self._transition_progress = 1.0

    def start(self) -> None:
        self._running = True
        self._start_time = time.time()
        self._state_timer = 0.0
        self._init_state()

    def stop(self) -> None:
        self._running = False

    @property
    def is_connected(self) -> bool:
        return self._running

    def _advance_state(self, dt: float) -> None:
        """Advance brain state machine with smooth transitions."""
        self._state_timer += dt

        if self._transition_progress < 1.0:
            self._transition_progress = min(
                1.0, self._transition_progress + dt / self._transition_duration
            )

        if self._state_timer >= self._state_duration:
            self._state_timer = 0.0
            self._prev_multipliers = self._get_effective_multipliers()
            # Pick next state (weighted: prefer adjacent states)
            weights = [1.0] * len(BrainState.STATES)
            # Higher weight for neighboring states (more natural transitions)
            curr = self._current_state_idx
            for i in range(len(weights)):
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
            state_name, mults, dur = BrainState.STATES[self._current_state_idx]
            self._curr_multipliers = dict(mults)
            self._state_duration = dur + random.uniform(-8, 8)
            self._transition_progress = 0.0
            self._transition_duration = random.uniform(3.0, 8.0)

    def _get_effective_multipliers(self) -> Dict[str, float]:
        """Interpolate between previous and current state multipliers."""
        p = self._smooth_step(self._transition_progress)
        result = {}
        for key in self.BASE_AMPLITUDES:
            prev = self._prev_multipliers.get(key, 1.0)
            curr = self._curr_multipliers.get(key, 1.0)
            result[key] = prev + (curr - prev) * p
        return result

    @staticmethod
    def _smooth_step(t: float) -> float:
        """Smooth hermite interpolation for natural transitions."""
        t = max(0.0, min(1.0, t))
        return t * t * (3.0 - 2.0 * t)

    def read_sample(self) -> Dict[str, float]:
        """Generate a single mock EEG sample with realistic band activity."""
        t = time.time() - self._start_time if self._running else 0.0

        self._advance_state(0.5)

        multipliers = self._get_effective_multipliers()

        sample: Dict[str, float] = {"timestamp": t}

        for band in self.BASE_AMPLITUDES:
            base = self.BASE_AMPLITUDES[band]
            mult = multipliers[band]
            rate = self.MODULATION_RATES[band]
            phase = self._phase_offsets[band]
            noise_std = base * self.NOISE_FRACTION[band]

            # Amplitude envelope: slow modulation + harmonics
            envelope = (
                1.0
                + 0.35 * math.sin(2 * math.pi * rate * t + phase)
                + 0.15 * math.sin(2 * math.pi * rate * 2.3 * t + phase * 1.7)
                + 0.08 * math.sin(2 * math.pi * rate * 0.4 * t + phase * 0.6)
            )

            # Cross-band interaction: alpha suppresses when beta is high
            if band.startswith("alpha"):
                beta_mult = (multipliers.get("beta1", 1.0) + multipliers.get("beta2", 1.0)) / 2
                if beta_mult > 1.0:
                    mult *= max(0.3, 1.0 - (beta_mult - 1.0) * 0.4)

            # Delta/theta boost when alpha is low (drowsiness)
            if band in ("delta", "theta"):
                alpha_mult = (multipliers.get("alpha1", 1.0) + multipliers.get("alpha2", 1.0)) / 2
                if alpha_mult < 0.6:
                    mult *= 1.0 + (0.6 - alpha_mult) * 0.5

            value = base * mult * envelope + random.gauss(0, noise_std)

            # Occasional burst activity (10% chance per sample per band)
            if random.random() < 0.10:
                burst = random.uniform(0.8, 1.5) * base * 0.3
                value += burst

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
    print("Band amplitudes over 20 samples (0.1s intervals):")
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
