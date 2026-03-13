from collections import deque
from typing import Dict, List


class RollingBuffer:
    """Rolling average buffer for signal smoothing."""

    def __init__(self, window_size: int = 5) -> None:
        self._window_size: int = window_size
        self._buffers: Dict[str, deque] = {}

    def push(self, band_name: str, value: float) -> float:
        """Push a new value and return the smoothed (rolling average) value."""
        if band_name not in self._buffers:
            self._buffers[band_name] = deque(maxlen=self._window_size)
        buf = self._buffers[band_name]
        buf.append(value)
        return sum(buf) / len(buf)

    def push_sample(self, sample: Dict[str, float]) -> Dict[str, float]:
        """Smooth all numeric bands in a sample dict."""
        smoothed: Dict[str, float] = {}
        for key, value in sample.items():
            if isinstance(value, (int, float)) and key != "timestamp":
                smoothed[key] = self.push(key, value)
            else:
                smoothed[key] = value
        return smoothed

    def reset(self) -> None:
        self._buffers.clear()


class VarianceBuffer:
    """Rolling buffer for computing variance over a time window (e.g., 20 seconds)."""

    def __init__(self, max_size: int = 40) -> None:
        self._buffer: deque = deque(maxlen=max_size)

    def push(self, value: float) -> None:
        self._buffer.append(value)

    def variance(self) -> float:
        if len(self._buffer) < 2:
            return 0.0
        n = len(self._buffer)
        mean = sum(self._buffer) / n
        return sum((x - mean) ** 2 for x in self._buffer) / n

    def mean(self) -> float:
        if not self._buffer:
            return 0.0
        return sum(self._buffer) / len(self._buffer)

    def values(self) -> List[float]:
        return list(self._buffer)

    def reset(self) -> None:
        self._buffer.clear()

    def __len__(self) -> int:
        return len(self._buffer)


if __name__ == "__main__":
    rb = RollingBuffer(window_size=5)
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    for v in values:
        smoothed = rb.push("alpha", v)
        print(f"Input: {v}, Smoothed: {smoothed:.2f}")

    vb = VarianceBuffer(max_size=5)
    for v in [100.0, 100.0, 100.0, 100.0, 100.0]:
        vb.push(v)
    print(f"Variance of constant: {vb.variance():.4f}")

    for v in [50.0, 150.0, 50.0, 150.0, 50.0]:
        vb.push(v)
    print(f"Variance of oscillating: {vb.variance():.4f}")
