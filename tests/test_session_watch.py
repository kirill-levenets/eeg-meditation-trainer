"""What a running session watches on each tick besides its metrics: the headset's link (up, lost), data going stale, a low
battery and power-line noise. Each warns once per run, its UI through the main thread."""
from unittest.mock import MagicMock

import pytest

from app.config import APP
from app.session.session_run import Phase, SessionRun
from app.ui.headset import Headset
from app.ui.session_watch import SessionWatch
from tests._context import stub_context


class _Detector:
    """A power-line detector that is ready after `after` feeds and finds `found` (None: nothing)."""

    def __init__(self, after: int, found: int | None) -> None:
        self.fed, self._after, self._found = 0, after, found

    def feed(self, waveform) -> None:
        self.fed += 1

    def ready(self) -> bool:
        return self.fed >= self._after

    def result(self):
        return (self._found is not None, self._found)


@pytest.fixture
def watch(monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", False)
    queued = []
    stream, live_screen, device, audio = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    stream.is_connected, stream._device_address, stream._device_name = False, "AA:BB", "MWM2"
    headset = Headset(stub_context(live=lambda: True), stream, device, live_screen, serial_override=lambda: None)
    w = SessionWatch(audio, live_screen, headset, on_main=queued.append)
    run = SessionRun(1)
    run.phase = Phase.STARTED
    return w, run, queued, stream, live_screen, device, audio


def _run_queued(queued) -> None:
    while queued:
        queued.pop(0)()


def test_the_link_coming_up_is_shown_in_settings_once(watch):
    w, run, queued, stream, _live, device, _audio = watch
    stream.is_connected = True
    w.follow_link(run)
    w.follow_link(run)
    _run_queued(queued)
    device.update_device_status.assert_called_once_with(True, name="MWM2")


def test_the_link_lost_mid_session_shows_reconnecting_with_the_alert(watch):
    w, run, queued, stream, live, _device, audio = watch
    stream.is_connected = True
    w.follow_link(run)
    stream.is_connected = False
    w.follow_link(run)
    _run_queued(queued)
    assert live.update_device_status.call_args == ((False,), {"device_name": "MWM2", "connecting": True})
    audio.play_disconnect_alert.assert_called_once()


def test_the_mock_headset_has_no_link_to_follow(watch, monkeypatch):
    monkeypatch.setattr(APP, "USE_MOCK_DEVICE", True)
    w, run, queued, stream, _live, device, audio = watch
    stream.is_connected = True
    w.follow_link(run)
    assert not queued and not run.bt_connected_notified
    audio.play_disconnect_alert.assert_not_called()


def test_a_low_battery_is_warned_about_once_per_run(watch):
    w, run, queued, _stream, live, _device, _audio = watch
    for _ in range(3):
        w.check_sample(run, {"battery": 10})
    _run_queued(queued)
    assert [c.args[0] for c in live.show_alert.call_args_list] == ["Low headset battery (7%)."]
    w.check_sample(SessionRun(1), {"battery": 10})  # the next run warns again
    _run_queued(queued)
    assert live.show_alert.call_count == 2


def test_no_battery_reading_warns_nothing(watch):
    w, run, queued, _stream, _live, _device, _audio = watch
    w.check_sample(run, {})  # the MindWave Mobile 2 doesn't send it
    assert not queued


def test_power_line_noise_found_is_warned_about_once(watch):
    w, run, queued, _stream, live, _device, _audio = watch
    run.noise_detector = _Detector(after=2, found=50)
    for _ in range(4):
        w.check_sample(run, {"raw_eeg_waveform": [1, 2, 3]})
    _run_queued(queued)
    assert run.noise_detector.fed == 2  # fed until it has its answer
    assert len(live.show_alert.call_args_list) == 1 and "50 Hz" in live.show_alert.call_args.args[0]


def test_no_noise_found_warns_nothing(watch):
    w, run, queued, _stream, _live, _device, _audio = watch
    run.noise_detector = _Detector(after=1, found=None)
    w.check_sample(run, {"raw_eeg_waveform": [1]})
    assert not queued


def test_data_flowing_again_rearms_the_stale_stop(watch):
    w, run, _queued, stream, _live, _device, _audio = watch
    stream.seconds_since_last_packet = w.STALE_DATA_THRESHOLD + 1
    assert w.check_stale(run) == ("stale_data", "No EEG data. Session stopped.\nCheck headset and battery.")
    assert w.check_stale(run) is None  # once per stall
    stream.seconds_since_last_packet = 0.3
    assert w.check_stale(run) is None
    assert not run.stale_data_warned


def test_the_recording_limit_ends_it_before_the_other_checks_run(watch, monkeypatch):
    w, run, queued, stream, _live, _device, audio = watch
    monkeypatch.setattr(APP, "SESSION_MAX_SECONDS", 60)
    stream.is_connected, stream.seconds_since_last_packet = True, 0.2
    assert w.check(run, elapsed=59) is None and queued  # under it: the link is followed
    queued.clear()
    reason, alert = w.check(run, elapsed=60)
    assert reason == "user" and "recording limit" in alert and not queued
    audio.play_disconnect_alert.assert_called_once()


def test_a_reconnect_mid_session_shows_the_headset_connected_again(watch):
    w, run, queued, stream, live, device, _audio = watch
    for connected in (True, False, True):
        stream.is_connected = connected
        w.follow_link(run)
    _run_queued(queued)
    assert live.update_device_status.call_args.args[0] is True  # not left "reconnecting" to the session's end
    assert device.update_device_status.call_args.args[0] is True


def test_a_drop_mid_session_is_shown_in_settings_too(watch):
    w, run, queued, stream, _live, device, _audio = watch
    for connected in (True, False):
        stream.is_connected = connected
        w.follow_link(run)
    _run_queued(queued)
    assert device.update_device_status.call_args.args[0] is False  # not still "connected"
