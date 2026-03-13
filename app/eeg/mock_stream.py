import math
import random
import time
from typing import Dict


class MockEEGStream:
    """Generates simulated EEG data for development and testing."""

    def __init__(self) -> None:
        self._running: bool = False
        self._start_time: float = 0.0

    def start(self) -> None:
        self._running = True
        self._start_time = time.time()

    def stop(self) -> None:
        self._running = False

    @property
    def is_connected(self) -> bool:
        return self._running

    def read_sample(self) -> Dict[str, float]:
        """Generate a single mock EEG sample with realistic-ish waveforms."""
        t = time.time() - self._start_time if self._running else 0.0

        base_alpha1 = 400 + 200 * math.sin(0.1 * t) + random.gauss(0, 30)
        base_alpha2 = 350 + 180 * math.sin(0.12 * t) + random.gauss(0, 25)
        base_beta1 = 150 + 80 * math.sin(0.3 * t) + random.gauss(0, 20)
        base_beta2 = 120 + 60 * math.sin(0.35 * t) + random.gauss(0, 15)
        base_gamma1 = 50 + 30 * math.sin(0.5 * t) + random.gauss(0, 10)
        base_gamma2 = 40 + 25 * math.sin(0.55 * t) + random.gauss(0, 8)
        base_theta = 200 + 100 * math.sin(0.08 * t) + random.gauss(0, 20)
        base_delta = 300 + 150 * math.sin(0.05 * t) + random.gauss(0, 25)

        return {
            "timestamp": t,
            "delta": max(0.0, base_delta),
            "theta": max(0.0, base_theta),
            "alpha1": max(0.0, base_alpha1),
            "alpha2": max(0.0, base_alpha2),
            "beta1": max(0.0, base_beta1),
            "beta2": max(0.0, base_beta2),
            "gamma1": max(0.0, base_gamma1),
            "gamma2": max(0.0, base_gamma2),
            "attention": random.randint(20, 80),
            "meditation": random.randint(20, 80),
        }


if __name__ == "__main__":
    stream = MockEEGStream()
    stream.start()
    for i in range(10):
        sample = stream.read_sample()
        print(f"Sample {i}: alpha1={sample['alpha1']:.1f}, beta1={sample['beta1']:.1f}, theta={sample['theta']:.1f}")
        time.sleep(0.1)
    stream.stop()
    print(f"Connected after stop: {stream.is_connected}")
