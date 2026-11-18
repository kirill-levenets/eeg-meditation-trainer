"""What a running session watches on each tick besides its metrics: the headset's link (up, lost), data going stale, a low
battery and power-line noise. Each warns once per run, its UI through the main thread."""
from unittest.mock import MagicMock

import pytest

from app.config import APP
from app.session.session_events import Alert, LinkChanged
from app.session.session_run import Phase, SessionRun
from app.session.session_watch import SessionWatch
from app.ui.headset import Headset
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
def watch():
    events = []
    stream, live_screen, device, audio = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    stream.is_connected, stream._device_address, stream._device_name = False, "AA:BB", "MWM2"
    headset = Headset(stub_context(live=lambda: True), stream, device, live_screen, serial_override=lambda: None)
    w = SessionWatch(audio, stream, headset_name=headset.name, emit=lambda run, event: events.append((run, event)))
    w.headset = headset  # what the app shows on a LinkChanged
    run = SessionRun(1)
    run.phase = Phase.STARTED
    return w, run, events, stream, live_screen, device, audio


def _shown(watch_, events) -> list[str]:
    """The alerts the events show, the headset shown again as the app does on each LinkChanged; each for its run."""
    alerts = []
    while events:
        _run, event = events.pop(0)
        if isinstance(event, LinkChanged):
            watch_.headset.show_selected()
        elif isinstance(event, Alert):
            alerts.append(event.message)
    return alerts


def test_the_link_coming_up_is_shown_in_settings_once(watch):
    w, run, queued, stream, _live, device, _audio = watch
    stream.is_connected = True
    w.follow_link(run)
    w.follow_link(run)
    _shown(w, queued)
    device.update_device_status.assert_called_once_with(True, name="MWM2")


def test_the_link_lost_mid_session_shows_reconnecting_with_the_alert(watch):
    w, run, queued, stream, live, _device, audio = watch
    stream.is_connected = True
    w.follow_link(run)
    stream.is_connected = False
    w.follow_link(run)
    _shown(w, queued)
    assert live.update_device_status.call_args == ((False,), {"device_name": "MWM2", "connecting": True})
    audio.play_disconnect_alert.assert_called_once()


def test_a_mock_session_follows_no_link_and_never_goes_stale(watch):
    # The headset's link outlives sessions: it may be up, or long silent, during a mock session.
    w, run, queued, stream, _live, device, audio = watch
    stream.is_connected, stream.seconds_since_last_packet = True, w.STALE_DATA_THRESHOLD + 1
    assert w.check(run, elapsed=0, on_headset=False) is None
    assert not queued and not run.bt_connected_notified and not run.stale_data_warned
    audio.play_disconnect_alert.assert_not_called()


def test_a_low_battery_is_warned_about_once_per_run(watch):
    w, run, queued, _stream, live, _device, _audio = watch
    for _ in range(3):
        w.check_sample(run, {"battery": 10})
    assert [r for r, _e in queued] == [run] and _shown(w, queued) == ["Low headset battery (7%)."]
    w.check_sample(SessionRun(1), {"battery": 10})  # the next run warns again
    assert _shown(w, queued) == ["Low headset battery (7%)."]


def test_no_battery_reading_warns_nothing(watch):
    w, run, queued, _stream, _live, _device, _audio = watch
    w.check_sample(run, {})  # the MindWave Mobile 2 doesn't send it
    assert not queued


def test_power_line_noise_found_is_warned_about_once(watch):
    w, run, queued, _stream, live, _device, _audio = watch
    run.noise_detector = _Detector(after=2, found=50)
    for _ in range(4):
        w.check_sample(run, {"raw_eeg_waveform": [1, 2, 3]})
    alerts = _shown(w, queued)
    assert run.noise_detector.fed == 2  # fed until it has its answer
    assert len(alerts) == 1 and "50 Hz" in alerts[0]


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
    assert w.check(run, elapsed=59, on_headset=True) is None and queued  # under it: the link is followed
    queued.clear()
    reason, alert = w.check(run, elapsed=60, on_headset=True)
    assert reason == "user" and "recording limit" in alert and not queued
    audio.play_disconnect_alert.assert_called_once()


def test_a_reconnect_mid_session_shows_the_headset_connected_again(watch):
    w, run, queued, stream, live, device, _audio = watch
    for connected in (True, False, True):
        stream.is_connected = connected
        w.follow_link(run)
    _shown(w, queued)
    assert live.update_device_status.call_args.args[0] is True  # not left "reconnecting" to the session's end
    assert device.update_device_status.call_args.args[0] is True


def test_a_drop_mid_session_is_shown_in_settings_too(watch):
    w, run, queued, stream, _live, device, _audio = watch
    for connected in (True, False):
        stream.is_connected = connected
        w.follow_link(run)
    _shown(w, queued)
    assert device.update_device_status.call_args.args[0] is False  # not still "connected"
