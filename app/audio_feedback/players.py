"""The platform's sound players (a MediaPlayer on Android, SoundLoader on desktop), a loop or a one-shot, and the
app's one audio-focus request."""

import threading

from kivy.clock import Clock

from app import android_jni
from app.logger import logger


class RepeatedError:
    """For a call that repeats (a volume ramp step every 25 ms): its failure is logged when the message changes, and a
    success forgets the last one."""

    def __init__(self) -> None:
        self._last: str | None = None

    def is_new(self, error: Exception) -> bool:
        new, self._last = str(error) != self._last, str(error)
        return new

    def clear(self) -> None:
        self._last = None


class _KivyNoisePlayer:
    """Kivy SoundLoader-backed player: a noise loop or a one-shot alert. Used on desktop platforms."""

    def __init__(self, path: str, loop: bool = True) -> None:
        from kivy.core.audio import SoundLoader  # noqa: PLC0415 - desktop only: it loads Kivy's audio provider
        snd = SoundLoader.load(path)
        # SoundSDL2 (wav, flac, mp3, ogg) loads a file it can't decode at length 0; MusicSDL2 never reports a length
        if snd is None or (type(snd).__name__ == "SoundSDL2" and not snd.length):
            raise RuntimeError(f"SoundLoader could not load {path!r}")
        snd.loop = loop
        self._snd = snd
        self._on_end = None
        self._stopping = False  # the app's own stop: Sound fires on_stop for it too, not only at the sound's end
        snd.bind(on_stop=self._stopped)

    def set_on_end(self, callback) -> None:
        self._on_end = callback

    def _stopped(self, *_args) -> None:
        if not self._stopping and self._on_end is not None:
            self._on_end()

    @property
    def volume(self) -> float:
        return self._snd.volume

    @volume.setter
    def volume(self, v: float) -> None:
        self._snd.volume = max(0.0, min(1.0, float(v)))

    def play(self) -> None:
        self._own(self._snd.play)  # Sound.play() first stops a sound still playing

    def stop(self) -> None:
        self._own(self._snd.stop)

    def _own(self, action) -> None:
        """The app's own play or stop, which fires on_stop like the sound's end does."""
        self._stopping = True
        try:
            action()
        finally:
            self._stopping = False

    def unload(self) -> None:
        try:
            self.stop()
            self._snd.unload()
        except Exception:
            logger.exception("SoundLoader stop or unload failed")


def _media_attributes():
    """The players' audio attributes, which the focus request names too: USAGE_MEDIA plays through a lock."""
    from jnius import autoclass  # noqa: PLC0415 - Android only (pyjnius)
    AudioAttributes = autoclass("android.media.AudioAttributes")
    return (autoclass("android.media.AudioAttributes$Builder")()
            .setUsage(AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
            .build())


class _AndroidMediaNoisePlayer:
    """MediaPlayer-backed player. USAGE_MEDIA so it keeps playing through
    screen lock (SDL_mixer/SoundLoader is silenced while locked). Used for the
    looping noise (loop=True), the one-shot timer gong and the alerts (loop=False)."""

    def __init__(self, path: str, loop: bool = True) -> None:
        from jnius import autoclass  # noqa: PLC0415 - Android only (pyjnius)
        MediaPlayer = autoclass("android.media.MediaPlayer")

        self._mp = MediaPlayer()  # a failed setup leaves it to GC: its finalizer releases it, off the session's runner
        self._mp.setAudioAttributes(_media_attributes())
        self._mp.setDataSource(path)
        self._mp.setLooping(loop)
        self._mp.prepare()  # synchronous — fine for small WAV files
        self._volume: float = 0.0
        self._mp.setVolume(0.0, 0.0)
        self._playing: bool = False
        self._on_end = None
        self._listener = None  # kept: a listener nothing references is collected while Java still holds it
        self._volume_error = RepeatedError()  # a player in an error state fails at every ramp step

    def set_on_end(self, callback) -> None:
        """Called on Android's main thread when a one-shot plays to its end (a loop never ends)."""
        self._on_end = callback
        if callback is not None and self._listener is None:
            self._listener = _completion_listener(self._ended)
            self._mp.setOnCompletionListener(self._listener)

    def _ended(self) -> None:
        self._playing = False
        if self._on_end is not None:
            self._on_end()

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, v: float) -> None:
        v = max(0.0, min(1.0, float(v)))
        self._volume = v
        try:
            self._mp.setVolume(v, v)
        except Exception as e:
            if self._volume_error.is_new(e):
                logger.debug(f"Player volume not set (a released player keeps none): {e}")
        else:
            self._volume_error.clear()

    def play(self) -> None:
        self._mp.start()
        self._playing = True

    def stop(self) -> None:
        try:
            if self._playing:
                self._mp.pause()
                self._mp.seekTo(0)
                self._playing = False
        except Exception as e:
            logger.debug(f"Player not stopped (a released player has nothing to stop): {e}")

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


