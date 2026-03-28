"""Generate white, pink, and rain noise WAV files for comparison.

Usage: python tools/compare_noise.py
Creates files in /tmp (5 seconds each).
"""
import math
import random
import struct
import wave

RATE = 22050
DURATION = 5.0
VOLUME = 0.7


def write_wav(path, samples, rate):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples)


def generate_white(volume, rate, duration):
    n = int(rate * duration)
    raw = [int(random.uniform(-volume, volume) * 32767) for _ in range(n)]
    return struct.pack(f"<{n}h", *raw)


def generate_pink(volume, rate, duration):
    n = int(rate * duration)
    b0 = b1 = b2 = b3 = b4 = b5 = b6 = 0.0
    raw = []
    for _ in range(n):
        w = random.uniform(-1.0, 1.0)
        b0 = 0.99886 * b0 + w * 0.0555179
        b1 = 0.99332 * b1 + w * 0.0750759
        b2 = 0.96900 * b2 + w * 0.1538520
        b3 = 0.86650 * b3 + w * 0.3104856
        b4 = 0.55000 * b4 + w * 0.5329522
        b5 = -0.7616 * b5 - w * 0.0168980
        pink = b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362
        b6 = w * 0.115926
        raw.append(max(-32767, min(32767, int((pink / 3.5) * volume * 32767))))
    return struct.pack(f"<{n}h", *raw)


def generate_rain(volume, rate, duration):
    n = int(rate * duration)
    brown = 0.0
    leak = 0.98
    lp = 0.0
    cutoff = 2500.0
    rc = 1.0 / (2.0 * math.pi * cutoff)
    dt = 1.0 / rate
    alpha = dt / (rc + dt)
    raw = []
    for _ in range(n):
        white = random.uniform(-1.0, 1.0)
        brown = leak * brown + white * (1.0 - leak)
        sample = 0.8 * brown + 0.2 * white
        lp += alpha * (sample - lp)
        raw.append(lp)
    peak = max(abs(s) for s in raw) or 1.0
    raw = [max(-32767, min(32767, int((s / peak) * volume * 32767))) for s in raw]
    return struct.pack(f"<{n}h", *raw)


paths = {
    "White noise": "/tmp/white_noise.wav",
    "Pink noise":  "/tmp/pink_noise.wav",
    "Rain noise":  "/tmp/rain_noise.wav",
}

generators = {
    "White noise": generate_white,
    "Pink noise":  generate_pink,
    "Rain noise":  generate_rain,
}

for name, path in paths.items():
    write_wav(path, generators[name](VOLUME, RATE, DURATION), RATE)
    print(f"{name}: {path}")

print("\nPlay with:")
for name, path in paths.items():
    print(f"  aplay {path}   # {name}")
