import math
import os
import random
import struct
import tempfile
import threading
import time
import wave
from typing import Optional

from app.config import APP
from app.logger import logger

# ---------------------------------------------------------------------------
# Noise-player abstraction
# ---------------------------------------------------------------------------

class _KivyNoisePlayer:
    """Kivy SoundLoader-backed noise loop. Used on desktop platforms."""

    def __init__(self, path: str) -> None:
        from kivy.core.audio import SoundLoader
        snd = SoundLoader.load(path)
        if snd is None:
            raise RuntimeError(f"SoundLoader could not load {path!r}")
        snd.loop = True
        self._snd = snd
        self.loop: bool = True

    @property
    def volume(self) -> float:
        return self._snd.volume

    @volume.setter
    def volume(self, v: float) -> None:
        self._snd.volume = max(0.0, min(1.0, float(v)))

    def play(self) -> None:
        self._snd.play()

    def stop(self) -> None:
        self._snd.stop()

    def unload(self) -> None:
        try:
            self._snd.stop()
            self._snd.unload()
        except Exception:
            pass


class _AndroidMediaNoisePlayer:
    """MediaPlayer-backed player. USAGE_MEDIA so it keeps playing through
    screen lock (SDL_mixer/SoundLoader is silenced while locked). Used for the
    looping noise (loop=True) and the one-shot timer gong (loop=False)."""

    def __init__(self, path: str, loop: bool = True) -> None:
        from jnius import autoclass
        MediaPlayer = autoclass("android.media.MediaPlayer")
        AudioAttributes = autoclass("android.media.AudioAttributes")
        AudioAttributesBuilder = autoclass("android.media.AudioAttributes$Builder")

        self._mp = MediaPlayer()
        attrs = (
            AudioAttributesBuilder()
            .setUsage(AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
            .build()
        )
        self._mp.setAudioAttributes(attrs)
        self._mp.setDataSource(path)
        self._mp.setLooping(loop)
        self._mp.prepare()  # synchronous — fine for small WAV files
        self._volume: float = 0.0
        self._mp.setVolume(0.0, 0.0)
        self.loop: bool = True
        self._playing: bool = False

        # Request audio focus so Android treats this as intentional media
        # playback. Failure is non-fatal; MediaPlayer still plays.
        self._audio_mgr = None
        self._focus_request = None
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Context = autoclass("android.content.Context")
            AudioManager = autoclass("android.media.AudioManager")
            AudioFocusRequestBuilder = autoclass(
                "android.media.AudioFocusRequest$Builder"
            )
            mgr = PythonActivity.mActivity.getSystemService(Context.AUDIO_SERVICE)
            self._audio_mgr = mgr
            focus_request = (
                AudioFocusRequestBuilder(AudioManager.AUDIOFOCUS_GAIN)
                .setAudioAttributes(attrs)
                .build()
            )
            self._focus_request = focus_request
            mgr.requestAudioFocus(focus_request)
        except Exception as e:
            logger.warning(f"Audio focus request failed (non-fatal): {e}")

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, v: float) -> None:
        v = max(0.0, min(1.0, float(v)))
        self._volume = v
        try:
            self._mp.setVolume(v, v)
        except Exception:
            pass

    def play(self) -> None:
        try:
            self._mp.start()
            self._playing = True
        except Exception:
            pass

    def stop(self) -> None:
        try:
            if self._playing:
                self._mp.pause()
                self._mp.seekTo(0)
                self._playing = False
        except Exception:
            pass

    def unload(self) -> None:
        # release() MUST run even if stop() raises (IllegalStateException on a
        # MediaPlayer left in a bad state after an aborted session) — otherwise
        # the native player leaks and audio keeps playing until GC.
        try:
            self.stop()
        except Exception:
            logger.exception("MediaPlayer stop during unload failed")
        try:
            self._mp.release()
        except Exception:
            logger.exception("MediaPlayer release failed")
        try:
            if self._audio_mgr and self._focus_request:
                self._audio_mgr.abandonAudioFocusRequest(self._focus_request)
        except Exception:
            logger.exception("MediaPlayer abandonAudioFocusRequest failed")


