"""What a running session watches on each tick besides its metrics: the recording limit, the headset's link, data going
stale, a low headset battery and power-line noise."""
from collections.abc import Callable

from app.config import APP
from app.logger import logger
from app.session.session_run import SessionRun


class SessionWatch:
    """Tick thread: each check warns once per condition and says when the session must end, for the app to end it;
    alerts and the headset's link reach the main thread through on_main."""

    STALE_DATA_THRESHOLD = 10.0  # seconds with no new packets before warning

    def __init__(self, audio, live_screen, headset, *, on_main: Callable[[Callable], None]) -> None:
        self._stream = headset.stream  # the selected headset's link: the same object for the app's life
        self._audio = audio
        self._live_screen = live_screen
        self._headset = headset
        self._on_main = on_main

    def check(self, run: SessionRun, elapsed: float) -> tuple[str, str] | None:
        """The recording limit, the headset's link and stale data, in that order: the (reason, alert) the session must
        end with now, or None."""
        ending = self.at_limit(elapsed)
        if ending:
            return ending
        self.follow_link(run)
        return self.check_stale(run)

    def at_limit(self, elapsed: float) -> tuple[str, str] | None:
        """A session that reached the recording limit ends, saved, with the alert sound."""
        if elapsed < APP.SESSION_MAX_SECONDS:
            return None
        logger.info(f"Session reached max duration ({APP.SESSION_MAX_SECONDS}s), auto-stopping")
        self._audio.play_disconnect_alert()
        return "user", (f"Session recording limit reached ({APP.SESSION_MAX_SECONDS // 3600}h). "
                        "Session saved. Start a new one to continue.")

    def follow_link(self, run: SessionRun) -> None:
        """The headset's link coming up and dropping during a session, shown where the headset is shown (a drop as
        reconnecting, with the disconnect alert)."""
        connected = self._stream.is_connected  # read once: the reader thread moves it
        if APP.USE_MOCK_DEVICE or connected == run.bt_connected_notified:
            return
        run.bt_connected_notified = connected
        self._on_main(self._headset.show_selected)
        if connected:
            logger.info(f"BT device {self._headset.name()} connected")
        else:
            self._audio.play_disconnect_alert()
            logger.warning(f"BT device {self._headset.name()} disconnected during session")

    def check_stale(self, run: SessionRun) -> tuple[str, str] | None:
        """A session whose real headset stopped sending EEG data ends, once per stall."""
        if APP.USE_MOCK_DEVICE:
            return None
        stale_secs = self._stream.seconds_since_last_packet
        if stale_secs <= self.STALE_DATA_THRESHOLD:
            run.stale_data_warned = False
            return None
        if run.stale_data_warned:
            return None
        run.stale_data_warned = True
        logger.warning(f"Stale EEG data: no packets for {stale_secs:.0f}s, auto-stopping")
        return "stale_data", "No EEG data. Session stopped.\nCheck headset and battery."

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
