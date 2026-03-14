import random
import struct

from app.config import APP
from app.logger import logger


class WhiteNoiseGenerator:
    """Gapless white noise via audiostream's ThreadSource.

    Generates random PCM samples on-the-fly in a background thread — no file
    I/O, no loop boundaries, zero audio spikes. Volume is scaled in real time
    based on meditation score vs threshold.

    Falls back gracefully if audiostream is not installed.
    """

    def __init__(self) -> None:
        self._volume: float = 0.0
        self._max_volume: float = APP.MAX_VOLUME
        self._threshold: int = 100
        self._is_playing: bool = False
        self._stream: object = None
        self._source: object = None

    def set_threshold(self, threshold: int) -> None:
        self._threshold = max(1, threshold)

    def compute_volume(self, meditation_score: float) -> float:
        """Compute volume based on meditation score and threshold."""
        if meditation_score >= self._threshold:
            return 0.0
        raw = self._max_volume * (self._threshold - meditation_score) / self._threshold
        return min(raw, self._max_volume)

    def update(self, meditation_score: float) -> None:
        """Update volume based on current meditation score."""
        self._volume = self.compute_volume(meditation_score)

    def start(self) -> None:
        """Start gapless white noise playback via audiostream."""
        if self._is_playing:
            return
        try:
            from audiostream import get_output
            from audiostream.sources.thread import ThreadSource

            rate = APP.WHITE_NOISE_SAMPLE_RATE
            buffersize = 1024
            self._stream = get_output(
                channels=1, rate=rate, buffersize=buffersize, encoding=16,
            )

            generator = self
            chunk_samples = buffersize

            class NoiseSource(ThreadSource):
                def get_bytes(self):
                    vol = generator._volume
                    if vol <= 0.001:
                        return b"\x00" * (chunk_samples * 2)
                    samples = struct.pack(
                        f"<{chunk_samples}h",
                        *(int(random.uniform(-vol, vol) * 32767)
                          for _ in range(chunk_samples))
                    )
                    return samples

            self._source = NoiseSource(self._stream, *[])
            self._source.start()
            self._is_playing = True
            logger.info("White noise streaming started (audiostream)")
        except ImportError:
            logger.warning("audiostream not available, audio disabled")
        except Exception as e:
            logger.warning(f"Failed to start audiostream: {e}")

    def stop(self) -> None:
        """Stop white noise playback."""
        if self._source:
            try:
                self._source.stop()
            except Exception:
                pass
            self._source = None
        self._is_playing = False
        self._volume = 0.0

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    def cleanup(self) -> None:
        """Stop playback and release resources."""
        self.stop()
        self._stream = None


if __name__ == "__main__":
    gen = WhiteNoiseGenerator()
    print(f"Volume at score 0: {gen.compute_volume(0):.2f}")
    print(f"Volume at score 25: {gen.compute_volume(25):.2f}")
    print(f"Volume at score 50: {gen.compute_volume(50):.2f}")
    print(f"Volume at score 100: {gen.compute_volume(100):.2f}")
    gen.set_threshold(100)
    gen.update(25)
    print(f"Volume after update(25): {gen.volume:.2f}")
    gen.cleanup()
    print("Done")
