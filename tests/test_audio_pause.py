"""Pause must keep the prepared feedback players: Resume brings back the same below and reward sounds (#37)."""

from unittest.mock import MagicMock

import pytest

import app.audio_feedback.noise as noise_mod
from app.audio_feedback.noise import AudioEngine
from app.session.manager import SessionState
from app.ui.app_manager import EEGMeditationApp


class _FakePlayer:
    def __init__(self, path):
        self.path = path
        self.volume = 0.0
        self.loop = False
        self.played = False
        self.stopped = False
        self.unloaded = False

    def play(self):
        self.played = True

    def stop(self):
        self.stopped = True

    def unload(self):
        self.unloaded = True


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(noise_mod, "_make_noise_player", _FakePlayer)
    e = AudioEngine()
    e.prepare_feedback({"tone": ("tone", ""), "heartbeat": ("heartbeat", "")}, "tone")
    e.set_reward("heartbeat")
    e.start()
    yield e
    e.cleanup()


def test_pause_then_resume_keeps_the_player_set_roles_and_playback(engine):
    players = dict(engine._feedback_players)
    engine.pause()
    assert engine._feedback_players == players
    assert all(p.stopped and not p.unloaded for p in players.values())
    assert all(p.volume == 0.0 for p in players.values())
    for p in players.values():
        p.played = False
    engine.resume()
    assert engine._feedback_players == players
    assert (engine._active_feedback, engine._reward_feedback) == ("tone", "heartbeat")
    assert all(p.played for p in players.values())
    assert engine.is_playing


def test_alerts_stay_silent_while_paused(engine, monkeypatch):
    rang = []
    monkeypatch.setattr(engine, "_play_bell", lambda: rang.append("bell"))
    monkeypatch.setattr(engine, "_play_chime", lambda: rang.append("chime"))
    engine.sinking_alert_enabled = True
    engine.subtle_alert_enabled = True
    engine.pause()
    engine.update_sinking(1000.0)
    engine.update_subtle_distraction(1000.0)
    assert rang == []


def test_stop_after_pause_still_tears_the_players_down(engine):
    players = list(engine._feedback_players.values())
    engine.pause()
    engine.stop()
    assert engine._feedback_players == {}
    assert all(p.unloaded for p in players)


def test_the_pause_button_twice_brings_the_same_sounds_back(engine):
    app = EEGMeditationApp.__new__(EEGMeditationApp)
    app._audio = engine
    app._session_manager = MagicMock()
    app._session_manager.state = SessionState.RUNNING
    app._session_manager.pause.side_effect = lambda: setattr(app._session_manager, "state", SessionState.PAUSED)
    app._session_manager.resume.side_effect = lambda: setattr(app._session_manager, "state", SessionState.RUNNING)
    app._live_screen = MagicMock()
    app._stop_tick_thread = MagicMock()
    app._start_tick_thread = MagicMock()
    players = dict(engine._feedback_players)

    app._on_pause()  # pause
    assert app._session_manager.state is SessionState.PAUSED
    for p in players.values():
        p.played = False
    app._on_pause()  # resume

    assert engine._feedback_players == players
    assert (engine._active_feedback, engine._reward_feedback) == ("tone", "heartbeat")
    assert all(p.played for p in players.values())


def test_resume_restores_ramp_alerts_reward_target_and_a_segment_override(engine, monkeypatch):
    rang = []
    monkeypatch.setattr(engine, "_play_bell", lambda: rang.append("bell"))
    engine.sinking_alert_enabled = True
    engine.set_active_feedback("heartbeat")  # a program segment's per-segment source
    engine._reward_target_volume = 0.2
    engine.pause()
    engine.resume()
    assert engine._active_feedback == "heartbeat"
    assert engine._reward_target_volume == 0.2
    assert engine._ramp_running and engine._ramp_thread is not None and engine._ramp_thread.is_alive()
    engine.update_sinking(1000.0)
    assert rang == ["bell"], "alerts must re-arm after resume"
