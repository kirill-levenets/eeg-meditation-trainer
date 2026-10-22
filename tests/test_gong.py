"""The timer-end gong is a one-shot like the alerts: one kept player, replayed; a new file gets a new player and the
old is released on the main thread; its end reaches the Settings Test button through on_end."""
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from kivy.clock import Clock
from kivy.core.audio import SoundLoader

import app.audio_feedback.noise as noise_mod
from app.audio_feedback.noise import (
    AudioEngine,
    _AndroidMediaNoisePlayer,
    _KivyNoisePlayer,
)
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
    made[0].set_on_end.assert_called_with(None)  # the old player's end can't end the new play


def test_from_the_tick_thread_the_old_gong_is_released_on_the_next_frame_not_there(made, engine, tmp_path):
    custom = tmp_path / "gong.wav"
    custom.write_bytes(b"x")
    engine.play_timer_sound()
    _on_tick_thread(lambda: engine.play_timer_sound(str(custom)))
    made[0].unload.assert_not_called()  # release() on the tick thread deadlocks while the screen is locked
    assert made[0].volume == 0.0  # silent meanwhile: no frame comes while the screen is locked
    made[0].set_on_end.assert_called_with(None)  # and its end can't end the new play meanwhile
    Clock.tick()
    made[0].unload.assert_called_once()


def test_stopping_the_gong_from_the_tick_thread_releases_it_on_the_next_frame(made, engine):
    engine.play_timer_sound()
    _on_tick_thread(engine.stop_timer_bell)
    made[0].unload.assert_not_called()
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


def test_a_timer_gong_over_a_test_gong_ends_the_test_once(made, engine):
    ended = []
    engine.play_timer_sound(on_end=lambda: ended.append(1))
    player_end = made[0].set_on_end.call_args.args[0]
    engine.play_timer_sound()  # the timer ends while the Settings Test still rings
    Clock.tick()
    assert ended == [1]
    player_end()  # the timer's gong plays out: the Test isn't waiting any more
    Clock.tick()
    assert ended == [1]


def test_releasing_the_gong_ends_its_test(made, engine):
    ended = []
    engine.play_timer_sound(on_end=lambda: ended.append(1))
    engine.stop_timer_bell()  # a session start or a summary button while the Test rings
    Clock.tick()
    assert ended == [1]


def _failing_for(bad_path, made):
    def factory(path, loop=True):
        if path == bad_path:
            raise RuntimeError("MediaPlayer can't prepare it")
        made.append(MagicMock(path=path))
        return made[-1]
    return factory


def test_a_custom_gong_that_cant_play_rings_the_default(made, engine, tmp_path, monkeypatch):
    bad = tmp_path / "gong.xyz"
    bad.write_bytes(b"x")
    monkeypatch.setattr(noise_mod, "_make_noise_player", _failing_for(str(bad), made))
    engine.play_timer_sound()
    ended = []
    assert engine.play_timer_sound(str(bad), on_end=lambda: ended.append(1)) == engine._timer_bell_path
    assert [p.path for p in made] == [engine._timer_bell_path]  # the kept player stays: nothing rebuilt
    assert engine._gong is made[0] and engine._one_shot_paths["_gong"] == engine._timer_bell_path
    made[0].unload.assert_not_called()
    assert made[0].play.call_count == 2
    Clock.tick()
    assert ended == []  # the default gong rings for the Test
    made[0].set_on_end.call_args.args[0]()
    Clock.tick()
    assert ended == [1]


def test_a_gong_that_wont_start_has_not_played(made, engine, tmp_path, monkeypatch):
    custom = tmp_path / "gong.wav"
    custom.write_bytes(b"x")

    def factory(path, loop=True):
        made.append(MagicMock(path=path))
        if path == str(custom):
            made[-1].play.side_effect = RuntimeError("start() in a bad state")
        return made[-1]
    monkeypatch.setattr(noise_mod, "_make_noise_player", factory)
    assert engine.play_timer_sound(str(custom)) == engine._timer_bell_path


def test_an_android_player_whose_start_fails_says_so(monkeypatch):
    monkeypatch.setitem(sys.modules, "jnius", SimpleNamespace(autoclass=lambda _name: MagicMock()))
    player = _AndroidMediaNoisePlayer("gong.wav", loop=False)
    player._mp.start.side_effect = RuntimeError("IllegalStateException")
    with pytest.raises(RuntimeError):
        player.play()
    assert not player._playing


def test_releasing_an_android_player_builds_no_listener(monkeypatch):
    monkeypatch.setitem(sys.modules, "jnius", SimpleNamespace(autoclass=lambda _name: MagicMock()))
    player = _AndroidMediaNoisePlayer("chime.wav", loop=False)
    player.set_on_end(None)  # _release on an alert that never had one
    player._mp.setOnCompletionListener.assert_not_called()


