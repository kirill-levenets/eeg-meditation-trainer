import array
import wave
import os
import random
import tempfile
from typing import Optional

from app.config import APP
from app.logger import logger


class WhiteNoiseGenerator:
    """Generates white noise audio and controls volume based on meditation score."""

    def __init__(self) -> None:
        self._volume: float = 0.0
        self._max_volume: float = APP.MAX_VOLUME
        self._threshold: int = 50
        self._noise_file: Optional[str] = None
        self._sound: object = None
        self._is_playing: bool = False
        self._generate_noise_file()

    def _generate_noise_file(self) -> None:
        """Generate a white noise WAV file for looped playback."""
        sample_rate = APP.WHITE_NOISE_SAMPLE_RATE
        duration = APP.WHITE_NOISE_DURATION
        num_samples = int(sample_rate * duration)

        noise_data = array.array("h")
        for _ in range(num_samples):
            sample = int(random.uniform(-1.0, 1.0) * 32767)
            noise_data.append(sample)

        self._noise_file = os.path.join(tempfile.gettempdir(), "eeg_white_noise.wav")
        with wave.open(self._noise_file, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(noise_data.tobytes())

        logger.info(f"White noise file generated: {self._noise_file}")

    def set_threshold(self, threshold: int) -> None:
        self._threshold = max(1, threshold)

    def compute_volume(self, meditation_score: float) -> float:
        """Compute volume based on meditation score and threshold."""
        if meditation_score >= self._threshold:
            return 0.0
        return self._max_volume * (self._threshold - meditation_score) / self._threshold

    def update(self, meditation_score: float) -> None:
        """Update volume based on current meditation score."""
        self._volume = self.compute_volume(meditation_score)
        if self._sound is not None:
            try:
                self._sound.volume = self._volume
            except Exception:
                pass

    def start(self) -> None:
        """Start playing white noise (requires Kivy SoundLoader)."""
        try:
            from kivy.core.audio import SoundLoader

            if self._noise_file and os.path.exists(self._noise_file):
                self._sound = SoundLoader.load(self._noise_file)
                if self._sound:
                    self._sound.loop = True
                    self._sound.volume = self._volume
                    self._sound.play()
                    self._is_playing = True
                    logger.info("White noise playback started")
        except ImportError:
            logger.warning("Kivy SoundLoader not available, audio disabled")

    def stop(self) -> None:
        """Stop white noise playback."""
        if self._sound:
            try:
                self._sound.stop()
            except Exception:
                pass
            self._sound = None
        self._is_playing = False
        self._volume = 0.0

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    def cleanup(self) -> None:
        """Remove temporary noise file."""
        self.stop()
        if self._noise_file and os.path.exists(self._noise_file):
            try:
                os.remove(self._noise_file)
            except OSError:
                pass


if __name__ == "__main__":
    gen = WhiteNoiseGenerator()
    print(f"Noise file: {gen._noise_file}")
    print(f"Volume at score 0: {gen.compute_volume(0):.2f}")
    print(f"Volume at score 25: {gen.compute_volume(25):.2f}")
    print(f"Volume at score 50: {gen.compute_volume(50):.2f}")
    print(f"Volume at score 100: {gen.compute_volume(100):.2f}")
    gen.cleanup()
    print("Cleanup done")
