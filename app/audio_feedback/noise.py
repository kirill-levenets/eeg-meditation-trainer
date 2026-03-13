import threading
from typing import Optional

import numpy as np
import sounddevice as sd

from app.config import APP
from app.logger import logger


class WhiteNoiseGenerator:
    """Generates and plays white noise in realtime via sounddevice.

    No WAV files are created. Audio is synthesized on-the-fly in a
    streaming callback running in a separate thread.
    """

    def __init__(self) -> None:
        self._volume: float = 0.0
        self._max_volume: float = APP.MAX_VOLUME
        self._threshold: int = 50
        self._stream: Optional[sd.OutputStream] = None
        self._is_playing: bool = False
        self._lock: threading.Lock = threading.Lock()

    def _audio_callback(self, outdata: np.ndarray, frames: int,
                        time_info, status) -> None:
        """Called by sounddevice in the audio thread to fill output buffer."""
        with self._lock:
            vol = self._volume
        if vol <= 0.0:
            outdata[:] = 0.0
        else:
            noise = np.random.uniform(-1.0, 1.0, size=(frames, 1)).astype(np.float32)
            outdata[:] = noise * vol

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
        new_vol = self.compute_volume(meditation_score)
        with self._lock:
            self._volume = new_vol

    def start(self) -> None:
        """Start realtime white noise playback."""
        if self._is_playing:
            return
        try:
            self._stream = sd.OutputStream(
                samplerate=APP.WHITE_NOISE_SAMPLE_RATE,
                channels=1,
                dtype="float32",
                callback=self._audio_callback,
                blocksize=1024,
            )
            self._stream.start()
            self._is_playing = True
            logger.info("Realtime white noise playback started")
        except Exception as e:
            logger.warning(f"Could not start audio stream: {e}")
            self._is_playing = False

    def stop(self) -> None:
        """Stop white noise playback."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._is_playing = False
        with self._lock:
            self._volume = 0.0

    @property
    def volume(self) -> float:
        with self._lock:
            return self._volume

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    def cleanup(self) -> None:
        """Stop stream and release resources."""
        self.stop()


if __name__ == "__main__":
    import time

    gen = WhiteNoiseGenerator()
    print(f"Volume at score 0: {gen.compute_volume(0):.2f}")
    print(f"Volume at score 25: {gen.compute_volume(25):.2f}")
    print(f"Volume at score 50: {gen.compute_volume(50):.2f}")
    print(f"Volume at score 100: {gen.compute_volume(100):.2f}")

    gen.set_threshold(50)
    gen.update(25)
    gen.start()
    print(f"Playing: {gen.is_playing}, Volume: {gen.volume:.2f}")
    time.sleep(2)
    gen.update(50)
    print(f"Volume after threshold: {gen.volume:.2f}")
    time.sleep(1)
    gen.stop()
    print(f"Playing after stop: {gen.is_playing}")
    gen.cleanup()
    print("Cleanup done")
