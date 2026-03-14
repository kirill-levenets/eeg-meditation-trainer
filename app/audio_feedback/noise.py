import math
import random
import struct
import time
import threading

from app.config import APP
from app.logger import logger


class AudioEngine:
    """Dual-channel audio engine for meditation neurofeedback.

    Channel 1 (White Noise): Continuous gapless stream via audiostream
        ThreadSource. Volume scales inversely with meditation score.
    Channel 2 (Sinking Alert): Synthesized bell/tingsha tone played once
        when sinking exceeds threshold, with cooldown to prevent spam.

    Also supports:
    - test_audio(): plays white noise at full volume for a few seconds
    - disconnect_alert(): plays a warning tone on device disconnect
    """

    def __init__(self) -> None:
        self._volume: float = 0.0
        self._max_volume: float = APP.MAX_VOLUME
        self._threshold: int = METRICS_THRESHOLD_FALLBACK
        self._is_playing: bool = False
        self._stream: object = None
        self._noise_source: object = None
        self._bell_source: object = None
        self._bell_active: bool = False
        self._bell_samples_remaining: int = 0
        self._bell_phase: float = 0.0
        self._sinking_cooldown_until: float = 0.0
        self._sinking_alert_enabled: bool = True
        self._disconnect_alert_enabled: bool = APP.DISCONNECT_ALERT_ENABLED
        self._test_active: bool = False
        self._test_until: float = 0.0
        self._rate: int = APP.WHITE_NOISE_SAMPLE_RATE
        self._buffersize: int = 1024

    def set_threshold(self, threshold: int) -> None:
        self._threshold = max(1, threshold)

    def compute_volume(self, meditation_score: float) -> float:
        """Compute noise volume based on meditation score and threshold."""
        if meditation_score >= self._threshold:
            return 0.0
        raw = self._max_volume * (self._threshold - meditation_score) / self._threshold
        return min(raw, self._max_volume)

    def update(self, meditation_score: float) -> None:
        """Update noise volume based on current meditation score."""
        self._volume = self.compute_volume(meditation_score)

    def update_sinking(self, sinking_score: float) -> None:
        """Check sinking score and trigger bell alert if needed."""
        if not self._sinking_alert_enabled:
            return
        if not self._is_playing:
            return
        now = time.time()
        if sinking_score > APP.SINKING_ALERT_THRESHOLD and now >= self._sinking_cooldown_until:
            self._trigger_bell()
            self._sinking_cooldown_until = now + APP.SINKING_ALERT_COOLDOWN
            logger.info(f"Sinking alert triggered (score={sinking_score:.0f})")

    def _trigger_bell(self) -> None:
        """Activate the bell tone for BELL_DURATION seconds."""
        self._bell_active = True
        self._bell_samples_remaining = int(self._rate * APP.BELL_DURATION)
        self._bell_phase = 0.0

    def _generate_bell_samples(self, count: int) -> bytes:
        """Synthesize a decaying sine wave (tingsha bell sound)."""
        freq = APP.BELL_FREQUENCY
        total_samples = int(self._rate * APP.BELL_DURATION)
        samples = []
        for _ in range(count):
            if self._bell_samples_remaining <= 0:
                self._bell_active = False
                samples.append(0)
                continue
            progress = 1.0 - (self._bell_samples_remaining / total_samples)
            envelope = math.exp(-3.0 * progress)
            value = envelope * math.sin(2 * math.pi * freq * self._bell_phase / self._rate)
            # Add subtle harmonics for richer bell timbre
            value += 0.3 * envelope * math.sin(4 * math.pi * freq * self._bell_phase / self._rate)
            value += 0.15 * envelope * math.sin(6 * math.pi * freq * self._bell_phase / self._rate)
            samples.append(int(value * 28000))
            self._bell_phase += 1.0
            self._bell_samples_remaining -= 1
        return struct.pack(f"<{len(samples)}h", *samples)

    def start(self) -> None:
        """Start dual-channel audio playback via audiostream."""
        if self._is_playing:
            return
        try:
            from audiostream import get_output
            from audiostream.sources.thread import ThreadSource

            self._stream = get_output(
                channels=1, rate=self._rate,
                buffersize=self._buffersize, encoding=16,
            )

            engine = self
            chunk = self._buffersize

            class DualChannelSource(ThreadSource):
                def get_bytes(self_src):
                    # Test mode: full volume white noise
                    if engine._test_active:
                        if time.time() >= engine._test_until:
                            engine._test_active = False
                        else:
                            return struct.pack(
                                f"<{chunk}h",
                                *(int(random.uniform(-0.7, 0.7) * 32767)
                                  for _ in range(chunk))
                            )

                    # Mix Channel 1 (noise) + Channel 2 (bell)
                    noise_data = []
                    bell_data = []
                    has_bell = engine._bell_active

                    if has_bell:
                        bell_data = list(struct.unpack(
                            f"<{chunk}h",
                            engine._generate_bell_samples(chunk)
                        ))

                    vol = engine._volume
                    for i in range(chunk):
                        sample = 0
                        # Channel 1: white noise
                        if vol > 0.001:
                            sample += int(random.uniform(-vol, vol) * 32767)
                        # Channel 2: bell overlay
                        if has_bell and i < len(bell_data):
                            sample += bell_data[i]
                        sample = max(-32767, min(32767, sample))
                        noise_data.append(sample)

                    return struct.pack(f"<{chunk}h", *noise_data)

            self._noise_source = DualChannelSource(self._stream, *[])
            self._noise_source.start()
            self._is_playing = True
            logger.info("Dual-channel audio started (audiostream)")
        except ImportError:
            logger.warning("audiostream not available, audio disabled")
        except Exception as e:
            logger.warning(f"Failed to start audiostream: {e}")

    def stop(self) -> None:
        """Stop all audio playback."""
        if self._noise_source:
            try:
                self._noise_source.stop()
            except Exception:
                pass
            self._noise_source = None
        self._is_playing = False
        self._volume = 0.0
        self._bell_active = False
        self._test_active = False

    def test_audio(self) -> None:
        """Play white noise at ~70% volume for AUDIO_TEST_DURATION seconds.

        If the stream is not running, temporarily starts it then schedules
        a stop via a background timer.
        """
        was_playing = self._is_playing
        if not was_playing:
            self.start()
        self._test_active = True
        self._test_until = time.time() + APP.AUDIO_TEST_DURATION
        logger.info("Audio test started")

        if not was_playing:
            def _stop_after_test():
                time.sleep(APP.AUDIO_TEST_DURATION + 0.3)
                if not self._is_playing:
                    return
                self._test_active = False
                self.stop()
                logger.info("Audio test finished, stream stopped")
            t = threading.Thread(target=_stop_after_test, daemon=True)
            t.start()

    def play_disconnect_alert(self) -> None:
        """Play a short warning tone when device disconnects."""
        if not self._disconnect_alert_enabled:
            return
        self._trigger_bell()
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
        """Stop playback and release resources."""
        self.stop()
        self._stream = None


# Fallback threshold if config not loaded yet
METRICS_THRESHOLD_FALLBACK = 100


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
    engine.cleanup()
    print("Done")
