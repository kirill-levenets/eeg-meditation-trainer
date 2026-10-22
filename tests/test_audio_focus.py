"""The app holds one audio-focus request: listener-less requests are one client, so per-player requests dropped the
app's focus with any player's release. It is held while the session's feedback plays and while the gong rings
(transient, other audio ducks), and given up when the last of them stops."""
import sys
import types
from unittest.mock import MagicMock

import pytest

import app.audio_feedback.noise as noise_mod
from app.audio_feedback.noise import AudioEngine, _AndroidMediaNoisePlayer, _AudioFocus

DUCK = "AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK"


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


def _manager_answering(jnius, monkeypatch, answer: str) -> MagicMock:
    manager = MagicMock()
    manager.requestAudioFocus.return_value = getattr(jnius.setdefault("android.media.AudioManager", MagicMock()), answer)
    monkeypatch.setattr(noise_mod, "on_android", lambda: True)
    monkeypatch.setattr(noise_mod, "activity", lambda: MagicMock(getSystemService=lambda _name: manager))
    return manager


def _gain_asked(jnius):
    return jnius["android.media.AudioFocusRequest$Builder"].call_args.args[0]


def _session_calls(focus: MagicMock) -> list:
    return [(c[0], c.args) for c in focus.mock_calls if c[0] in ("hold", "release") and c.args[0] == "session"]


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
        engine.pause()  # nothing plays while paused
        engine.resume()
        engine._play_bell()
        engine.play_alert()
        engine.stop()
        assert _session_calls(engine._focus) == [("hold", ("session",)), ("release", ("session",)),
                                                 ("hold", ("session",)), ("release", ("session",))]
        assert all(c.args[0] == "session" for c in engine._focus.hold.call_args_list)  # an alert holds nothing
    finally:
        engine.cleanup()


def test_a_session_with_every_channel_off_asks_for_nothing(players):
    engine = AudioEngine()
    try:
        engine._focus = MagicMock()
        engine.prepare_feedback({}, "")
        engine.start()
        engine._focus.hold.assert_not_called()
    finally:
        engine.cleanup()


def test_the_gong_ducks_other_audio_until_it_has_rung(players):
    engine = AudioEngine()
    try:
        engine._focus = MagicMock()
        engine.play_timer_sound()
        engine._focus.hold.assert_called_once_with("_gong", DUCK)
        players[0].set_on_end.call_args.args[0]()  # it plays to its end
        engine._focus.release.assert_any_call("_gong")
    finally:
        engine.cleanup()


def test_the_gong_keeps_the_focus_after_the_session_gives_it_up(jnius, monkeypatch, players):
    manager = _manager_answering(jnius, monkeypatch, "AUDIOFOCUS_REQUEST_GRANTED")
    engine = AudioEngine()
    try:
        engine.prepare_feedback({"noise": ("noise", "")}, "noise")
        engine.start()
        assert _gain_asked(jnius) == jnius["android.media.AudioManager"].AUDIOFOCUS_GAIN
        engine.play_timer_sound()  # the timer's end: the gong first, the session's stop a frame later
        engine.stop()
        assert manager.requestAudioFocus.call_count == 1
        manager.abandonAudioFocusRequest.assert_not_called()  # the gong still rings
        players[-1].set_on_end.call_args.args[0]()
        manager.abandonAudioFocusRequest.assert_called_once()
    finally:
        engine.cleanup()


def test_a_gong_alone_asks_for_transient_focus_and_gives_it_up_when_stopped(jnius, monkeypatch, players):
    manager = _manager_answering(jnius, monkeypatch, "AUDIOFOCUS_REQUEST_GRANTED")
    engine = AudioEngine()
    try:
        engine.play_timer_sound()  # the Settings Test, or a timer end with every feedback channel off
        assert _gain_asked(jnius) == getattr(jnius["android.media.AudioManager"], DUCK)
        engine.stop_timer_bell()
        manager.abandonAudioFocusRequest.assert_called_once()
    finally:
        engine.cleanup()


def test_a_refused_request_is_asked_again(jnius, monkeypatch):
    manager = _manager_answering(jnius, monkeypatch, "AUDIOFOCUS_REQUEST_FAILED")  # during a call
    focus = _AudioFocus()
    focus.hold("session")
    focus.release("session")
    focus.hold("session")  # resume
    assert manager.requestAudioFocus.call_count == 2
    focus.release("session")
    manager.abandonAudioFocusRequest.assert_not_called()


def test_the_focus_is_one_request_given_up_by_the_last_holder(jnius, monkeypatch):
    manager = _manager_answering(jnius, monkeypatch, "AUDIOFOCUS_REQUEST_GRANTED")
    focus = _AudioFocus()
    focus.hold("session")
    focus.hold("_gong", DUCK)
    assert manager.requestAudioFocus.call_count == 1
    request = manager.requestAudioFocus.call_args.args[0]
    focus.release("_chime_sound")  # an alert never held it
    focus.release("session")
    manager.abandonAudioFocusRequest.assert_not_called()
    focus.release("_gong")
    focus.release("_gong")
    manager.abandonAudioFocusRequest.assert_called_once_with(request)


def test_off_android_there_is_no_focus_to_ask_for(jnius):
    focus = _AudioFocus()
    focus.hold("session")
    focus.release("session")
    assert not jnius
