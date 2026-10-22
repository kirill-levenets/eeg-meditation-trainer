"""The tick's alerts replay one kept player each, a MediaPlayer on Android: SoundLoader there freezes a locked app."""
import threading
from unittest.mock import MagicMock

import kivy.utils
import pytest
from kivy.core.audio import SoundLoader

import app.audio_feedback.noise as noise_mod
from app.audio_feedback.noise import AudioEngine


@pytest.fixture
def made(monkeypatch) -> list[tuple[str, bool, MagicMock]]:
    made: list[tuple[str, bool, MagicMock]] = []

    def factory(path: str, loop: bool = True) -> MagicMock:
        player = MagicMock()
        made.append((path, loop, player))
        return player

    monkeypatch.setattr(noise_mod, "_make_noise_player", factory)
    return made


@pytest.fixture(autouse=True)
def soundloader(monkeypatch) -> MagicMock:
    load = MagicMock(return_value=None)  # recorded, not raised: an alert's own except would swallow a raise
    monkeypatch.setattr(SoundLoader, "load", load)
    return load


def _on_tick_thread(fn) -> None:
    tick = threading.Thread(target=fn)
    tick.start()
    tick.join(2)
    assert not tick.is_alive()


def test_a_cue_on_the_tick_thread_plays_one_shot_through_the_platform_player(made, soundloader):
    engine = AudioEngine()
    try:
        _on_tick_thread(engine.play_transition_cue)
        assert [(path, loop) for path, loop, _ in made] == [(engine._chime_path, False)]
        made[0][2].play.assert_called_once()
        soundloader.assert_not_called()
    finally:
        engine.cleanup()


def test_every_alert_replays_its_one_player_and_releases_nothing_on_the_tick(made):
    engine = AudioEngine()
    try:
        for _ in range(3):
            for alert in (engine.play_transition_cue, engine._play_bell, engine.play_alert):
                _on_tick_thread(alert)
        assert [path for path, _, _ in made] == [engine._chime_path, engine._bell_path, engine._disconnect_path]
        for _, _, player in made:
            assert player.play.call_count == 3
            player.unload.assert_not_called()
    finally:
        engine.cleanup()
    for _, _, player in made:
        player.unload.assert_called_once()  # at app exit, on the main thread


def test_on_android_an_alert_player_is_a_media_player_that_plays_once(monkeypatch):
    monkeypatch.setattr(kivy.utils, "platform", "android")
    monkeypatch.setattr(noise_mod, "_AndroidMediaNoisePlayer", lambda path, loop: ("MediaPlayer", path, loop))
    assert noise_mod._make_noise_player("chime.wav", loop=False) == ("MediaPlayer", "chime.wav", False)


@pytest.fixture
def broken_media_player(monkeypatch):
    def fail(path, loop=True):
        raise RuntimeError("MediaPlayer prepare failed")

    monkeypatch.setattr(kivy.utils, "platform", "android")
    monkeypatch.setattr(noise_mod, "_AndroidMediaNoisePlayer", fail)


def test_on_android_an_alert_whose_media_player_fails_stays_silent_rather_than_use_soundloader(
        broken_media_player, soundloader):
    engine = AudioEngine()
    try:
        _on_tick_thread(engine.play_transition_cue)
        assert engine._chime_sound is None
        soundloader.assert_not_called()
    finally:
        engine.cleanup()


def test_on_android_a_gong_whose_media_player_fails_stays_silent_rather_than_use_soundloader(
        broken_media_player, soundloader):
    engine = AudioEngine()
    try:
        _on_tick_thread(engine.play_timer_sound)
        assert engine._gong is None
        soundloader.assert_not_called()
    finally:
        engine.cleanup()


def test_on_android_the_settings_gong_test_plays_what_the_timer_end_will(broken_media_player, soundloader):
    # The gong's kept player is replayed at the timer end on the tick thread, where SoundLoader freezes a locked app;
    # and a file MediaPlayer can't play is silent there, so a SoundLoader test would promise a gong that never comes.
    engine = AudioEngine()
    try:
        engine.play_timer_sound()
        assert engine._gong is None
        soundloader.assert_not_called()
    finally:
        engine.cleanup()


def test_on_android_a_noise_loop_whose_media_player_fails_still_falls_back(broken_media_player, monkeypatch):
    monkeypatch.setattr(noise_mod, "_KivyNoisePlayer", lambda path, loop: ("SoundLoader", path, loop))
    assert noise_mod._make_noise_player("rain.wav") == ("SoundLoader", "rain.wav", True)
