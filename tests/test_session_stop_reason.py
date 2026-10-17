from unittest.mock import MagicMock

import app.audio_feedback.noise as noise_mod
from app.audio_feedback.noise import AudioEngine
from app.session.manager import SessionManager, SessionState


def _make_manager():
    mgr = SessionManager.__new__(SessionManager)
    mgr._audio = MagicMock()
    mgr._state = SessionState.RUNNING
    mgr._start_time = 0.0
    mgr._elapsed = 0.0
    mgr._pause_start = 0.0
    mgr._total_paused = 0.0
    mgr._metrics_accumulator = []
    mgr._reset_scoring()
    mgr._time_shamatha_90 = 0.0
    mgr._threshold_used = 50
    mgr._active_metric = "meditation_score"
    mgr._active_target = None
    return mgr


def test_stop_user_reason_does_not_alert():
    mgr = _make_manager()
    mgr.stop(reason="user")
    mgr._audio.play_alert.assert_not_called()


def test_stop_stale_data_triggers_alert():
    mgr = _make_manager()
    mgr.stop(reason="stale_data")
    mgr._audio.play_alert.assert_called_once()


def test_stop_bt_lost_triggers_alert():
    mgr = _make_manager()
    mgr.stop(reason="bt_lost")
    mgr._audio.play_alert.assert_called_once()


def test_stop_error_triggers_alert():
    mgr = _make_manager()
    mgr.stop(reason="error")
    mgr._audio.play_alert.assert_called_once()


def test_stop_default_reason_is_user():
    mgr = _make_manager()
    mgr.stop()
    mgr._audio.play_alert.assert_not_called()


def test_set_audio_attaches_engine():
    mgr = SessionManager()
    fake_audio = MagicMock()
    mgr.set_audio(fake_audio)
    assert mgr._audio is fake_audio


def test_failure_stop_warble_survives_the_audio_teardown_that_follows_it(monkeypatch):
    # _stop_and_save stops the session (which starts the warble) and calls _audio.stop() on the next
    # line; stop() used to unload the warble milliseconds in, so a stale-data/BT-lost end was silent.
    engine = AudioEngine()
    try:
        played = []
        monkeypatch.setattr(noise_mod, "_make_noise_player",
                            lambda path, loop=True: played.append(MagicMock()) or played[-1])
        chime = MagicMock()
        engine._chime_sound = chime
        mgr = _make_manager()
        mgr._audio = engine
        mgr.stop(reason="stale_data")
        warble = played[-1]
        stops = warble.stop.call_count  # the rewind before it plays
        engine.stop()
        assert warble.stop.call_count == stops
        warble.unload.assert_not_called()
        chime.unload.assert_called_once()
    finally:
        engine.cleanup()
