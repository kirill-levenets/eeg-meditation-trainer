"""Every BT-wait exit ends its run before it stops the stream: a wait step that read the stop would take it for a
failed connect."""

import time
from unittest.mock import MagicMock

import pytest

import app.ui.running_session as rs
from app.session.session_run import Phase, SessionRun
from app.ui.bt_wait import BtWait
from tests._app import HEADSET, frames, popups, runner_alive, start_connecting


@pytest.fixture(autouse=True)
def _reports(monkeypatch):
    """A failed connect files a diagnostic report: here it is recorded (`rs.report_soft_error`), not shown."""
    monkeypatch.setattr(rs, "report_soft_error", MagicMock())


class _Waiting:
    """The app in a start's BT wait, with no runner, so the test runs the wait's steps; `events` records whether the
    run had ended when the stream stopped, `releases` each wake-lock release."""

    def __init__(self, app, monkeypatch) -> None:
        self.app, self.events, self.releases = app, [], []
        start_connecting(app, monkeypatch)
        run, stream_stop, release = app._session.run, app._real_stream.stop, app._session.keep_awake.release

        def stop_stream():
            self.events.append(("stream_stopped", run.phase is Phase.ENDED))
            stream_stop()

        def release_lock():
            self.releases.append(True)
            release()

        monkeypatch.setattr(app._real_stream, "stop", stop_stream)
        monkeypatch.setattr(app._session.keep_awake, "release", release_lock)

    def assert_unwatched_stream_stop(self) -> None:
        assert self.events == [("stream_stopped", True)]  # the run ended first: no wait step acts on the stop
        assert not self.app._session.connecting()
        # Released by the exit itself (on the writer for a wait's give-up), and again by a cancel's shared teardown.
        assert self.releases


def test_connect_cancel_stops_watcher_before_stream(fresh_app, monkeypatch):
    waiting = _Waiting(fresh_app, monkeypatch)
    fresh_app._on_connect_cancel()
    waiting.assert_unwatched_stream_stop()
    assert fresh_app._session.run is None  # the start's run ended with it


def test_stop_during_bt_wait_stops_watcher_before_stream(fresh_app, monkeypatch):
    waiting = _Waiting(fresh_app, monkeypatch)
    assert fresh_app._live_screen._overlay.opacity == 1
    fresh_app._on_stop()
    waiting.assert_unwatched_stream_stop()
    assert fresh_app._session.run is None and fresh_app._live_screen._overlay.opacity == 0
    assert popups() == []  # no "Stop session?": nothing started


def test_a_cancel_before_any_start_is_harmless(build_app):
    """Cancel before any session (e.g. during the device scan) read an attribute only Start created."""
    app = build_app()
    assert app._session.run is None and not app._session.connecting()
    app._on_connect_cancel()  # must not raise
    assert app._session.run is None and not app._live_screen._btn_start.disabled


def test_failed_connect_exit_releases_wake_lock_and_service(fresh_app, monkeypatch):
    app = fresh_app
    waiting = _Waiting(app, monkeypatch)
    run = app._session.run
    app._real_stream._running = False  # the reader gave up
    app._real_stream._last_connect_error = "Headset is asleep or off."

    app._session._follow_bt_wait(run)  # the wait's tick that sees it

    waiting.assert_unwatched_stream_stop()
    assert run.phase is Phase.ENDED and app._session.run is run  # its teardown is queued for the main thread
    assert rs.report_soft_error.call_args.args[0] == "bt_connect_failed"
    frames()
    assert app._session.run is None and "Headset is asleep or off." in app._live_screen._overlay_status.text


def test_refused_start_undoes_setup_without_entering_the_wait(fresh_app, monkeypatch):
    app = fresh_app
    releases = []
    monkeypatch.setattr(app._session.keep_awake, "release", lambda: releases.append(True))
    monkeypatch.setattr(app._real_stream, "start", lambda: False)  # the reader refuses: its last one is still alive
    app._real_stream._last_connect_error = "Previous connection is still closing."
    app._change_setting("use_mock", False)
    app._real_stream.set_device(*HEADSET)

    app._on_start()

    assert not app._session.connecting() and app._session.run is None and not runner_alive(app)
    assert releases == [True]
    assert "still closing" in app._live_screen._overlay_status.text
    assert app._live_screen._overlay_retry_btn.parent is not None
    rs.report_soft_error.assert_not_called()  # its 60 s cooldown would hide the next real failure


def test_started_stream_enters_the_wait(fresh_app, monkeypatch):
    app = fresh_app
    releases = []
    monkeypatch.setattr(app._session.keep_awake, "release", lambda: releases.append(True))
    start_connecting(app, monkeypatch, runner=True)
    assert app._session.connecting() and runner_alive(app)
    assert app._live_screen._overlay.opacity == 1 and app._live_screen._overlay_status.text.startswith("Connecting to")
    assert releases == []


def test_a_failed_connect_is_reported_with_its_headset_and_hint(monkeypatch):
    stream = MagicMock(is_connected=False, _running=False, _device_address="AA:BB",
                       _last_connect_error="Headset is asleep or off.")
    wait = BtWait(stream, headset_name=lambda: "MWM2", show=MagicMock(), emit=MagicMock())
    run = SessionRun(1)
    run.connect_start = time.time()
    end = wait.tick(run)
    assert (end.started, end.message) == (False, "Connection to MWM2 failed.\nHeadset is asleep or off.")
    assert "MWM2 (AA:BB)" in end.report and "Headset is asleep or off." in end.report  # the app files it


def test_a_give_up_that_lost_its_run_to_a_cancel_does_nothing(fresh_app, monkeypatch):
    # The Cancel ended the run between the give-up's check and its claim (a runner slow to take it): one exit acts.
    app = fresh_app
    waiting = _Waiting(app, monkeypatch)
    run, mark = app._session.run, app._session.run.mark_ended
    app._real_stream._running = False  # the reader gave up
    app._real_stream._last_connect_error = "Headset is asleep or off."

    cancelled = []

    def cancel_claims_first():
        if not cancelled:
            cancelled.append(True)
            app._session.abort()
        return mark()

    monkeypatch.setattr(run, "mark_ended", cancel_claims_first)
    app._session._follow_bt_wait(run)
    assert waiting.events == [("stream_stopped", True)]  # the Cancel's, once
    rs.report_soft_error.assert_not_called()
