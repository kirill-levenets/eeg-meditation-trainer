"""The built-in sounds, synthesized: the rain, tone and cricket loops, the bell, the chime, the warble and the gong;
kept on file, so only the first launch (or a change to the generators) writes them."""

import functools
import math
import os
import random
import struct
import wave
from collections.abc import Callable
from typing import BinaryIO

from app.config import APP
from app.storage.fileops import discard_file, write_file_atomic

_FADE_SAMPLES = 512
_NOISE_BUFFER_SECONDS = 10
_HEARTBEAT_PULSE_SECONDS = 0.1  # short cricket chirp on a ~10s silent bed -> one chirp per loop
_SOUNDS_VERSION = 1  # of the generators: a kept sound is reused by its name, so a change to their samples bumps it


def _write_wav(path: str, samples: bytes, rate: int) -> None:
    """Write raw 16-bit mono PCM samples as a WAV file that is whole or absent: a kept sound is trusted by its name."""
    def write(f: BinaryIO) -> None:
        with wave.open(f, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(samples)

    write_file_atomic(path, write)


def _generate_noise_wav(volume: float, rate: int, duration: float) -> bytes:
    """Generate rain-like noise PCM with crossfade at boundaries for gapless loop.

    Blends brown noise (warm low rumble) with a touch of white noise
    (high-frequency patter), then applies a one-pole low-pass filter
    to soften harsh edges. Sounds like steady rain.
    """
    n_samples = int(rate * duration)
    if volume <= 0.001:
        return b"\x00" * (n_samples * 2)

    # Brown noise via leaky integration of white noise
    brown = 0.0
    leak = 0.98  # higher = deeper rumble
    # Low-pass filter state (smooths the final mix)
    lp = 0.0
    alpha = _lowpass_alpha(2500.0, rate)  # tames harsh highs

    raw = []
    for _ in range(n_samples):
        white = random.uniform(-1.0, 1.0)
        # Brown noise: integrated white with leak to prevent drift
        brown = leak * brown + white * (1.0 - leak)
        # Mix: 80% brown (rumble) + 20% white (patter texture)
        sample = 0.8 * brown + 0.2 * white
        # One-pole low-pass
        lp += alpha * (sample - lp)
        raw.append(lp)

    return _loop_pcm(raw, volume)


def _lowpass_alpha(cutoff: float, rate: int) -> float:
    """The one-pole low-pass coefficient for `cutoff` Hz at `rate` samples per second."""
    rc = 1.0 / (2.0 * math.pi * cutoff)
    dt = 1.0 / rate
    return dt / (rc + dt)


def _loop_pcm(raw: list[float], gain: float) -> bytes:
    """Float samples as 16-bit PCM peaking at `gain` of full scale, ends crossfaded so the loop repeats without a click."""
    n_samples = len(raw)
    peak = max(abs(s) for s in raw) or 1.0
    pcm = [int((s / peak) * gain * 32767) for s in raw]
    for i in range(_FADE_SAMPLES):
        t = i / _FADE_SAMPLES  # 0 → 1
        head = pcm[i]
        tail = pcm[n_samples - _FADE_SAMPLES + i]
        pcm[i] = int(head * t + tail * (1 - t))
        pcm[n_samples - _FADE_SAMPLES + i] = int(tail * t + head * (1 - t))
    pcm = [max(-32767, min(32767, s)) for s in pcm]
    return struct.pack(f"<{n_samples}h", *pcm)


def _generate_tone_wav(rate: int, freq: float, duration: float) -> bytes:
    """Harmonic-pad drone (fundamental + a fifth), low-passed and crossfaded for a seamless loop."""
    n_samples = int(rate * duration)
    fifth = freq * 1.5
    lp = 0.0
    alpha = _lowpass_alpha(3000.0, rate)

    raw = []
    for i in range(n_samples):
        shimmer = 1.0 + 0.08 * math.sin(2 * math.pi * 0.2 * i / rate)
        value = 0.6 * math.sin(2 * math.pi * freq * i / rate)
        value += 0.4 * math.sin(2 * math.pi * fifth * i / rate)
        value *= shimmer
        lp += alpha * (value - lp)
        raw.append(lp)

    return _loop_pcm(raw, 0.9)  # 10% headroom below the 16-bit ceiling


def _generate_heartbeat_wav(rate: int, duration: float, pulse_seconds: float) -> bytes:
    """Liveness cue: a silent bed with one short cricket-like chirp, so a looping player
    fires a soft chirp once per `duration`s. The chirp is a high tonal carrier (+ a
    harmonic for a buzzy, cicada-ish edge) gated by a fast half-wave amplitude trill so
    it reads as insect syllables, not a tone. Loop edges stay silent (lead-in + trailing
    silence) and the burst is Hann-windowed to zero at both ends, so the loop is seamless."""
    n_samples = int(rate * duration)
    raw = [0] * n_samples
    pulse_len = min(int(rate * pulse_seconds), max(0, n_samples - 2))
    if pulse_len > 1:
        start = min(int(rate * 0.2), n_samples - pulse_len - 1)  # lead-in keeps the loop head silent
        carrier = 4800.0  # Hz — cricket-like chirp pitch (< Nyquist with its 2nd harmonic)
        trill = 40.0      # Hz — syllable rate that gives the stridulating texture
        burst = []
        for i in range(pulse_len):
            t = i / rate
            tone = math.sin(2 * math.pi * carrier * t) + 0.3 * math.sin(2 * math.pi * 2 * carrier * t)
            syllable = max(0.0, math.sin(2 * math.pi * trill * t)) ** 1.5  # half-wave -> distinct chirps
            window = 0.5 * (1.0 - math.cos(2 * math.pi * i / (pulse_len - 1)))  # Hann: edges -> 0, no click
            burst.append(tone * syllable * window)
        peak = max(abs(s) for s in burst) or 1.0
        for i, s in enumerate(burst):
            raw[start + i] = max(-32767, min(32767, int((s / peak) * 0.9 * 32767)))
    return struct.pack(f"<{n_samples}h", *raw)


def _generate_bell_wav(rate: int, freq: float, duration: float) -> bytes:
    """Synthesize a decaying sine wave with harmonics (tingsha bell)."""
    n_samples = int(rate * duration)
    samples = []
    for i in range(n_samples):
        progress = i / n_samples
        envelope = math.exp(-3.0 * progress)
        value = envelope * math.sin(2 * math.pi * freq * i / rate)
        value += 0.3 * envelope * math.sin(4 * math.pi * freq * i / rate)
        value += 0.15 * envelope * math.sin(6 * math.pi * freq * i / rate)
        samples.append(int(value * 28000))
    return struct.pack(f"<{n_samples}h", *samples)


def _generate_chime_wav(rate: int, freq: float, duration: float) -> bytes:
    """Synthesize a gentle chime for subtle distraction.

    Higher pitch than the sinking bell, softer harmonics, longer
    exponential decay with a shimmer effect.
    """
    n_samples = int(rate * duration)
    samples = []
    for i in range(n_samples):
        progress = i / n_samples
        envelope = math.exp(-2.0 * progress)
        shimmer = 1.0 + 0.15 * math.sin(2 * math.pi * 6.0 * i / rate)
        value = envelope * shimmer * math.sin(2 * math.pi * freq * i / rate)
        value += 0.2 * envelope * math.sin(2 * math.pi * freq * 2.0 * i / rate)
        value += 0.08 * envelope * math.sin(2 * math.pi * freq * 3.0 * i / rate)
        samples.append(int(value * 20000))
    return struct.pack(f"<{n_samples}h", *samples)


def _generate_disconnect_wav(
    rate: int, freq_low: float, freq_high: float, duration: float, cycles: int
) -> bytes:
    """Synthesize an urgent alternating dual-frequency warble alert.

    Rapidly alternates between freq_low and freq_high for `cycles` times
    within the given duration. Sounds harsh and attention-grabbing.
    """
    n_samples = int(rate * duration)
    cycle_len = n_samples // cycles
    half_cycle = cycle_len // 2
    samples = []
    for i in range(n_samples):
        progress = i / n_samples
        envelope = 1.0 - 0.3 * progress
        pos_in_cycle = i % cycle_len
        freq = freq_low if pos_in_cycle < half_cycle else freq_high
        value = envelope * math.sin(2 * math.pi * freq * i / rate)
        value += 0.5 * envelope * math.sin(2 * math.pi * freq * 1.5 * i / rate)
        samples.append(max(-32767, min(32767, int(value * 22000))))
    return struct.pack(f"<{n_samples}h", *samples)


def _kept_sounds(rate: int) -> dict[str, tuple[str, Callable[[], bytes]]]:
    """Each built-in sound's file and its generator; the file's name carries what shapes the samples."""
    shaped = {
        "noise": (_generate_noise_wav, 1.0, rate, _NOISE_BUFFER_SECONDS),
        "bell": (_generate_bell_wav, rate, APP.BELL_FREQUENCY, APP.BELL_DURATION),
        "timer_bell": (_generate_bell_wav, rate, APP.TIMER_BELL_FREQUENCY, APP.TIMER_BELL_DURATION),
        "chime": (_generate_chime_wav, rate, APP.CHIME_FREQUENCY, APP.CHIME_DURATION),
        "disconnect": (_generate_disconnect_wav, rate, APP.DISCONNECT_FREQ_LOW, APP.DISCONNECT_FREQ_HIGH,
                       APP.DISCONNECT_DURATION, APP.DISCONNECT_CYCLES),
        "tone": (_generate_tone_wav, rate, APP.TONE_FREQUENCY, _NOISE_BUFFER_SECONDS),
        "heartbeat": (_generate_heartbeat_wav, rate, _NOISE_BUFFER_SECONDS, _HEARTBEAT_PULSE_SECONDS),
    }
    sounds = {}
    for name, (generate, *args) in shaped.items():
        file = f"v{_SOUNDS_VERSION}-{name}-{'_'.join(str(arg) for arg in args)}.wav"
        sounds[name] = (os.path.join(APP.BUILT_IN_SOUNDS_DIR, file), functools.partial(generate, *args))
    return sounds


def _drop_stale_sounds() -> None:
    """Remove the sounds another version of the generators kept."""
    for file in os.listdir(APP.BUILT_IN_SOUNDS_DIR):
        if file.endswith(".wav") and not file.startswith(f"v{_SOUNDS_VERSION}-"):
            discard_file(os.path.join(APP.BUILT_IN_SOUNDS_DIR, file))


class KeptSounds:
    """The built-in sounds' files at a sample rate, each generated on its first use and kept for the next launches."""

    def __init__(self, rate: int) -> None:
        self._rate = rate
        self._files = _kept_sounds(rate)

    def prepare(self) -> None:
        """Have the sounds a session can't wait for on file (only the first launch generates them), the stale ones gone."""
        os.makedirs(APP.BUILT_IN_SOUNDS_DIR, exist_ok=True)
        _drop_stale_sounds()
        for name in ("noise", "bell", "timer_bell", "chime", "disconnect"):
            self.path(name)

    def path(self, name: str) -> str:
        """The built-in sound's file, generated unless it is kept already."""
        path, generate = self._files[name]
        if not os.path.exists(path):
            _write_wav(path, generate(), self._rate)
        return path

    def feedback_path(self, kind: str, custom_path: str = "") -> str:
        """A feedback source's playable file: a custom one that exists, else the tone, cricket or rain loop."""
        if kind == "custom" and custom_path and os.path.isfile(custom_path):
            return custom_path
        return self.path(kind if kind in ("tone", "heartbeat") else "noise")