def test_when_no_gong_can_play_the_test_still_ends(made, engine, monkeypatch):
    monkeypatch.setattr(noise_mod, "_make_noise_player", _failing_for(engine._timer_bell_path, made))
    ended = []
    assert engine.play_timer_sound(on_end=lambda: ended.append(1)) == ""
    Clock.tick()
    assert ended == [1]


def test_stopping_the_gong_releases_it_and_the_next_one_is_fresh(made, engine):
    engine.play_timer_sound()
    engine.stop_timer_bell()
    made[0].unload.assert_called_once()
    engine.play_timer_sound()
    assert len(made) == 2


def test_on_desktop_the_apps_own_stop_is_not_the_sounds_end(monkeypatch):
    sound = _sdl_sound("SoundSDL2", 4.0)
    sound.handlers = []
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
    player.set_on_end(None)  # released or replaced
    sound.stop()
    assert ended == [1]


def _sdl_sound(kind: str, length: float):
    """A Kivy SDL Sound as SoundLoader returns it: SoundSDL2 for wav/flac/mp3/ogg, MusicSDL2 for MIDI and trackers."""
    return type(kind, (SimpleNamespace,), {})(loop=False, volume=1.0, length=length, play=lambda: None,
                                              stop=lambda: None, unload=lambda: None, bind=lambda **_k: None)


def test_on_desktop_a_gong_sdl_cannot_decode_rings_the_default(engine, monkeypatch, tmp_path):
    broken = tmp_path / "gong.mp3"
    broken.write_bytes(b"not audio")
    # SDL hands back an empty Sound for a file it can't decode, and logs "Unable to load"
    monkeypatch.setattr(SoundLoader, "load", lambda path: _sdl_sound("SoundSDL2", 0 if path == str(broken) else 4.0))
    assert engine.play_timer_sound(str(broken)) == engine._timer_bell_path


def test_on_desktop_a_midi_gong_plays_though_sdl_reports_no_length(monkeypatch):
    monkeypatch.setattr(SoundLoader, "load", lambda _path: _sdl_sound("MusicSDL2", 0))
    _KivyNoisePlayer("gong.mid", loop=False)  # doesn't raise


def test_on_desktop_a_replay_is_not_the_sounds_end(monkeypatch):
    sound = _sdl_sound("SoundSDL2", 4.0)
    sound.handlers = []
    sound.bind = lambda on_stop: sound.handlers.append(on_stop)
    sound.play = lambda: [h(sound) for h in sound.handlers]  # Kivy's play() stops a sound still playing first
    monkeypatch.setattr(SoundLoader, "load", lambda _path: sound)
    player = _KivyNoisePlayer("gong.wav", loop=False)
    ended = []
    player.set_on_end(lambda: ended.append(1))
    player.play()
    assert ended == []


def test_a_new_gong_is_built_outside_the_one_shot_lock(engine, monkeypatch, tmp_path):
    custom = tmp_path / "gong.wav"
    custom.write_bytes(b"x")
    held = []

    def factory(path, loop=True):
        held.append(engine._one_shot_lock.locked())  # SDL decodes the whole file: a release mustn't wait on it
        return MagicMock(path=path)
    monkeypatch.setattr(noise_mod, "_make_noise_player", factory)
    engine.play_timer_sound()
    engine.play_timer_sound(str(custom))
    assert held == [False, False]


def test_the_settings_test_button_hears_the_gongs_end():
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._timer_state = MagicMock(custom_sound_path="")
    app._audio = MagicMock()
    app._settings_screen = MagicMock()
    app._warn_missing_sound_files = MagicMock()
    app._on_test_timer_sound()
    on_end = app._audio.play_timer_sound.call_args.kwargs["on_end"]
    assert on_end == app._settings_screen.timer.notify_timer_sound_test_ended



@pytest.mark.parametrize("custom, exists, played, said", [
    ("gong.xyz", True, "default", "Custom timer sound can't be played"),  # the default rang instead
    ("gong.xyz", True, "", "The timer sound can't be played."),  # nothing rang
    ("", False, "", "The timer sound can't be played."),
    ("gong.xyz", True, "custom", None),
    ("gong.xyz", False, "default", None),  # missing: _warn_missing_sound_files says so
    ("", False, "default", None),
])
def test_the_settings_test_says_what_it_could_not_play(monkeypatch, tmp_path, custom, exists, played, said):
    reported = []
    monkeypatch.setattr("app.ui.app_manager.report_soft_error", lambda label, detail, **k: reported.append(detail))
    path = str(tmp_path / custom) if custom else ""
    if exists:
        (tmp_path / custom).write_bytes(b"x")
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._timer_state = MagicMock(custom_sound_path=path)
    app._audio = MagicMock()
    app._audio.play_timer_sound.return_value = {"default": "/tmp/timer_bell.wav", "custom": path, "": ""}[played]
    app._settings_screen = MagicMock()
    app._warn_missing_sound_files = MagicMock()
    app._on_test_timer_sound()
    assert [d.split(":")[0] if ":" in d else d for d in reported] == ([said] if said else [])