def _completion_listener(on_complete):
    """A MediaPlayer.OnCompletionListener calling on_complete; jnius is imported here, as only Android has it."""
    from jnius import PythonJavaClass, java_method  # noqa: PLC0415 - Android only (pyjnius)

    class _Completion(PythonJavaClass):
        __javainterfaces__ = ["android/media/MediaPlayer$OnCompletionListener"]

        @java_method("(Landroid/media/MediaPlayer;)V")
        def onCompletion(self, _player):
            on_complete()

    return _Completion()


class AudioFocus:
    """The app's one audio-focus request (listener-less requests are one client), held while any holder plays."""

    def __init__(self) -> None:
        self._mgr = None
        self._request = None
        self._holders: set[str] = set()
        self._lock = threading.Lock()  # the session holds on the main thread, the gong on the tick or Android's

    def hold(self, holder: str, gain: str = "AUDIOFOCUS_GAIN") -> None:
        """`holder` plays: ask for focus unless held; the first holder's `gain` stands. Refused, the next hold asks."""
        with self._lock:
            self._holders.add(holder)
            if self._request is None and android_jni.on_android():
                self._ask(gain)

    def release(self, holder: str) -> None:
        """`holder` stopped playing; the last one out gives the focus up."""
        with self._lock:
            self._holders.discard(holder)
            if self._holders or self._request is None:
                return
            try:
                self._mgr.abandonAudioFocusRequest(self._request)
            except Exception:
                logger.exception("Abandoning audio focus failed")
            self._mgr = self._request = None

    def _ask(self, gain: str) -> None:
        try:
            from jnius import autoclass  # noqa: PLC0415 - Android only (pyjnius)
            AudioManager = autoclass("android.media.AudioManager")
            request = (autoclass("android.media.AudioFocusRequest$Builder")(getattr(AudioManager, gain))
                       .setAudioAttributes(_media_attributes())
                       .build())
            mgr = android_jni.activity().getSystemService(autoclass("android.content.Context").AUDIO_SERVICE)
            if mgr.requestAudioFocus(request) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED:
                logger.info("Audio focus refused (a call?); the next start, resume or gong asks again")
                return
            self._mgr, self._request = mgr, request
        except Exception as e:
            logger.warning(f"Audio focus request failed (non-fatal, the sound plays anyway): {e}")


def next_frame(fn) -> None:
    """Run `fn` on Kivy's thread at the next frame."""
    Clock.schedule_once(lambda _dt: fn(), 0)


def make_player(path: str, loop: bool = True):
    """Return the right player for this platform: a noise loop, or a one-shot alert (loop=False).

    On Android, tries MediaPlayer first (survives screen lock). A loop falls back
    to SoundLoader if MediaPlayer init fails; a one-shot raises. Desktop always
    uses SoundLoader.
    """
    if android_jni.on_android():
        try:
            return _AndroidMediaNoisePlayer(path, loop)
        except Exception as e:
            if not loop:
                raise  # a one-shot plays off the main thread, where SoundLoader on Android can freeze the app
            logger.warning(f"Falling back to SoundLoader for {path}: {e}")
    return _KivyNoisePlayer(path, loop)
