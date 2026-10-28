"""A session ends once. A check that ends it on the tick thread (data gone stale, the recording limit) freezes it there,
so no later tick ends it again while the main thread can't run (a locked phone), and every main-thread finish is for
its own run."""
from unittest.mock import MagicMock

from app.config import APP
from app.session.manager import SessionManager, SessionState
from tests._session_watch import make_watch
from tests.test_resume_mirror import _drive_tick, _make_tick_app, _metrics, _raw_sample


def _locked_app(monkeypatch):
    """A running headset session on a held main thread: what the tick queues for it waits in `queued`."""
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", False)
    app = _make_tick_app(is_paused=True)
    app._session_manager = SessionManager()
    app._session_manager.start(threshold=50)
    app._watch = make_watch(app)
    app._real_stream.seconds_since_last_packet = 0.2  # streaming
    app._ticker = MagicMock(running=True)
    app._timer_state.custom_sound_path = ""
    queued = []
    app._on_main = queued.append
    app._finalize_stop_ui = MagicMock()  # the main thread's teardown: counted, not run
    reasons = []
    persist = app._persist_session_data
    app._persist_session_data = lambda reason: (reasons.append(reason), persist(reason))[1]
    return app, queued, reasons


def _unlock(queued) -> None:
    while queued:
        queued.pop(0)()


def test_a_timer_end_after_the_data_went_stale_ends_it_once(monkeypatch):
    app, queued, reasons = _locked_app(monkeypatch)
    app._real_stream.seconds_since_last_packet = app._watch.STALE_DATA_THRESHOLD + 1
    _drive_tick(app, _raw_sample(), _metrics())  # the data went stale: the session stops here
    app._timer_state.tick.return_value = True
    _drive_tick(app, _raw_sample(), _metrics())  # a tick that would end it by the timer
    _unlock(queued)
    assert reasons == ["stale_data"]
    app._finalize_stop_ui.assert_called_once()
    assert app._session_manager.state == SessionState.FINISHED


def test_a_stale_stop_freezes_the_session_on_the_tick_thread(monkeypatch):
    # Its duration ends when the data stopped, not when the phone is unlocked; its noise goes quiet meanwhile.
    app, queued, _reasons = _locked_app(monkeypatch)
    app._real_stream.seconds_since_last_packet = app._watch.STALE_DATA_THRESHOLD + 1
    _drive_tick(app, _raw_sample(), _metrics())
    assert app._session_manager.state == SessionState.PAUSED
    app._audio.mute.assert_called_once()
    app._ticker.stop.assert_called_once()
    assert len(queued) == 1


def test_the_recording_limit_ends_it_once_however_many_ticks_pass_before_the_unlock(monkeypatch):
    app, queued, reasons = _locked_app(monkeypatch)
    monkeypatch.setattr(APP, "SESSION_MAX_SECONDS", 0)
    for _ in range(3):
        _drive_tick(app, _raw_sample(), _metrics())
    _unlock(queued)
    app._audio.play_disconnect_alert.assert_called_once()
    assert reasons == ["user"]
    app._finalize_stop_ui.assert_called_once()


def test_a_timer_finish_for_a_run_already_ended_does_nothing(monkeypatch):
    # The timer saved it on the tick thread; the profile was deleted before the main thread showed its end card.
    app, queued, _reasons = _locked_app(monkeypatch)
    app._timer_state.tick.return_value = True
    _drive_tick(app, _raw_sample(), _metrics())
    app._run = None  # its ending already ran on the main thread
    _unlock(queued)
    app._finalize_stop_ui.assert_not_called()


def test_without_a_stale_stop_the_timer_still_ends_it(monkeypatch):
    app, queued, reasons = _locked_app(monkeypatch)
    app._timer_state.tick.return_value = True
    _drive_tick(app, _raw_sample(), _metrics())
    _unlock(queued)
    assert reasons == ["timer"]
    app._finalize_stop_ui.assert_called_once()


def test_the_unfrozen_session_keeps_its_tick(monkeypatch):
    app, queued, reasons = _locked_app(monkeypatch)
    _drive_tick(app, _raw_sample(), _metrics())
    assert app._session_manager.state == SessionState.RUNNING and reasons == [] and not queued
    app._ticker.stop.assert_not_called()


def test_a_stale_stop_still_says_why(monkeypatch):
    app, queued, _reasons = _locked_app(monkeypatch)
    app._real_stream.seconds_since_last_packet = app._watch.STALE_DATA_THRESHOLD + 1
    _drive_tick(app, _raw_sample(), _metrics())
    _unlock(queued)
    assert any("No EEG data" in c.args[0] for c in app._live_screen.show_alert.call_args_list)
