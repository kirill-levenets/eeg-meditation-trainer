"""The BT wait at a session's start: the reader connects, and the first data on this connection starts the session."""
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.eeg.band_spec import BAND_KEYS
from app.logger import logger
from app.session.session_events import Connecting, Waiting
from app.session.session_run import Phase, SessionRun


@dataclass(frozen=True)
class WaitEnd:
    """How a run's BT wait ended: its first data started the session, or it gave up with the retry screen's message
    (and, for a failed connect, the diagnostic report the app files)."""

    started: bool
    message: str = ""
    report: str = ""


STARTED = WaitEnd(started=True)


class BtWait:
    """A run's CONNECTING phase, driven by the session's runner: it gives up on a refused start, a failed connect, the connect
    timeout, no data, or a headset that keeps closing the link, and says how it ended for the app to act on. Its
    overlay reaches the main thread for its run only."""

    CONNECT_TIMEOUT = 30.0  # seconds before BT socket gives up
    SIGNAL_TIMEOUT = 8.0  # seconds to wait for EEG packets after connected
    MAX_DROPS = 2  # the third drop of the link in one wait ends it: the headset keeps closing it

    def __init__(self, stream, *, headset_name: Callable[[], str], show: Callable[[object], None],
                 emit: Callable[[SessionRun, object], None]) -> None:
        self._stream = stream
        self._headset_name = headset_name
        self._show = show  # main thread: the wait's start
        self._emit = emit  # the runner: its progress, for its run

    def begin(self, run: SessionRun) -> WaitEnd | None:
        """Start the reader and show the connect overlay; the reader's refusal ends the wait before it begins."""
        name = self._headset_name()
        if not self._stream.start():
            # Nothing is connecting: entering the wait would misreport a refusal as a failed connect.
            logger.info(f"BT start refused: {self._stream._last_connect_error!r}")
            return WaitEnd(False, f"Can't connect to {name} yet.\n{self._stream._last_connect_error}")
        run.phase = Phase.CONNECTING
        self._show(Connecting(name))
        logger.info(f"Waiting for BT connection to {name}")
        return None

    def tick(self, run: SessionRun) -> WaitEnd | None:
        """Tick thread: one step of the wait, and how it ended if it did; Kivy UI goes through the main thread."""
        name = self._headset_name()
        link_dropped = not self._stream.is_connected and run.signal_start is not None
        if link_dropped and (end := self._link_dropped(run, name)):
            return end
        elapsed = time.time() - run.connect_start

        if self._stream.is_connected:
            return self._wait_for_data(run, name)
        if not self._stream._running:
            return self._connect_failed(name)
        if elapsed > self.CONNECT_TIMEOUT:
            logger.error("BT connection timed out")
            return WaitEnd(False, f"Connection to {name} timed out.\nMake sure the device is turned on\nand in range.")
        remaining = int(self.CONNECT_TIMEOUT - elapsed)
        self._emit(run, Waiting(f"Connecting to {name}...\nTimeout in {remaining}s"))
        return None

    def _link_dropped(self, run: SessionRun, name: str) -> WaitEnd | None:
        """Tick thread: the link dropped and the reader reconnects; the wait ends if the headset keeps closing it."""
        # The next connection gets its own connect and no-data windows, and only its own packets count.
        run.signal_start = None
        run.dropped_at = time.monotonic()
        run.connect_start = time.time()
        run.drops += 1
        if run.drops <= self.MAX_DROPS:
            return None
        logger.error(f"BT wait: {name} closed the connection {run.drops} times, giving up")
        return WaitEnd(False, f"{name} keeps closing the connection.\nSwitch the headset off and on, then retry.")

    def _wait_for_data(self, run: SessionRun, name: str) -> WaitEnd | None:
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
            logger.info(f"BT device {name} connected, session started")
            return STARTED
        if signal_elapsed > self.SIGNAL_TIMEOUT and not has_packets:
            # No packets: ThinkGear didn't start streaming. No RFCOMM reconnect: closing the socket triggers an EBUSY
            # that blocks reconnection for 60+ seconds; only a headset power cycle fixes it.
            logger.error("No ThinkGear packets — likely low battery or needs power cycle")
            return WaitEnd(False, "No EEG data received.\nCheck battery or restart headset.")
        # Headset streaming: no timeout, wait for contact
        wait_msg = "Place sensor on forehead..." if has_packets else f"Waiting for EEG data... {signal_remaining}s"
        logger.debug(
            f"BT signal wait: sq={sq} total={total:.0f} "
            f"packets={'yes' if has_packets else 'no'} "
            f"elapsed={signal_elapsed:.0f}s"
        )
        self._emit(run, Waiting(f"Connected to {name}\n{wait_msg}\n{sensor_contact(sq)}"))
        return None

    def _connect_failed(self, name: str) -> WaitEnd:
        """Tick thread: the connection thread ended with an error."""
        hint = self._stream._last_connect_error or "Check device is on and paired."
        logger.error("BT connection failed, session aborted")
        return WaitEnd(False, f"Connection to {name} failed.\n{hint}", report=self._connect_report(name, hint))

    def _connect_report(self, device_name: str, hint: str) -> str:
        """Fire a soft-error dialog for a failed BT connect (cooldown-gated).

        The retry overlay already tells the user *something* went wrong; this
        adds a copy-pasteable technical report so they can forward it when
        the friendly hint isn't enough.
        """
        addr = self._stream._device_address or "(unset)"
        last_err = self._stream._last_connect_error or "(none)"
        return (
            f"Device: {device_name} ({addr})\n"
            f"Hint shown to user: {hint}\n"
            f"Stream last_connect_error: {last_err}\n"
        )


def sensor_contact(signal_quality: int) -> str:
    """The connect overlay's line on the sensor's contact, from ThinkGear's signal quality (200 = none, 0 = good)."""
    if signal_quality == 200:
        return "Sensor: no contact"
    if signal_quality > 50:
        return f"Sensor: poor (quality {signal_quality})"
    if signal_quality > 0:
        return f"Sensor: fair (quality {signal_quality})"
    return "Sensor: good"
