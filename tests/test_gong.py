"""The timer-end gong is a one-shot like the alerts: one kept player, replayed; a new file gets a new player and the
old is released on the main thread; its end reaches the Settings Test button through on_end."""
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from kivy.clock import Clock
from kivy.core.audio import SoundLoader

import app.audio_feedback.noise as noise_mod
from app.audio_feedback.noise import AudioEngine, _KivyNoisePlayer
from app.ui.app_manager import EEGMeditationApp


@pytest.fixture
def made(monkeypatch):
    made = []

    def factory(path, loop=True):
        player = MagicMock()
        player.path = path
        made.append(player)
        return player

    monkeypatch.setattr(noise_mod, "_make_noise_player", factory)
    return made


@pytest.fixture
def engine():
    eng = AudioEngine()
    yield eng
    eng.cleanup()


def _on_tick_thread(fn) -> None:
    tick = threading.Thread(target=fn)
    tick.start()
    tick.join(2)
    assert not tick.is_alive()


def test_the_gong_replays_its_one_player(made, engine):
    engine.play_timer_sound()
    engine.play_timer_sound()  # a second Test, or a timer end while a test gong still rings
    assert len(made) == 1
    assert made[0].play.call_count == 2
    made[0].unload.assert_not_called()


def test_a_new_gong_file_gets_a_new_player_and_the_old_is_released_on_the_main_thread(made, engine, tmp_path):
    custom = tmp_path / "gong.wav"
    custom.write_bytes(b"x")
    engine.play_timer_sound()
    engine.play_timer_sound(str(custom))
    assert [p.path for p in made] == [engine._timer_bell_path, str(custom)]
    made[0].unload.assert_called_once()  # this test runs on the main thread


def test_from_the_tick_thread_the_old_gong_is_released_on_the_next_frame_not_there(made, engine, tmp_path):
    custom = tmp_path / "gong.wav"
    custom.write_bytes(b"x")
    engine.play_timer_sound()
    _on_tick_thread(lambda: engine.play_timer_sound(str(custom)))
    made[0].unload.assert_not_called()  # release() on the tick thread deadlocks while the screen is locked
    Clock.tick()
    made[0].unload.assert_called_once()


def test_the_gongs_end_reaches_kivys_thread(made, engine):
    ended = []
    engine.play_timer_sound(on_end=lambda: ended.append(1))
    player_end = made[0].set_on_end.call_args.args[0]
    _on_tick_thread(player_end)  # MediaPlayer calls its completion listener on Android's main thread, not Kivy's
    assert ended == []
    Clock.tick()
    assert ended == [1]


def test_a_gong_without_on_end_clears_the_tests(made, engine):
    engine.play_timer_sound(on_end=lambda: None)
    engine.play_timer_sound()  # the timer's end after a test: the Test button isn't waiting any more
    assert made[0].set_on_end.call_args.args[0] is None


def test_stopping_the_gong_releases_it_and_the_next_one_is_fresh(made, engine):
    engine.play_timer_sound()
    engine.stop_timer_bell()
    made[0].unload.assert_called_once()
    engine.play_timer_sound()
    assert len(made) == 2


def test_on_desktop_the_apps_own_stop_is_not_the_sounds_end(monkeypatch):
    sound = SimpleNamespace(loop=False, volume=1.0, play=lambda: None, unload=lambda: None, handlers=[])
    sound.bind = lambda on_stop: sound.handlers.append(on_stop)
    sound.stop = lambda: [h(sound) for h in sound.handlers]  # Kivy's Sound fires on_stop for any stop
    monkeypatch.setattr(SoundLoader, "load", lambda _path: sound)
    player = _KivyNoisePlayer("gong.wav", loop=False)
    ended = []
    player.set_on_end(lambda: ended.append(1))
    player.stop()  # the replay's rewind, or Stop pressed
    assert ended == []
    sound.stop()  # the sound reaching its end stops itself
    assert ended == [1]


def test_the_settings_test_button_hears_the_gongs_end():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._timer_state = MagicMock(custom_sound_path="")
    app._audio = MagicMock()
    app._settings_screen = MagicMock()
    app._warn_missing_sound_files = MagicMock()
    app._on_test_timer_sound()
    on_end = app._audio.play_timer_sound.call_args.kwargs["on_end"]
    assert on_end == app._settings_screen.timer.notify_timer_sound_test_ended
