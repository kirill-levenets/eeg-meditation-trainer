"""What a running session watches on each tick besides its metrics: the recording limit, the headset's link, data going
stale, a low headset battery and power-line noise."""
from collections.abc import Callable

from app.config import APP
from app.logger import logger
from app.session.session_run import SessionRun


class SessionWatch:
    """Tick thread: each check warns once per condition and ends the session where it must (end_session freezes it on
    this thread and saves it once on the main one); alerts and the device status reach the main thread through on_main."""

    STALE_DATA_THRESHOLD = 10.0  # seconds with no new packets before warning

    def __init__(self, stream, session_manager, audio, live_screen, device_section, *, headset_name: Callable[[], str],
                 on_main: Callable[[Callable], None], end_session: Callable[[SessionRun, str, str], None]) -> None:
        self._stream = stream
        self._session_manager = session_manager
        self._audio = audio
        self._live_screen = live_screen
        self._device_section = device_section
        self._headset_name = headset_name
        self._on_main = on_main
        self._end_session = end_session

    def at_limit(self, run: SessionRun) -> bool:
        """End a session that reached the recording limit; True if it did."""
        if self._session_manager.elapsed_seconds < APP.SESSION_MAX_SECONDS:
            return False
        logger.info(f"Session reached max duration ({APP.SESSION_MAX_SECONDS}s), auto-stopping")
        self._audio.play_disconnect_alert()
        limit_msg = (
            f"Session recording limit reached ({APP.SESSION_MAX_SECONDS // 3600}h). "
            "Session saved. Start a new one to continue."
        )
        self._end_session(run, "user", limit_msg)
        return True

    def follow_link(self, run: SessionRun) -> None:
        """The headset's link coming up (Settings shows it) and dropping during a session (the Session screen shows it
        reconnecting, with the disconnect alert)."""
        if (not run.bt_connected_notified
                and not APP.USE_MOCK_DEVICE
                and self._stream.is_connected):
            run.bt_connected_notified = True
            name = self._headset_name()
            self._on_main(lambda n=name: self._device_section.update_device_status(True, name=n))
            logger.info(f"Settings updated: {name} connected")

        if (not APP.USE_MOCK_DEVICE
                and run.bt_connected_notified
                and not self._stream.is_connected):
            run.bt_connected_notified = False
            name = self._headset_name()
            self._on_main(lambda n=name: self._live_screen.update_device_status(
                False, device_name=n, connecting=True
            ))
            self._audio.play_disconnect_alert()
            logger.warning(f"BT device {name} disconnected during session")

    def check_stale(self, run: SessionRun) -> None:
        """Auto-stop session when the real device stops sending EEG data."""
        if APP.USE_MOCK_DEVICE:
            return
        stale_secs = self._stream.seconds_since_last_packet
        if stale_secs <= 0:
            run.stale_data_warned = False
            return
        if stale_secs > self.STALE_DATA_THRESHOLD:
            if not run.stale_data_warned:
                run.stale_data_warned = True
                logger.warning(f"Stale EEG data: no packets for {stale_secs:.0f}s, auto-stopping")
                self._end_session(run, "stale_data", "No EEG data. Session stopped.\nCheck headset and battery.")
        else:
            run.stale_data_warned = False

    def check_sample(self, run: SessionRun, raw_sample: dict) -> None:
        """A low headset battery and power-line noise, each warned about once."""
        # Low battery warning (ThinkGear reports 0-127, warn below ~20%)
        battery = raw_sample.get("battery", -1)
        if battery != -1 and battery < 25 and not run.low_battery_warned:
            run.low_battery_warned = True
            pct = int(battery / 127 * 100)
            bat_msg = f"Low headset battery ({pct}%)."
            self._on_main(lambda m=bat_msg: self._live_screen.show_alert(m))
            logger.warning(f"Low headset battery: {battery}/127 ({pct}%)")

        # Feed raw waveform to power line noise detector
        detector = run.noise_detector
        if detector and not detector.ready():
            waveform = raw_sample.get("raw_eeg_waveform", [])
            if waveform:
                detector.feed(waveform)
            if detector.ready():
                detected, freq = detector.result()
                if detected:
                    noise_msg = (
                        f"Warning: {freq} Hz power line noise detected. "
                        f"Check notch filter setting or move away from electrical equipment."
                    )
                    self._on_main(lambda m=noise_msg: self._live_screen.show_alert(m))
                    logger.warning(f"Power line noise detected: {freq} Hz")
