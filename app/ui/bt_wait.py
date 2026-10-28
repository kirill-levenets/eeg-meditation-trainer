"""The BT wait at a session's start: the reader connects, and the first data on this connection starts the session."""
import time
from collections.abc import Callable

from app.crash_handler import report_soft_error
from app.eeg.band_spec import BAND_KEYS
from app.logger import logger
from app.session.session_run import Phase, SessionRun


class BtWait:
    """A run's CONNECTING phase, driven by the tick thread: it gives up on a refused start, a failed connect, the connect
    timeout, no data, or a headset that keeps closing the link. Its UI reaches the main thread for its run only."""

    CONNECT_TIMEOUT = 30.0  # seconds before BT socket gives up
    SIGNAL_TIMEOUT = 8.0  # seconds to wait for EEG packets after connected
    MAX_DROPS = 2  # the third drop of the link in one wait ends it: the headset keeps closing it

    def __init__(self, stream, live_screen, *, headset_name: Callable[[], str],
                 on_main_for: Callable[[SessionRun, Callable], None], start_session: Callable[[], None],
                 on_connected: Callable[[str], None], abort: Callable[[], None],
                 undo_setup: Callable[[], None]) -> None:
        self._stream = stream
        self._live_screen = live_screen
        self._headset_name = headset_name
        self._on_main_for = on_main_for
        self._start_session = start_session  # tick thread, on the first data
        self._on_connected = on_connected  # main thread, for its run
        self._abort = abort  # the wait's teardown: the tick watcher, then the stream
        self._undo_setup = undo_setup

    def begin(self, run: SessionRun) -> bool:
        """Start the reader and show the connect overlay; False, with the session setup undone, if refused."""
        name = self._headset_name()
        if not self._stream.start():
            # Nothing is connecting: entering the wait would misreport a refusal as a failed connect.
            self._undo_setup()
            self._live_screen.update_device_status(False, device_name=name)
            self._live_screen.show_overlay_retry(
                f"Can't connect to {name} yet.\n{self._stream._last_connect_error}"
            )
            logger.info(f"BT start refused: {self._stream._last_connect_error!r}")
            return False
        run.phase = Phase.CONNECTING
        self._live_screen.update_device_status(False, device_name=name, connecting=True)
        self._live_screen.show_overlay(f"Connecting to {name}...")
        logger.info(f"Waiting for BT connection to {name}")
        return True

    def tick(self, run: SessionRun) -> None:
        """Tick thread: one step of the wait; Kivy UI goes through the main thread."""
        name = self._headset_name()
        link_dropped = not self._stream.is_connected and run.signal_start is not None
        if link_dropped and self._link_dropped(run, name):
            return
        elapsed = time.time() - run.connect_start

        if self._stream.is_connected:
            self._wait_for_data(run, name)
        elif not self._stream._running:
            self._connect_failed(run, name)
        elif elapsed > self.CONNECT_TIMEOUT:
            self._connect_timed_out(run, name)
        else:
            # Still waiting for BT socket — show countdown
            remaining = int(self.CONNECT_TIMEOUT - elapsed)
            msg = f"Connecting to {name}...\nTimeout in {remaining}s"
            self._on_main_for(run, lambda m=msg: self._live_screen.update_overlay(m))

    def _give_up(self, run: SessionRun, name: str, message: str) -> None:
        """End the wait from the tick thread with a retry screen (queued for this run only)."""
        self._abort()
        self._on_main_for(run, lambda: (
            self._undo_setup(),
            self._live_screen.update_device_status(False, device_name=name),
            self._live_screen.show_overlay_retry(message),
        ))

    def _link_dropped(self, run: SessionRun, name: str) -> bool:
        """Tick thread: the link dropped and the reader reconnects; True if the headset keeps closing it (the wait ends)."""
        # The next connection gets its own connect and no-data windows, and only its own packets count.
        run.signal_start = None
        run.dropped_at = time.monotonic()
        run.connect_start = time.time()
        run.drops += 1
        if run.drops > self.MAX_DROPS:
            self._give_up(run, name, f"{name} keeps closing the connection.\n"
                                     "Switch the headset off and on, then retry.")
            logger.error(f"BT wait: {name} closed the connection {run.drops} times, giving up")
            return True
        return False

    def _wait_for_data(self, run: SessionRun, name: str) -> None:
        """Tick thread: BT socket connected — waiting for actual EEG data; the first data starts the session."""
        if not run.signal_start:
            run.signal_start = time.time()
        signal_elapsed = time.time() - run.signal_start
        signal_remaining = int(self.SIGNAL_TIMEOUT - signal_elapsed)

        raw_sample = self._stream.read_sample()
        sq = raw_sample.get("signal_quality", 200)
        total = sum(raw_sample.get(k, 0.0) for k in BAND_KEYS)

        # Is the headset streaming packets on this connection?
        since_packet = self._stream.seconds_since_last_packet
        has_packets = 0 < since_packet < time.monotonic() - run.dropped_at

        if total > 0 and has_packets:  # data on this connection: band values outlive a drop
            self._start_session()
            run.phase = Phase.STARTED
            self._on_main_for(run, lambda n=name: self._on_connected(n))
            logger.info(f"BT device {name} connected, session started")
        elif signal_elapsed > self.SIGNAL_TIMEOUT and not has_packets:
            # No packets — ThinkGear didn't start streaming.
            # Don't try RFCOMM reconnect: closing the socket triggers
            # EBUSY that blocks reconnection for 60+ seconds.
            # The only reliable fix is a headset power cycle.
            self._give_up(run, name, "No EEG data received.\nCheck battery or restart headset.")
            logger.error("No ThinkGear packets — likely low battery or needs power cycle")
        else:
            # Show signal quality feedback (keep waiting if packets arrive)
            if has_packets:
                # Headset streaming — no timeout, wait for contact
                wait_msg = "Place sensor on forehead..."
            else:
                wait_msg = f"Waiting for EEG data... {signal_remaining}s"
            logger.debug(
                f"BT signal wait: sq={sq} total={total:.0f} "
                f"packets={'yes' if has_packets else 'no'} "
                f"elapsed={signal_elapsed:.0f}s"
            )
            msg = f"Connected to {name}\n{wait_msg}\n{sensor_contact(sq)}"
            self._on_main_for(run, lambda m=msg: self._live_screen.update_overlay(m))

    def _connect_failed(self, run: SessionRun, name: str) -> None:
        """Tick thread: the connection thread ended with an error."""
        hint = self._stream._last_connect_error or "Check device is on and paired."
        self._give_up(run, name, f"Connection to {name} failed.\n{hint}")
        logger.error("BT connection failed, session aborted")
        self._report_connect_failure(name, hint)

    def _connect_timed_out(self, run: SessionRun, name: str) -> None:
        """Tick thread: no BT socket within CONNECT_TIMEOUT."""
        self._give_up(run, name, f"Connection to {name} timed out.\n"
                                 "Make sure the device is turned on\nand in range.")
        logger.error("BT connection timed out")

    def _report_connect_failure(self, device_name: str, hint: str) -> None:
        """Fire a soft-error dialog for a failed BT connect (cooldown-gated).

        The retry overlay already tells the user *something* went wrong; this
        adds a copy-pasteable technical report so they can forward it when
        the friendly hint isn't enough.
        """
        addr = self._stream._device_address or "(unset)"
        last_err = self._stream._last_connect_error or "(none)"
        detail = (
            f"Device: {device_name} ({addr})\n"
            f"Hint shown to user: {hint}\n"
            f"Stream last_connect_error: {last_err}\n"
        )
        report_soft_error("bt_connect_failed", detail)


def sensor_contact(signal_quality: int) -> str:
    """The connect overlay's line on the sensor's contact, from ThinkGear's signal quality (200 = none, 0 = good)."""
    if signal_quality == 200:
        return "Sensor: no contact"
    if signal_quality > 50:
        return f"Sensor: poor (quality {signal_quality})"
    if signal_quality > 0:
        return f"Sensor: fair (quality {signal_quality})"
    return "Sensor: good"
