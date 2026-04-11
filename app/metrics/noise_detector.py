"""Detect 50/60 Hz power line noise in raw EEG signal using FFT."""

import math
from typing import Optional

from app.logger import logger


class PowerLineDetector:
    """Accumulates raw EEG samples and detects 50/60 Hz interference.

    Call feed() each tick with the raw_eeg_waveform list from the sample.
    After enough samples are collected, result() returns the detection.
    """

    SAMPLE_RATE: int = 512
    MIN_SAMPLES: int = 2048  # ~4 seconds at 512Hz
    # Frequency must be this many times louder than median to count as a peak
    PEAK_RATIO: float = 5.0

    def __init__(self) -> None:
        self._samples: list[float] = []
        self._result: Optional[tuple[bool, Optional[int]]] = None

    def feed(self, raw_waveform: list[int]) -> None:
        """Add raw 512Hz samples. No-op after detection is done."""
        if self._result is not None:
            return
        self._samples.extend(raw_waveform)
        if len(self._samples) >= self.MIN_SAMPLES:
            self._analyze()

    def ready(self) -> bool:
        return self._result is not None

    def result(self) -> Optional[tuple[bool, Optional[int]]]:
        """Return (detected, freq_hz) or None if not ready.

        detected=True, freq_hz=50 means 50Hz noise found.
        detected=False, freq_hz=None means clean signal.
        """
        return self._result

    def reset(self) -> None:
        self._samples.clear()
        self._result = None

    def _analyze(self) -> None:
        n = len(self._samples)
        # Simple DFT at target frequencies (much cheaper than full FFT)
        freqs_to_check = [50, 60]
        magnitudes = {}
        for freq in freqs_to_check:
            magnitudes[freq] = self._goertzel(self._samples, freq, self.SAMPLE_RATE)

        # Compute average magnitude across a few reference frequencies
        ref_freqs = [20, 30, 35, 45, 55, 70, 80, 90]
        ref_mags = [self._goertzel(self._samples, f, self.SAMPLE_RATE) for f in ref_freqs]
        ref_mags.sort()
        median_mag = ref_mags[len(ref_mags) // 2] if ref_mags else 1.0
        if median_mag < 1e-6:
            median_mag = 1.0

        detected_freq = None
        best_ratio = 0.0
        for freq in freqs_to_check:
            ratio = magnitudes[freq] / median_mag
            logger.info(f"Noise check: {freq} Hz mag={magnitudes[freq]:.2f} "
                        f"median={median_mag:.2f} ratio={ratio:.1f}")
            if ratio > self.PEAK_RATIO and ratio > best_ratio:
                best_ratio = ratio
                detected_freq = freq

        if detected_freq is not None:
            self._result = (True, detected_freq)
        else:
            self._result = (False, None)

    @staticmethod
    def _goertzel(samples: list[float], target_freq: float, sample_rate: int) -> float:
        """Goertzel algorithm — efficient single-frequency DFT magnitude."""
        n = len(samples)
        k = round(target_freq * n / sample_rate)
        w = 2.0 * math.pi * k / n
        coeff = 2.0 * math.cos(w)
        s0 = 0.0
        s1 = 0.0
        s2 = 0.0
        for sample in samples:
            s0 = sample + coeff * s1 - s2
            s2 = s1
            s1 = s0
        magnitude = math.sqrt(s1 * s1 + s2 * s2 - coeff * s1 * s2)
        return magnitude / n
