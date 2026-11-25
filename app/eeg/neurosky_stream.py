"""The real headset's stream: one reader thread that connects to the MindWave over its link (`bt_links`), parses its
ThinkGear packets (`thinkgear`) and keeps the latest sample: 8 band powers, attention and meditation, signal quality,
battery and the raw wave."""
import threading
import time

from app import android_jni
from app.eeg import bt_links
from app.eeg.thinkgear import BAND_NAMES, ThinkGearParser
from app.logger import logger


def connect_error_text(error: Exception) -> str:
    """What the screen says about a failed connect."""
    text = str(error)
    if "Host is down" in text:
        return "Headset is asleep or off.\nTurn it on and retry."
    if "Device or resource busy" in text:
        return "Bluetooth busy.\nWait 15 seconds and retry."
    if "timed out" in text.lower():
        return "Connection timed out.\nCheck headset is on and in range."
    return "Check headset is on and paired."


class NeuroSkyStream:
    """Bluetooth RFCOMM stream to NeuroSky MindWave Mobile 2.

    Interface matches MockEEGStream: start(), stop(), is_connected, read_sample().
    """

    _STOP_JOIN_TIMEOUT: float = 5.0

    def __init__(self) -> None:
        self._running: bool = False
        self._connected: bool = False
        self._start_time: float = 0.0
        self._sample_count: int = 0
        self._parser: ThinkGearParser = ThinkGearParser()
        self._thread: threading.Thread | None = None
        self._lock: threading.Lock = threading.Lock()
        self._device_address: str | None = None
        self._device_name: str | None = None

        # Latest consolidated sample (updated by reader thread)
        self._latest_bands: dict[str, float] = dict.fromkeys(BAND_NAMES, 0.0)
        self._latest_attention: float = 0.0
        self._latest_meditation: float = 0.0
        self._latest_signal_quality: int = 200
        self._raw_wave_buffer: list[int] = []
        self._last_packet_time: float = 0.0  # monotonic time of last parsed packet
        self._last_connect_error: str = ""  # human-readable error from last failed connect
        self._battery_level: int = -1  # 0-127 from ThinkGear, -1 = unknown

        self._link: bt_links.Link | None = None  # to the selected headset, made at start(): one at a time
        self._read_count: int = 0
        self._bytes_read: int = 0
        self._rate_window_start: float = 0.0
        # Connect generation: a reader that outlives its stop() closes its link, never adopts it.
        self._connect_epoch: int = 0
        # Set by stop() so a connect in flight and the reader's back-off sleeps end at once.
        self._stop_event = threading.Event()

    def set_device(self, address: str | None, name: str = "") -> None:
        """Set the target Bluetooth device address (None: no headset); a link to another one closes, so the next start
        reaches this one."""
        if self._running and address != self._device_address:
            self.stop()
        self._device_address = address
        self._device_name = name or address
        logger.info(f"NeuroSky device set: {self._device_name} ({address})" if address else "NeuroSky device cleared")

    def start(self) -> bool:
        """Start the reader thread; False (with _last_connect_error set) if it was refused."""
        if self._running:
            return True
        if self._thread is not None and self._thread.is_alive():
            # A second reader would race the closing one for the headset's only channel.
            logger.warning("NeuroSky start ignored: previous reader thread still alive")
            self._last_connect_error = "Previous connection is still closing.\nRetry in a few seconds."
            return False
        if not self._device_address:
            logger.warning("NeuroSky start failed: no device address set")
            self._last_connect_error = "No device selected.\nPick one in Settings > Device."
            return False
        self._stop_event.clear()
        self._running = True
        self._start_time = time.time()
        self._parser = ThinkGearParser()
        # Stale data from a previous session must not pass the signal-wait check as data flowing.
        self.reset_sample_state()
        self._link = bt_links.link_for(self._device_address, self._device_name or self._device_address,
                                       self._stop_event)
        self._connect_epoch += 1
        self._thread = threading.Thread(
            target=self._read_loop, args=(self._connect_epoch,), daemon=True
        )
        self._thread.start()
        logger.info(f"NeuroSky stream started (epoch {self._connect_epoch})")
        return True

    def stop(self) -> None:
        """Stop the reader thread and close the link."""
        self._running = False
        self._connected = False
        self._stop_event.set()
        # Close before the join so the reader's blocked connect()/read() aborts (Link.close).
        self._connect_epoch += 1
        self._close_link()
        # Local copy: the session's runner and the main thread can both be in stop().
        t = self._thread
        if t is not None:
            t.join(timeout=self._STOP_JOIN_TIMEOUT)
            if t.is_alive():
                # Keep the reference: start() must refuse until this reader exits.
                logger.warning(
                    f"NeuroSky reader thread did not exit within {self._STOP_JOIN_TIMEOUT:.0f}s"
                )
            elif self._thread is t:
                self._thread = None
        self._close_link()
        logger.info("NeuroSky stream stopped")

    def _close_link(self) -> None:
        link = self._link
        if link is not None:
            link.close()

    def reset_sample_state(self) -> None:
        """Clear cached sample data between sessions (connection stays alive)."""
        with self._lock:
            self._latest_bands = dict.fromkeys(BAND_NAMES, 0.0)
            self._latest_attention = 0.0
            self._latest_meditation = 0.0
            self._latest_signal_quality = 200
            self._raw_wave_buffer.clear()
            self._last_packet_time = 0.0
            self._sample_count = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def seconds_since_last_packet(self) -> float:
        """Seconds elapsed since last parsed EEG packet (monotonic)."""
        if self._last_packet_time == 0.0:
            return 0.0
        return time.monotonic() - self._last_packet_time

    def read_sample(self) -> dict:
        """Return the latest consolidated EEG sample.

        Returns a dict matching MockEEGStream format:
        delta, theta, alpha1, alpha2, beta1, beta2, gamma1, gamma2,
        attention, meditation, timestamp, signal_quality
        """
        with self._lock:
            sample: dict = {}
            sample["timestamp"] = time.time() - self._start_time
            for name in BAND_NAMES:
                sample[name] = self._latest_bands.get(name, 0.0)
            sample["attention"] = self._latest_attention
            sample["meditation"] = self._latest_meditation
            sample["signal_quality"] = self._latest_signal_quality
            sample["battery"] = self._battery_level
            # Drain raw wave buffer for waveform graph
            if self._raw_wave_buffer:
                sample["raw_eeg_waveform"] = list(self._raw_wave_buffer)
                self._raw_wave_buffer.clear()
            self._sample_count += 1
            return sample

    def _superseded(self, epoch: int) -> bool:
        return epoch != self._connect_epoch

    def _read_loop(self, epoch: int) -> None:
        """Reader thread for connect generation `epoch`; once superseded it closes its link, never adopts it."""
        if not self._first_connect(epoch):
            return
        self._read_count = 0
        self._bytes_read = 0
        self._rate_window_start = time.monotonic()
        self._boost_thread_priority()
        first_read_logged = False
        while self._running and not self._superseded(epoch):
            try:
                data = self._link.read(512)
                if not data:
                    time.sleep(0.01)
                    continue
                if not first_read_logged:
                    logger.debug(f"BT first read: {len(data)} bytes")
                    first_read_logged = True
                self._read_count += 1
                self._bytes_read += len(data)
                self._log_throughput()
                for pkt in self._parser.feed(data):
                    self._apply_packet(pkt)
            except Exception as e:
                if not self._running or self._superseded(epoch):
                    break  # the link closed by stop(), not a real error
                logger.error(f"NeuroSky read error: {e}")
                self._connected = False
                self._stop_event.wait(2.0)
                if self._running and not self._superseded(epoch) and not self._reconnect(epoch):
                    break
        self._close_link()
        # Also covers a stop() that landed between the epoch check and `_connected = True`.
        self._connected = False

    def _first_connect(self, epoch: int) -> bool:
        """Connect for `epoch`: True once connected; a failure says why (_last_connect_error), a stop closes."""
        try:
            self._link.connect()
        except Exception as e:
            if self._superseded(epoch):
                logger.info(f"NeuroSky connect aborted (epoch {epoch} superseded)")
                self._close_link()
                return False
            logger.error(f"NeuroSky BT connect failed: {e}")
            self._last_connect_error = connect_error_text(e)
            self._running = False
            self._connected = False
            return False
        if self._superseded(epoch) or not self._running:
            logger.warning(
                f"NeuroSky connect superseded (epoch {epoch} != {self._connect_epoch}); "
                "closing the orphaned link"
            )
            self._close_link()
            return False
        self._last_connect_error = ""
        self._connected = True
        logger.info("NeuroSky BT connected, reading packets...")
        return True

    def _reconnect(self, epoch: int) -> bool:
        """After a read error, the link opened again: True if it is (a stop meanwhile closes it), else the reader ends."""
        try:
            self._close_link()
            self._link.connect()
            if self._superseded(epoch):
                self._close_link()
                return False
            self._connected = True
            logger.info("NeuroSky reconnected")
            return True
        except Exception as re:
            if not self._superseded(epoch):
                logger.error(f"NeuroSky reconnect failed: {re}")
                self._running = False
            return False

    @staticmethod
    def _boost_thread_priority() -> None:
        """Run the reader at Android priority -8, like the NeuroSky SDK's, so Kivy's renderer can't starve it."""
        if not android_jni.on_android():
            return
        try:
            from jnius import autoclass  # noqa: PLC0415 - Android only (pyjnius)
            autoclass("android.os.Process").setThreadPriority(-8)
        except Exception as e:
            logger.debug(f"Thread priority boost skipped: {e}")

    def _log_throughput(self) -> None:
        """Log read throughput and the link's backlog high-water mark."""
        now = time.monotonic()
        window = now - self._rate_window_start
        if window < 30.0:
            return
        logger.info(
            f"BT throughput: {self._bytes_read / window:.0f} B/s, "
            f"{self._bytes_read / max(1, self._read_count):.0f} B/read, "
            f"backlog high-water {self._link.take_high_water()} B"
        )
        self._rate_window_start = now
        self._bytes_read = 0
        self._read_count = 0

    def _apply_packet(self, pkt: dict) -> None:
        """Update internal state from a parsed packet."""
        with self._lock:
            if "bands" in pkt:
                self._latest_bands.update(pkt["bands"])
            if "attention" in pkt:
                self._latest_attention = pkt["attention"]
            if "meditation" in pkt:
                self._latest_meditation = pkt["meditation"]
            if "signal_quality" in pkt:
                self._latest_signal_quality = pkt["signal_quality"]
            if "battery" in pkt:
                self._battery_level = pkt["battery"]
            self._last_packet_time = time.monotonic()
            if "raw_wave" in pkt:
                self._raw_wave_buffer.append(pkt["raw_wave"])
                if len(self._raw_wave_buffer) > 1024:
                    self._raw_wave_buffer = self._raw_wave_buffer[-1024:]
