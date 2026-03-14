import math
import os
import random
import struct
import tempfile
import time
import threading
import wave

from app.config import APP
from app.logger import logger

METRICS_THRESHOLD_FALLBACK = 100
_FADE_SAMPLES = 512
_NOISE_BUFFER_SECONDS = 10
_VOLUME_CHANGE_THRESHOLD = 0.05


def _write_wav(path: str, samples: bytes, rate: int) -> None:
    """Write raw 16-bit mono PCM samples to a WAV file."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples)


def _generate_noise_wav(volume: float, rate: int, duration: float) -> bytes:
    """Generate white noise PCM with crossfade at boundaries for gapless loop.

    The first and last _FADE_SAMPLES are blended so the waveform wraps
    smoothly when Kivy loops the file — eliminating the click/spike.
    """
    n_samples = int(rate * duration)
    if volume <= 0.001:
        return b"\x00" * (n_samples * 2)

    raw = [int(random.uniform(-volume, volume) * 32767) for _ in range(n_samples)]

    # Crossfade: blend tail into head so loop boundary is seamless
    for i in range(_FADE_SAMPLES):
        t = i / _FADE_SAMPLES  # 0 → 1
        head = raw[i]
        tail = raw[n_samples - _FADE_SAMPLES + i]
        raw[i] = int(head * t + tail * (1 - t))
        raw[n_samples - _FADE_SAMPLES + i] = int(tail * t + head * (1 - t))

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


class AudioEngine:
    """Dual-channel audio engine for meditation neurofeedback.

    Channel 1 (White Noise): Looping WAV generated with stdlib, played
        via Kivy SoundLoader. Crossfaded boundaries for gapless looping.
        Volume changes trigger WAV regeneration.
    Channel 2 (Sinking Alert): Synthesized bell/tingsha WAV played once
        when sinking exceeds threshold, with cooldown to prevent spam.

    Uses only stdlib + Kivy. No external audio libraries.
    """

    def __init__(self) -> None:
        self._volume: float = 0.0
        self._applied_volume: float = -1.0
        self._max_volume: float = APP.MAX_VOLUME
        self._threshold: int = METRICS_THRESHOLD_FALLBACK
        self._is_playing: bool = False
        self._noise_sound: object = None
        self._bell_sound: object = None
        self._noise_path: str = ""
        self._bell_path: str = ""
        self._sinking_cooldown_until: float = 0.0
        self._sinking_alert_enabled: bool = True
        self._disconnect_alert_enabled: bool = APP.DISCONNECT_ALERT_ENABLED
        self._test_active: bool = False
        self._rate: int = APP.WHITE_NOISE_SAMPLE_RATE
        self._tmpdir: str = tempfile.mkdtemp(prefix="eeg_audio_")
        self._noise_path = os.path.join(self._tmpdir, "noise.wav")
        self._bell_path = os.path.join(self._tmpdir, "bell.wav")
        self._lock = threading.Lock()
        self._prepare_bell()

    def _prepare_bell(self) -> None:
        """Pre-generate the bell WAV file."""
        pcm = _generate_bell_wav(
            self._rate, APP.BELL_FREQUENCY, APP.BELL_DURATION,
        )
        _write_wav(self._bell_path, pcm, self._rate)

    def _rebuild_noise(self, volume: float) -> None:
        """Regenerate noise WAV at given volume and reload SoundLoader."""
        pcm = _generate_noise_wav(volume, self._rate, _NOISE_BUFFER_SECONDS)
        _write_wav(self._noise_path, pcm, self._rate)
        self._applied_volume = volume
        try:
            from kivy.core.audio import SoundLoader
            if self._noise_sound:
                self._noise_sound.stop()
                self._noise_sound.unload()
            snd = SoundLoader.load(self._noise_path)
            if snd:
                snd.loop = True
                snd.volume = 1.0
                snd.play()
                self._noise_sound = snd
        except Exception as e:
            logger.warning(f"Failed to load noise WAV: {e}")

    def set_threshold(self, threshold: int) -> None:
        self._threshold = max(1, threshold)

    def compute_volume(self, meditation_score: float) -> float:
        """Compute noise volume based on meditation score and threshold."""
        if meditation_score >= self._threshold:
            return 0.0
        raw = self._max_volume * (self._threshold - meditation_score) / self._threshold
        return min(raw, self._max_volume)

    def update(self, meditation_score: float) -> None:
        """Update noise volume. Regenerates WAV if volume changed enough."""
        self._volume = self.compute_volume(meditation_score)
        if not self._is_playing or self._test_active:
            return
        delta = abs(self._volume - self._applied_volume)
        if delta >= _VOLUME_CHANGE_THRESHOLD or (
            self._volume <= 0.001 and self._applied_volume > 0.001
        ):
            with self._lock:
                self._rebuild_noise(self._volume)

    def update_sinking(self, sinking_score: float) -> None:
        """Check sinking score and trigger bell alert if needed."""
        if not self._sinking_alert_enabled:
            return
        if not self._is_playing:
            return
        now = time.time()
        if sinking_score > APP.SINKING_ALERT_THRESHOLD and now >= self._sinking_cooldown_until:
            self._play_bell()
            self._sinking_cooldown_until = now + APP.SINKING_ALERT_COOLDOWN
            logger.info(f"Sinking alert triggered (score={sinking_score:.0f})")

    def _play_bell(self) -> None:
        """Play the bell WAV once via SoundLoader."""
        try:
            from kivy.core.audio import SoundLoader
            if self._bell_sound:
                self._bell_sound.stop()
                self._bell_sound.unload()
            snd = SoundLoader.load(self._bell_path)
            if snd:
                snd.loop = False
                snd.volume = 0.8
                snd.play()
                self._bell_sound = snd
        except Exception as e:
            logger.warning(f"Failed to play bell: {e}")

    def start(self) -> None:
        """Start white noise playback."""
        if self._is_playing:
            return
        self._is_playing = True
        initial_vol = self._volume if self._volume > 0.001 else self._max_volume * 0.5
        with self._lock:
            self._rebuild_noise(initial_vol)
        logger.info("Audio engine started (SoundLoader)")

    def stop(self) -> None:
        """Stop all audio playback."""
        if self._noise_sound:
            try:
                self._noise_sound.stop()
                self._noise_sound.unload()
            except Exception:
                pass
            self._noise_sound = None
        if self._bell_sound:
            try:
                self._bell_sound.stop()
                self._bell_sound.unload()
            except Exception:
                pass
            self._bell_sound = None
        self._is_playing = False
        self._volume = 0.0
        self._applied_volume = -1.0
        self._test_active = False

    def test_audio(self) -> None:
        """Play white noise at ~70% volume for AUDIO_TEST_DURATION seconds."""
        was_playing = self._is_playing
        if not was_playing:
            self._is_playing = True
        self._test_active = True
        with self._lock:
            self._rebuild_noise(0.7)
        logger.info("Audio test started")

        def _stop_after_test():
            time.sleep(APP.AUDIO_TEST_DURATION)
            self._test_active = False
            if not was_playing:
                self.stop()
                logger.info("Audio test finished, stopped")
            else:
                with self._lock:
                    self._rebuild_noise(self._volume)

        t = threading.Thread(target=_stop_after_test, daemon=True)
        t.start()

    def play_disconnect_alert(self) -> None:
        """Play a short warning tone when device disconnects."""
        if not self._disconnect_alert_enabled:
            return
        self._play_bell()
        logger.info("Disconnect alert played")

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def sinking_alert_enabled(self) -> bool:
        return self._sinking_alert_enabled

    @sinking_alert_enabled.setter
    def sinking_alert_enabled(self, value: bool) -> None:
        self._sinking_alert_enabled = value

    @property
    def disconnect_alert_enabled(self) -> bool:
        return self._disconnect_alert_enabled

    @disconnect_alert_enabled.setter
    def disconnect_alert_enabled(self, value: bool) -> None:
        self._disconnect_alert_enabled = value

    def cleanup(self) -> None:
        """Stop playback, unload sounds, remove temp files."""
        self.stop()
        for path in (self._noise_path, self._bell_path):
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        try:
            if self._tmpdir and os.path.isdir(self._tmpdir):
                os.rmdir(self._tmpdir)
        except OSError:
            pass


if __name__ == "__main__":
    engine = AudioEngine()
    print(f"Volume at score 0: {engine.compute_volume(0):.2f}")
    print(f"Volume at score 25: {engine.compute_volume(25):.2f}")
    print(f"Volume at score 50: {engine.compute_volume(50):.2f}")
    print(f"Volume at score 100: {engine.compute_volume(100):.2f}")
    engine.set_threshold(100)
    engine.update(25)
    print(f"Volume after update(25): {engine.volume:.2f}")
    print(f"Sinking alert enabled: {engine.sinking_alert_enabled}")
    print(f"Disconnect alert enabled: {engine.disconnect_alert_enabled}")
    print(f"Bell WAV exists: {os.path.exists(engine._bell_path)}")
    engine.cleanup()
    print(f"Temp cleaned: {not os.path.exists(engine._noise_path)}")
    print("Done")