def _make_noise_player(path: str):
    """Return the right noise player for this platform.

    On Android, tries MediaPlayer first (survives screen lock). Falls back to
    SoundLoader if MediaPlayer init fails. Desktop always uses SoundLoader.
    """
    from kivy.utils import platform as kplat
    if kplat == "android":
        try:
            return _AndroidMediaNoisePlayer(path)
        except Exception as e:
            logger.warning(f"Falling back to SoundLoader for noise: {e}")
    return _KivyNoisePlayer(path)

METRICS_THRESHOLD_FALLBACK = 100
_FADE_SAMPLES = 512
_NOISE_BUFFER_SECONDS = 10


def _write_wav(path: str, samples: bytes, rate: int) -> None:
    """Write raw 16-bit mono PCM samples to a WAV file."""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples)


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
    cutoff = 2500.0  # Hz — tame harsh highs
    rc = 1.0 / (2.0 * math.pi * cutoff)
    dt = 1.0 / rate
    alpha = dt / (rc + dt)

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

    # Normalize to [-1, 1]
    peak = max(abs(s) for s in raw) or 1.0
    raw = [int((s / peak) * volume * 32767) for s in raw]

    # Crossfade: blend tail into head so loop boundary is seamless
    for i in range(_FADE_SAMPLES):
        t = i / _FADE_SAMPLES  # 0 → 1
        head = raw[i]
        tail = raw[n_samples - _FADE_SAMPLES + i]
        raw[i] = int(head * t + tail * (1 - t))
        raw[n_samples - _FADE_SAMPLES + i] = int(tail * t + head * (1 - t))

    # Clamp to 16-bit range
    raw = [max(-32767, min(32767, s)) for s in raw]

    return struct.pack(f"<{n_samples}h", *raw)


def _generate_tone_wav(rate: int, freq: float, duration: float) -> bytes:
    """Harmonic-pad drone (fundamental + a fifth), low-passed and crossfaded for a seamless loop."""
    n_samples = int(rate * duration)
    fifth = freq * 1.5
    lp = 0.0
    cutoff = 3000.0
    rc = 1.0 / (2.0 * math.pi * cutoff)
    dt = 1.0 / rate
    alpha = dt / (rc + dt)

    raw = []
    for i in range(n_samples):
        shimmer = 1.0 + 0.08 * math.sin(2 * math.pi * 0.2 * i / rate)
        value = 0.6 * math.sin(2 * math.pi * freq * i / rate)
        value += 0.4 * math.sin(2 * math.pi * fifth * i / rate)
        value *= shimmer
        lp += alpha * (value - lp)
        raw.append(lp)

    peak = max(abs(s) for s in raw) or 1.0
    raw = [int((s / peak) * 0.9 * 32767) for s in raw]

    for i in range(_FADE_SAMPLES):
        t = i / _FADE_SAMPLES
        head = raw[i]
        tail = raw[n_samples - _FADE_SAMPLES + i]
        raw[i] = int(head * t + tail * (1 - t))
        raw[n_samples - _FADE_SAMPLES + i] = int(tail * t + head * (1 - t))

    raw = [max(-32767, min(32767, s)) for s in raw]
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


