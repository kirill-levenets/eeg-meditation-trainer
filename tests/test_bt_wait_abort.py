"""Every BT-wait exit stops the tick watcher before the stream, which it would read as a failed connect."""

import time
from unittest.mock import MagicMock

import pytest

import app.ui.app_manager as am
from app.session.session_run import Phase, SessionRun
from app.ui.bt_wait import BtWait
from tests._app import HEADSET, frames, popups, start_connecting


@pytest.fixture(autouse=True)
def _reports(monkeypatch):
    """A failed connect files a diagnostic report: here it is recorded (`am.report_soft_error`), not shown."""
    monkeypatch.setattr(am, "report_soft_error", MagicMock())


class _Waiting:
    """The app in a start's BT wait, its tick thread stopped so the test runs the wait's ticks; `events` records the
    order the wait's teardown stops the tick and the stream, `releases` each wake-lock release."""

    def __init__(self, app, monkeypatch) -> None:
        self.app, self.events, self.releases = app, [], []
        start_connecting(app, monkeypatch)
        app._ticker.stop()
        tick_stop, stream_stop, release = app._ticker.stop, app._real_stream.stop, app._keep_awake.release

        def stop_tick():
            tick_stop()
            self.events.append("tick_stopped")

        def stop_stream():
            self.events.append(("stream_stopped", app._connecting(), app._ticker.running))
            stream_stop()

        def release_lock():
            self.releases.append(True)
            release()

        monkeypatch.setattr(app._ticker, "stop", stop_tick)
        monkeypatch.setattr(app._real_stream, "stop", stop_stream)
        monkeypatch.setattr(app._keep_awake, "release", release_lock)

    def assert_unwatched_stream_stop(self) -> None:
        assert self.events == ["tick_stopped", ("stream_stopped", False, False)]
        assert not self.app._connecting()
        # Released by the abort itself (on the tick thread for a wait exit), and again by a cancel's shared teardown.
        assert self.releases


def test_connect_cancel_stops_watcher_before_stream(fresh_app, monkeypatch):
    waiting = _Waiting(fresh_app, monkeypatch)
    fresh_app._on_connect_cancel()
    waiting.assert_unwatched_stream_stop()
    assert fresh_app._run is None  # the start's run ended with it


def test_stop_during_bt_wait_stops_watcher_before_stream(fresh_app, monkeypatch):
    waiting = _Waiting(fresh_app, monkeypatch)
    assert fresh_app._live_screen._overlay.opacity == 1
    fresh_app._on_stop()
    waiting.assert_unwatched_stream_stop()
    assert fresh_app._run is None and fresh_app._live_screen._overlay.opacity == 0
    assert popups() == []  # no "Stop session?": nothing started


def test_a_cancel_before_any_start_is_harmless(build_app):
    """Cancel before any session (e.g. during the device scan) read an attribute only Start created."""
    app = build_app()
    assert app._run is None and not app._connecting()
    app._on_connect_cancel()  # must not raise
    assert app._run is None and not app._live_screen._btn_start.disabled


def test_failed_connect_exit_releases_wake_lock_and_service(fresh_app, monkeypatch):
    app = fresh_app
    waiting = _Waiting(app, monkeypatch)
    run = app._run
    app._real_stream._running = False  # the reader gave up
    app._real_stream._last_connect_error = "Headset is asleep or off."

    app._follow_bt_wait(run)  # the wait's tick that sees it

    waiting.assert_unwatched_stream_stop()
    assert run.phase is Phase.ENDED and app._run is run  # its teardown is queued for the main thread
    assert am.report_soft_error.call_args.args[0] == "bt_connect_failed"
    frames()
    assert app._run is None and "Headset is asleep or off." in app._live_screen._overlay_status.text


def test_refused_start_undoes_setup_without_entering_the_wait(fresh_app, monkeypatch):
    app = fresh_app
    releases = []
    monkeypatch.setattr(app._keep_awake, "release", lambda: releases.append(True))
    monkeypatch.setattr(app._real_stream, "start", lambda: False)  # the reader refuses: its last one is still alive
    app._real_stream._last_connect_error = "Previous connection is still closing."
    app._change_setting("use_mock", False)
    app._real_stream.set_device(*HEADSET)

    app._on_start()

    assert not app._connecting() and app._run is None and not app._ticker.running
    assert releases == [True]
    assert "still closing" in app._live_screen._overlay_status.text
    assert app._live_screen._overlay_retry_btn.parent is not None
    am.report_soft_error.assert_not_called()  # its 60 s cooldown would hide the next real failure


def test_started_stream_enters_the_wait(fresh_app, monkeypatch):
    app = fresh_app
    releases = []
    monkeypatch.setattr(app._keep_awake, "release", lambda: releases.append(True))
    start_connecting(app, monkeypatch)
    assert app._connecting() and app._ticker.running
    assert app._live_screen._overlay.opacity == 1 and app._live_screen._overlay_status.text.startswith("Connecting to")
    assert releases == []


def test_a_failed_connect_is_reported_with_its_headset_and_hint(monkeypatch):
    stream = MagicMock(is_connected=False, _running=False, _device_address="AA:BB",
                       _last_connect_error="Headset is asleep or off.")
    wait = BtWait(stream, MagicMock(), headset_name=lambda: "MWM2", on_main_for=lambda run, fn: None)
    run = SessionRun(1)
    run.connect_start = time.time()
    end = wait.tick(run)
    assert (end.started, end.message) == (False, "Connection to MWM2 failed.\nHeadset is asleep or off.")
    assert "MWM2 (AA:BB)" in end.report and "Headset is asleep or off." in end.report  # the app files it
