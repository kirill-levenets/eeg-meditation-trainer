"""An alert sound replaced on the tick thread (a segment's end cue, the distraction chime, the sinking bell, the
disconnect warble) is released on the main thread: MediaPlayer.release() on the tick thread waits for the main Looper,
which a locked screen pauses, and froze the app."""
import threading
from unittest.mock import MagicMock

from kivy.clock import Clock

from app.audio_feedback.noise import AudioEngine


def _engine(monkeypatch) -> tuple[AudioEngine, MagicMock]:
    engine = AudioEngine()
    old = MagicMock()
    engine._chime_sound = old
    monkeypatch.setattr(engine, "_play_sound", lambda path, volume=0.8: "new chime")
    return engine, old


def test_a_cue_played_on_the_tick_thread_releases_the_last_one_on_the_main_thread(monkeypatch):
    engine, old = _engine(monkeypatch)
    queued = []
    monkeypatch.setattr(Clock, "schedule_once", lambda fn, *a, **k: queued.append(fn))
    released_on = []
    old.unload.side_effect = lambda: released_on.append(threading.current_thread())
    tick = threading.Thread(target=engine.play_transition_cue)
    tick.start()
    tick.join(2)
    old.stop.assert_not_called()
    old.unload.assert_not_called()
    assert engine._chime_sound == "new chime"  # the cue still plays at once
    for fn in queued:
        fn(0)  # the main thread, once it runs again
    assert released_on == [threading.main_thread()]
    old.stop.assert_called_once()


def test_on_the_main_thread_the_last_cue_is_released_at_once(monkeypatch):
    engine, old = _engine(monkeypatch)
    monkeypatch.setattr(Clock, "schedule_once", lambda *a, **k: (_ for _ in ()).throw(AssertionError("deferred")))
    engine.play_transition_cue()
    old.stop.assert_called_once()
    old.unload.assert_called_once()
    assert engine._chime_sound == "new chime"