class AudioEngine:
    """4-channel audio engine for meditation neurofeedback.

    Channel 1 (Noise): Looping brown/white noise WAV, volume scaled by
        meditation score via smooth ramping.
    Channel 2 (Bell): Synthesized tingsha bell, one-shot on sinking alert
        with cooldown.
    Channel 3 (Chime): Synthesized chime, one-shot on subtle distraction
        alert with cooldown.
    Channel 4 (Disconnect): Warble alert on Bluetooth disconnection.

    Uses only stdlib + Kivy. No external audio libraries.
    """

    # Volume interpolation: ramp toward target in small steps
    _RAMP_INTERVAL: float = 0.025  # 25ms between steps (40 updates/sec)
    _RAMP_SPEED: float = 0.6  # max volume change per second

    def __init__(self) -> None:
        self._volume: float = 0.0
        self._target_volume: float = 0.0
        self._max_volume: float = APP.MAX_VOLUME
        self._threshold: int = METRICS_THRESHOLD_FALLBACK
        self._is_playing: bool = False
        self._noise_sound: object = None
        self._bell_sound: object = None
        self._timer_bell_player: object = None  # Android MediaPlayer gong (lock-through)
        self._noise_path: str = ""
        self._bell_path: str = ""
        self._sinking_cooldown_until: float = 0.0
        self._sinking_alert_enabled: bool = False
        self._subtle_alert_enabled: bool = False
        self._disconnect_alert_enabled: bool = APP.DISCONNECT_ALERT_ENABLED
        self._test_active: bool = False
        self._rate: int = APP.WHITE_NOISE_SAMPLE_RATE
        self._tmpdir: str = tempfile.mkdtemp(prefix="eeg_audio_")
        self._noise_path = os.path.join(self._tmpdir, "noise.wav")
        self._bell_path = os.path.join(self._tmpdir, "bell.wav")
        self._timer_bell_path = os.path.join(self._tmpdir, "timer_bell.wav")
        self._chime_path = os.path.join(self._tmpdir, "chime.wav")
        self._disconnect_path = os.path.join(self._tmpdir, "disconnect.wav")
        self._chime_sound: object = None
        self._disconnect_sound: object = None
        self._subtle_cooldown_until: float = 0.0
        self._lock = threading.Lock()
        self._ramp_thread: Optional[threading.Thread] = None
        self._ramp_running: bool = False
        self._prepare_sounds()

    def _prepare_sounds(self) -> None:
        """Pre-generate all WAV files (noise at full amplitude, alerts)."""
        pcm = _generate_noise_wav(1.0, self._rate, _NOISE_BUFFER_SECONDS)
        _write_wav(self._noise_path, pcm, self._rate)

        pcm = _generate_bell_wav(
            self._rate, APP.BELL_FREQUENCY, APP.BELL_DURATION,
        )
        _write_wav(self._bell_path, pcm, self._rate)

        pcm = _generate_bell_wav(
            self._rate, APP.TIMER_BELL_FREQUENCY, APP.TIMER_BELL_DURATION,
        )
        _write_wav(self._timer_bell_path, pcm, self._rate)

        pcm = _generate_chime_wav(
            self._rate, APP.CHIME_FREQUENCY, APP.CHIME_DURATION,
        )
        _write_wav(self._chime_path, pcm, self._rate)

        pcm = _generate_disconnect_wav(
            self._rate,
            APP.DISCONNECT_FREQ_LOW,
            APP.DISCONNECT_FREQ_HIGH,
            APP.DISCONNECT_DURATION,
            APP.DISCONNECT_CYCLES,
        )
        _write_wav(self._disconnect_path, pcm, self._rate)

    def _start_noise_loop(self) -> None:
        """Load and start the pre-generated noise WAV in a loop."""
        try:
            if self._noise_sound:
                self._noise_sound.stop()
                self._noise_sound.unload()
            snd = _make_noise_player(self._noise_path)
            snd.loop = True
            snd.volume = self._volume
            snd.play()
            self._noise_sound = snd
        except Exception as e:
            logger.warning(f"Failed to load noise: {e}")

    def _set_noise_volume(self, volume: float) -> None:
        """Set target volume — the ramp thread interpolates smoothly toward it."""
        self._target_volume = volume
        self._volume = volume
        self._ensure_ramp_thread()

    def _ensure_ramp_thread(self) -> None:
        """Start the volume ramp thread if not already running."""
        if self._ramp_running:
            return
        self._ramp_running = True
        self._ramp_thread = threading.Thread(target=self._ramp_loop, daemon=True)
        self._ramp_thread.start()

    def _ramp_loop(self) -> None:
        """Background loop: smoothly interpolate sound.volume toward target."""
        max_step = self._RAMP_SPEED * self._RAMP_INTERVAL
        while self._ramp_running and self._is_playing:
            target = self._target_volume
            if self._noise_sound:
                try:
                    current = self._noise_sound.volume
                    diff = target - current
                    if abs(diff) < 0.001:
                        self._noise_sound.volume = target
                    else:
                        step = max(-max_step, min(max_step, diff))
                        self._noise_sound.volume = current + step
                except Exception:
                    pass
            time.sleep(self._RAMP_INTERVAL)
        self._ramp_running = False

    def set_threshold(self, threshold: int) -> None:
        self._threshold = max(1, threshold)

    def compute_volume(self, meditation_score: float) -> float:
        """Compute noise volume based on meditation score and threshold.

        Uses log scaling so volume rises quickly at first but the rate of
        increase slows as score approaches zero (concave curve).
        Curve: log(1 + t*k) / log(1 + k), k=9.
        """
        if meditation_score >= self._threshold:
            return 0.0
        t = (self._threshold - meditation_score) / self._threshold  # 0..1 linear
        k = 9.0
        scaled = math.log(1.0 + t * k) / math.log(1.0 + k)  # 0..1 log-curved
        return min(scaled * self._max_volume, self._max_volume)

    def update(self, meditation_score: float) -> None:
        """Update noise volume smoothly via sound.volume property."""
        new_vol = self.compute_volume(meditation_score)
        if not self._is_playing or self._test_active:
            self._volume = new_vol
            return
        self._set_noise_volume(new_vol)

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

    def update_subtle_distraction(self, subtle_score: float) -> None:
        """Check subtle distraction score and play gentle chime if needed."""
        if not self._subtle_alert_enabled:
            return
        if not self._is_playing:
            return
        now = time.time()
        if subtle_score > APP.SUBTLE_ALERT_THRESHOLD and now >= self._subtle_cooldown_until:
            self._play_chime()
            self._subtle_cooldown_until = now + APP.SUBTLE_ALERT_COOLDOWN
            logger.info(f"Subtle distraction chime (score={subtle_score:.0f})")

    def _play_sound(self, path: str, volume: float = 0.8) -> object:
        """Play a WAV file once via SoundLoader. Returns the Sound object."""
        try:
            from kivy.core.audio import SoundLoader
            snd = SoundLoader.load(path)
            if snd:
                snd.loop = False
                snd.volume = volume
                snd.play()
                return snd
        except Exception as e:
            logger.warning(f"Failed to play sound {path}: {e}")
        return None

    def _play_bell(self) -> None:
        """Play the sinking bell WAV."""
        if self._bell_sound:
            try:
                self._bell_sound.stop()
                self._bell_sound.unload()
            except Exception:
                pass
        self._bell_sound = self._play_sound(self._bell_path, 0.8)

    def _play_chime(self) -> None:
        """Play the gentle chime WAV for subtle distraction."""
        if self._chime_sound:
            try:
                self._chime_sound.stop()
                self._chime_sound.unload()
            except Exception:
                pass
        self._chime_sound = self._play_sound(self._chime_path, 0.6)

    def _play_disconnect(self) -> None:
        """Play the harsh disconnect alert WAV."""
        if self._disconnect_sound:
            try:
                self._disconnect_sound.stop()
                self._disconnect_sound.unload()
            except Exception:
                pass
        self._disconnect_sound = self._play_sound(self._disconnect_path, 0.9)

    def start(self) -> None:
        """Start noise playback."""
        if self._is_playing:
            return
        self._is_playing = True
        initial = self._volume if self._volume > 0.001 else self._max_volume * 0.5
        self._volume = initial
        self._target_volume = initial
        with self._lock:
            self._start_noise_loop()
        self._ensure_ramp_thread()
        logger.info("Audio engine started")

    def mute(self) -> None:
        """Silence the noise immediately without tearing down the player.

        Tick-thread-safe: only touches volume (MediaPlayer.setVolume is a
        direct native call with no main-Looper sync, so it works even while
        the screen is locked — unlike stop()/release(), which deadlock the
        tick thread against the paused main Looper). Use this at timer expiry
        on the tick thread; do the full stop()/release() teardown later on
        the main thread.
        """
        self._ramp_running = False  # stop the ramp from re-raising volume
        self._volume = 0.0
        self._target_volume = 0.0
        snd = getattr(self, "_noise_sound", None)
        if snd is not None:
            try:
                snd.volume = 0.0
            except Exception:
                logger.exception("mute: setting noise volume failed")

    def stop(self) -> None:
        """Stop all audio playback."""
        self._ramp_running = False
        if self._ramp_thread:
            self._ramp_thread.join(timeout=0.5)
            self._ramp_thread = None
        # NOTE: _bell_sound is deliberately excluded. It holds the timer-end gong
        # (SoundLoader fallback on desktop), which must keep ringing AFTER the
        # session stops — the timer-expiry path calls stop() (noise teardown) one
        # frame after starting the gong, so unloading it here cut the gong off
        # (desktop only; Android's gong uses the separate _timer_bell_player).
        # The gong is owned by play_timer_sound / stop_timer_bell instead.
        for snd_attr in ("_noise_sound", "_chime_sound", "_disconnect_sound"):
            snd = getattr(self, snd_attr, None)
            if snd:
                try:
                    snd.stop()
                    snd.unload()
                except Exception:
                    logger.exception(f"Failed to stop/unload {snd_attr}")
                setattr(self, snd_attr, None)
        self._is_playing = False
        self._volume = 0.0
        self._target_volume = 0.0
        self._test_active = False

    def test_audio(self) -> None:
        """Test all audio channels: noise volume sweep → bell → chime → disconnect.

        Demonstrates smooth volume gradient by ramping noise from silence
        to max and back down, then plays alert sounds.
        """
        was_playing = self._is_playing
        saved_volume = self._volume
        if not was_playing:
            self._is_playing = True
        self._test_active = True
        self._set_noise_volume(0.0)
        with self._lock:
            self._start_noise_loop()
        logger.info("Audio test: noise volume sweep started")

        def _run_sequence():
            # Sweep noise volume: 0 → max over half duration, max → 0 over other half
            sweep_duration = APP.AUDIO_TEST_DURATION
            step_interval = 0.05  # 50ms steps = 20 updates/sec
            n_steps = int(sweep_duration / step_interval)
            half = n_steps // 2
            for i in range(n_steps):
                if not self._test_active:
                    break
                if i <= half:
                    vol = self._max_volume * (i / half)
                else:
                    vol = self._max_volume * (1.0 - (i - half) / (n_steps - half))
                self._set_noise_volume(vol)
                time.sleep(step_interval)
            # Bell (sinking alert)
            self._set_noise_volume(0.0)
            logger.info("Audio test: sinking bell")
            self._play_bell()
            time.sleep(APP.BELL_DURATION + 0.3)
            # Chime (subtle distraction)
            logger.info("Audio test: subtle distraction chime")
            self._play_chime()
            time.sleep(APP.CHIME_DURATION + 0.3)
            # Disconnect alert (harsh warble)
            logger.info("Audio test: disconnect alert")
            self._play_disconnect()
            time.sleep(APP.DISCONNECT_DURATION + 0.3)
            self._test_active = False
            if not was_playing:
                self.stop()
            else:
                self._set_noise_volume(saved_volume)
            logger.info("Audio test complete")

        t = threading.Thread(target=_run_sequence, daemon=True)
        t.start()

    def play_timer_sound(self, custom_path: str = "") -> None:
        """Play the timer-end gong so it sounds even with the screen locked.

        On Android the gong goes through a one-shot MediaPlayer (USAGE_MEDIA),
        like the noise — SoundLoader/SDL_mixer is silenced while the screen is
        locked, so a meditation bell played that way would never be heard at
        the actual timer end. Desktop falls back to SoundLoader.

        Safe to call from the tick thread: only create()/prepare()/start()
        run here (no MediaPlayer.release(), which would deadlock against the
        paused main Looper during lock — see _release_timer_bell, which runs
        on the main thread via stop_timer_bell()).
        """
        path = custom_path if (custom_path and os.path.isfile(custom_path)) else self._timer_bell_path
        from kivy.utils import platform as kplat
        if kplat == "android":
            try:
                player = _AndroidMediaNoisePlayer(path, loop=False)
                player.volume = 1.0
                player.play()
                self._timer_bell_player = player
                logger.info("Timer gong (MediaPlayer, lock-through)")
                return
            except Exception:
                logger.exception("MediaPlayer gong failed; falling back to SoundLoader")
        if self._bell_sound:
            try:
                self._bell_sound.stop()
                self._bell_sound.unload()
            except Exception:
                logger.exception("Failed to clear prior bell before timer sound")
        self._bell_sound = self._play_sound(path, 0.9)
        logger.info("Timer gong (SoundLoader)")

    def _release_timer_bell(self) -> None:
        """Release the MediaPlayer gong. MUST run on the main thread (its
        event handler is on the main Looper; release() from the tick thread
        deadlocks while the screen is locked)."""
        player = self._timer_bell_player
        if player is None:
            return
        try:
            player.unload()
        except Exception:
            logger.exception("Failed to release timer gong player")
        self._timer_bell_player = None

    def stop_timer_bell(self) -> None:
        """Stop the timer-end bell early (e.g. user pressed a summary button).

        Safe to call when nothing is playing — references are cleared either
        way, so subsequent `_audio.start()` / new sessions don't carry a stale
        player across. Called from the main thread (summary buttons / session
        start), where releasing the MediaPlayer gong is safe.
        """
        self._release_timer_bell()
        snd = self._bell_sound
        if not snd:
            return
        try:
            snd.stop()
            snd.unload()
        except Exception:
            logger.exception("Failed to stop/unload bell")
        self._bell_sound = None

    def play_connect_sound(self) -> None:
        """Play a chime to confirm device connected."""
        self._play_chime()
        logger.info("Connect sound played")

    def play_transition_cue(self) -> None:
        """Play the chime as a program segment-transition cue."""
        self._play_chime()
        logger.info("Program transition cue played")

    def play_disconnect_alert(self) -> None:
        """Play a harsh warble when device disconnects."""
        if not self._disconnect_alert_enabled:
            return
        self._play_disconnect()
        logger.info("Disconnect alert played")

    def play_alert(self) -> None:
        """Play the disconnect warble channel briefly as a termination alert."""
        try:
            self._play_disconnect()
        except Exception:
            pass

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
    def subtle_alert_enabled(self) -> bool:
        return self._subtle_alert_enabled

    @subtle_alert_enabled.setter
    def subtle_alert_enabled(self, value: bool) -> None:
        self._subtle_alert_enabled = value

    @property
    def disconnect_alert_enabled(self) -> bool:
        return self._disconnect_alert_enabled

    @disconnect_alert_enabled.setter
    def disconnect_alert_enabled(self, value: bool) -> None:
        self._disconnect_alert_enabled = value

    def cleanup(self) -> None:
        """Stop playback, unload sounds, remove temp files."""
        self.stop()
        for path in (
            self._noise_path,
            self._bell_path,
            self._timer_bell_path,
            self._chime_path,
            self._disconnect_path,
        ):
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
    print(f"Chime WAV exists: {os.path.exists(engine._chime_path)}")
    print(f"Disconnect WAV exists: {os.path.exists(engine._disconnect_path)}")
    engine.cleanup()
    print(f"Temp cleaned: {not os.path.exists(engine._noise_path)}")
    print("Done")
