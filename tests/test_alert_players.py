"""An alert the tick plays (a program segment's end cue, the distraction chime, the sinking bell, the disconnect warble)
goes through the platform player, a MediaPlayer on Android: SDL_mixer holds its lock while the app is paused, so a
SoundLoader call from the tick thread during a screen lock stopped every Python thread and froze the app. Each alert
keeps one player and replays it, so a long locked session doesn't pile up players nobody releases."""
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
    monkeypatch.setattr(SoundLoader, "load", MagicMock(side_effect=AssertionError("SoundLoader on the tick thread")))
    return made


def _on_tick_thread(fn) -> None:
    tick = threading.Thread(target=fn)
    tick.start()
    tick.join(2)
    assert not tick.is_alive()


def test_a_cue_on_the_tick_thread_plays_one_shot_through_the_platform_player(made):
    engine = AudioEngine()
    try:
        _on_tick_thread(engine.play_transition_cue)
        assert [(path, loop) for path, loop, _ in made] == [(engine._chime_path, False)]
        made[0][2].play.assert_called_once()
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
