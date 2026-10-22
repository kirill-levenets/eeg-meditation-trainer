"""The app holds one audio-focus request while the session's feedback plays: per-player requests without a listener
are one client, so any player's release dropped the app's focus while the gong or the warble still played."""
import sys
import types
from unittest.mock import MagicMock

import pytest

import app.audio_feedback.noise as noise_mod
from app.audio_feedback.noise import AudioEngine, _AndroidMediaNoisePlayer, _AudioFocus


@pytest.fixture
def jnius(monkeypatch):
    """pyjnius faked: every class looked up is recorded, every call answers a mock."""
    looked_up: dict[str, MagicMock] = {}
    monkeypatch.setitem(sys.modules, "jnius", types.SimpleNamespace(
        autoclass=lambda name: looked_up.setdefault(name, MagicMock())))
    return looked_up


@pytest.fixture
def players(monkeypatch):
    made = []

    def factory(path, loop=True):
        made.append(MagicMock())
        return made[-1]

    monkeypatch.setattr(noise_mod, "_make_noise_player", factory)
    return made


def test_a_player_never_asks_for_focus(jnius):
    _AndroidMediaNoisePlayer("alert.wav", loop=False).unload()
    assert "android.media.AudioFocusRequest$Builder" not in jnius
    assert "android.media.AudioManager" not in jnius


def test_the_session_holds_focus_while_its_feedback_plays(players):
    engine = AudioEngine()
    try:
        engine._focus = MagicMock()
        engine.prepare_feedback({"noise": ("noise", "")}, "noise")
        engine.start()
        assert (engine._focus.request.call_count, engine._focus.abandon.call_count) == (1, 0)
        engine.pause()
        assert engine._focus.abandon.call_count == 1  # nothing plays while paused
        engine.resume()
        engine._play_bell()
        engine.play_alert()
        assert (engine._focus.request.call_count, engine._focus.abandon.call_count) == (2, 1)  # an alert keeps it
        engine.stop()
        assert engine._focus.abandon.call_count == 2
    finally:
        engine.cleanup()


def test_a_session_with_every_channel_off_asks_for_nothing(players):
    engine = AudioEngine()
    try:
        engine._focus = MagicMock()
        engine.prepare_feedback({}, "")
        engine.start()
        engine._focus.request.assert_not_called()
    finally:
        engine.cleanup()


def _manager_answering(jnius, monkeypatch, answer: str) -> MagicMock:
    manager = MagicMock()
    manager.requestAudioFocus.return_value = getattr(jnius.setdefault("android.media.AudioManager", MagicMock()), answer)
    monkeypatch.setattr(noise_mod, "on_android", lambda: True)
    monkeypatch.setattr(noise_mod, "activity", lambda: MagicMock(getSystemService=lambda _name: manager))
    return manager


def test_a_refused_request_is_asked_again(jnius, monkeypatch):
    manager = _manager_answering(jnius, monkeypatch, "AUDIOFOCUS_REQUEST_FAILED")  # during a call
    focus = _AudioFocus()
    focus.request()
    focus.request()  # resume
    assert manager.requestAudioFocus.call_count == 2
    focus.abandon()
    manager.abandonAudioFocusRequest.assert_not_called()


def test_the_focus_is_one_request_given_up_once(jnius, monkeypatch):
    manager = _manager_answering(jnius, monkeypatch, "AUDIOFOCUS_REQUEST_GRANTED")
    focus = _AudioFocus()
    focus.request()
    focus.request()
    assert manager.requestAudioFocus.call_count == 1
    request = manager.requestAudioFocus.call_args.args[0]
    focus.abandon()
    focus.abandon()
    manager.abandonAudioFocusRequest.assert_called_once_with(request)


def test_off_android_there_is_no_focus_to_ask_for(jnius):
    focus = _AudioFocus()
    focus.request()
    assert not jnius
