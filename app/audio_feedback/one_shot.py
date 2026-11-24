"""A one-shot sound's slot (the sinking bell, the chime, the disconnect warble, the timer gong): its one player,
replayed while the file is the same, safe from the session's runner."""
import threading
from collections.abc import Callable

from app.audio_feedback import players
from app.audio_feedback.players import AudioFocus
from app.logger import logger


class OneShot:
    """A replay ends the play before it. Its player is built outside the lock (SDL decodes the whole file) and a release
    meanwhile calls it off; a player is released on the main thread only (release() elsewhere deadlocks during a lock)."""

    def __init__(self, name: str, focus: AudioFocus) -> None:
        self.name = name  # in the log, and its audio-focus holder's name
        self._focus = focus
        self._lock = threading.Lock()
        self._player = None
        self._path: str | None = None  # the file the kept player plays
        self._on_end: Callable[[], None] | None = None  # the current play's
        self._gen = 0  # bumped by each release: a player built meanwhile is called off

    @property
    def player(self):
        return self._player

    def play(self, path: str, volume: float, on_end: Callable[[], None] | None = None, focus: str = "") -> bool:
        """Replay the kept player, a new file in a new one (a MediaPlayer on Android); False if it can't play.
        With `focus` (a gain), the app's audio focus is held for it until its play is over."""
        self.end()
        try:
            with self._lock:
                snd = self._player
                kept = snd is not None and self._path == path
                gen = self._gen
            if not kept:
                # Built outside the lock and before the kept one goes: a failure keeps it.
                snd = players.make_player(path, loop=False)
                with self._lock:
                    called_off = self._gen != gen
                    if not called_off:
                        old, self._player, self._path = self._player, snd, path
                if called_off:  # released while it was built: the app stopped this sound, nothing failed
                    self._release_player(snd)
                    if on_end is not None:
                        players.next_frame(on_end)
                    return True
                if old is not None:
                    self._release_player(old)
        except Exception as e:
            logger.warning(f"Failed to open sound {path}: {e}")
            return False
        try:
            snd.volume = volume
            snd.stop()  # rewinds a replay
            if on_end is not None:
                self._on_end = on_end
            if on_end is not None or focus:
                snd.set_on_end(self.end)
            if focus:
                self._focus.hold(self.name, focus)
            snd.play()
            return True
        except Exception as e:
            self._on_end = None
            logger.warning(f"Failed to play sound {path}: {e}")
            self.release()  # a player that can't start is built afresh next time
            return False

    def end(self) -> None:
        """Its play is over (played out, replayed or released): its focus goes, its on_end runs once."""
        self._focus.release(self.name)
        with self._lock:
            on_end, self._on_end = self._on_end, None
        if on_end is not None:
            players.next_frame(on_end)

    def release(self) -> None:
        """Stop and release its player, or call off one being built; the next play builds a new one."""
        with self._lock:
            snd, self._player, self._path = self._player, None, None
            self._gen += 1
        self.end()
        if snd:
            self._release_player(snd)

    def _release_player(self, player) -> None:
        """Release a player on the main thread; it ends no play."""
        try:
            player.set_on_end(None)
            if threading.current_thread() is not threading.main_thread():
                player.volume = 0.0  # silent now: no frame comes while the screen is locked, setVolume is safe here
                players.next_frame(lambda: self._release_player(player))
                return
            player.unload()  # stops it first
        except Exception:
            logger.exception(f"Failed to release {self.name}")
