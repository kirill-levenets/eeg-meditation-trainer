"""The headset the app talks to: which paired MindWave (or the mock), what its user calls it, Settings → Device's
choices, the scan for a profile's headset and the diagnostics report."""
import threading
from collections.abc import Callable, Mapping
from types import MappingProxyType

from kivy.clock import Clock

from app.config import APP
from app.eeg.neurosky_stream import NeuroSkyStream
from app.logger import logger
from app.ui.device_labels import MAX_DEVICE_ALIAS, device_label


def filter_mindwave(devices: list) -> list:
    """Subset of `devices` whose name looks like a NeuroSky MindWave."""
    out = []
    for dev in devices:
        name = (dev.get("name") or "").lower()
        if "mindwave" in name or "neurosky" in name:
            out.append(dev)
    return out


class Headset:
    """The Bluetooth link is always to the selected headset (NeuroSkyStream.set_device closes another), a switch is
    refused while a session runs, and the selected headset is the active profile's own or none. A headset's alias is
    the same for every profile: it is the same headset whoever uses it."""

    def __init__(self, db, stream, device_section, live_screen, *, user_id: Callable[[], int | None],
                 refused_while_session_runs: Callable[[str], bool], session_live: Callable[[], bool],
                 waiting_for_bt: Callable[[], bool], serial_override: Callable[[], str | None],
                 report: Callable[..., None]) -> None:
        self._db = db
        self._stream = stream
        self._device_section = device_section
        self._live_screen = live_screen
        self._user_id = user_id
        self._refused = refused_while_session_runs
        self._session_live = session_live
        self._waiting_for_bt = waiting_for_bt
        self._serial_override = serial_override
        self._report = report  # report_soft_error(label, detail, force=...) shown by the app
        # address -> the name its user gave the headset; replaced, never changed in place (the tick thread reads it)
        self.aliases: Mapping[str, str] = MappingProxyType({})
        # Moved by a profile load, a pick, a mode change and each profile scan: a profile scan applies while current.
        self._scan_seq = 0

    def load_aliases(self) -> None:
        aliases = self._db.get_json_setting("bt_device_aliases", {})
        valid = isinstance(aliases, dict) and all(isinstance(v, str) for v in aliases.values())
        self.aliases = MappingProxyType(aliases if valid else {})

    def name(self) -> str:
        """The selected headset as its user calls it."""
        stream = self._stream
        return device_label(stream._device_address or "", stream._device_name, self.aliases) or "Real EEG"

    def with_aliases(self, devices: list[dict]) -> list[dict]:
        return [{**dev, "alias": self.aliases.get(dev["address"], "")} for dev in devices]

    def list_devices(self, devices: list[dict]) -> None:
        self._device_section.populate_bt_devices(self.with_aliases(devices))

    def state(self) -> tuple[str | None, str | None]:
        """(selected, connected) headset addresses, none in mock mode: the stream's link is always to the selected one."""
        stream = self._stream
        if APP.USE_MOCK_DEVICE:
            return None, None
        return stream._device_address, stream._device_address if stream.is_connected else None

    def _session_label(self) -> str:
        return "Mock EEG" if APP.USE_MOCK_DEVICE else self.name()

    def show_selected(self) -> None:
        """The selected headset's name and link, on the Session screen and in Settings."""
        connected = self._stream.is_connected
        label = self.name()
        self._live_screen.update_device_status(connected, device_name=label,
                                               connecting=self._waiting_for_bt() and not connected)
        if connected:
            self._device_section.update_device_status(True, name=label)
        else:
            self._device_section.update_device_status(False, meta=f"Selected: {label}")

    def load(self, uid: int) -> None:
        """Select the profile's own headset, or none (closing a link to another profile's) and, in real mode, scan for
        one. The --serial override keeps its device, and a running session (its own profile re-picked) its headset."""
        self._scan_seq += 1
        if self._session_live():
            return
        if not self._serial_override():
            address = self._db.get_user_setting(uid, "bt_device_address") or None
            self._stream.set_device(address, self._db.get_user_setting(uid, "bt_device_name") or "")
            self._device_section.update_device_status(False, meta=f"Saved device: {self.name()}" if address else "")
        self._device_section.clear_picker_banner()  # it asked the last profile
        self._live_screen.update_device_status(False, device_name=self._session_label())
        if not self._stream._device_address and not APP.USE_MOCK_DEVICE:
            self.scan()

    def on_mode_toggle(self, use_mock: bool) -> None:
        self._scan_seq += 1
        APP.USE_MOCK_DEVICE = use_mock
        self._device_section.clear_picker_banner()  # Start's question was for the real headset
        addr = self._stream._device_address or "none"
        self._device_section.update_device_status(False, meta="Mode: Mock Data" if use_mock
                                                  else f"Mode: Real Device ({addr})")
        self._live_screen.update_device_status(False, device_name=self._session_label())
        uid = self._user_id()
        if uid:
            self._db.set_user_setting(uid, "use_mock", str(use_mock))
        logger.info(f"Device mode: {'Mock' if use_mock else 'Real'}")

    def on_scan(self) -> None:
        """Settings → Device's Scan: every paired device, listed; a profile scan still running makes its pick."""
        self.find_paired(self.list_devices)

    def on_select(self, address: str, name: str) -> None:
        """A headset picked in the list, or the one a scan found: the profile's, in real mode."""
        if address != self._stream._device_address and self._refused("switching headsets"):
            return
        self._scan_seq += 1
        self._stream.set_device(address, name)
        self._use_real_device()
        self._device_section.clear_picker_banner()
        self.show_selected()
        logger.info(f"BT device selected: {name} ({address}), switched to real mode")
        uid = self._user_id()
        if uid:
            self._db.set_user_setting(uid, "bt_device_address", address)
            self._db.set_user_setting(uid, "bt_device_name", name)

    def on_rename(self, address: str, name: str, text: str) -> None:
        """Name a headset (`name` is its Bluetooth one) for every profile: it is the same headset whoever uses it.
        Blank, or its Bluetooth name, drops the alias."""
        alias = text.strip()[:MAX_DEVICE_ALIAS]
        aliases = {k: v for k, v in self.aliases.items() if k != address}
        if alias and alias != name:
            aliases[address] = alias
        self._db.set_json_setting("bt_device_aliases", aliases)
        self.aliases = MappingProxyType(aliases)
        self._device_section.relabel_bt_device(address, aliases.get(address, ""))
        logger.info(f"BT device {address} named {aliases.get(address)!r}")
        if address == self.state()[0]:
            self.show_selected()

    def _use_real_device(self) -> None:
        APP.USE_MOCK_DEVICE = False
        self._device_section._device_mode_cb.active = False  # its handler, on_mode_toggle, saves the mode

    def find_paired(self, then: Callable[[list[dict]], None]) -> None:
        """The paired devices, listed off the main thread, to `then` on the main thread ([] when listing fails)."""
        def run():
            try:
                devices = NeuroSkyStream.scan_paired_devices()
            except Exception as e:  # noqa: BLE001 - a failed scan finds nothing: the headset is picked by hand; logged
                logger.warning(f"BT scan failed: {e}")
                devices = []
            logger.info(f"BT scan found {len(devices)} paired devices")
            Clock.schedule_once(lambda _dt: then(devices))

        threading.Thread(target=run, daemon=True).start()

    def adopt(self, devices: list[dict]) -> list[dict]:
        """A scan's paired devices: a single MindWave becomes the profile's headset unless it has one, and Settings →
        Device lists the MindWaves, or every paired device when none is one. Returns the MindWaves."""
        mindwaves = filter_mindwave(devices)
        if len(mindwaves) == 1 and not self._stream._device_address:
            self.on_select(mindwaves[0]["address"], mindwaves[0]["name"])
            logger.info(f"Auto-selected BT device: {mindwaves[0]['name']}")
        self.list_devices(mindwaves or devices)
        return mindwaves

    def scan(self, then: Callable[[list[dict]], None] | None = None) -> None:
        """Find the profile's headset (`adopt`), then `then(mindwaves)`; nothing comes of a result when another profile
        loaded, a headset was picked, the mode changed, another scan began or a session started meanwhile."""
        self._scan_seq += 1
        seq = self._scan_seq

        def done(devices: list[dict]) -> None:
            if seq != self._scan_seq or self._session_live():
                logger.info("BT scan result dropped: the headset choice or a session changed while it ran")
                return
            mindwaves = self.adopt(devices)
            if then is not None:
                then(mindwaves)

        self.find_paired(done)

    def scan_for_new_profile(self) -> None:
        """A new profile starts on the mock and leaves it when a MindWave is paired: Start asks which one if several."""
        def found(mindwaves: list[dict]) -> None:
            if mindwaves:
                self._use_real_device()

        self.scan(then=found)

    def on_copy_diagnostics(self) -> None:
        """Build a diagnostic report, with the paired devices listed off the main thread, and show it via the
        soft-error dialog; user-initiated, so it bypasses the per-label cooldown."""
        self.find_paired(self._report_diagnostics)

    def _report_diagnostics(self, paired: list[dict]) -> None:
        try:
            paired_summary = "\n".join(
                f"  - {d.get('name') or 'Unknown'}  ({d.get('address')})"
                for d in paired
            ) or "  (none)"
        except Exception:  # noqa: BLE001 - the report says it couldn't list them
            paired_summary = "  (failed to enumerate)"

        current_addr = self._stream._device_address or "(none)"
        current_name = self._stream._device_name or "(none)"
        last_err = self._stream._last_connect_error or "(none)"
        last_packet = self._stream.seconds_since_last_packet
        signal = self._stream._latest_signal_quality
        battery = self._stream._battery_level
        sample_rate = APP.WHITE_NOISE_SAMPLE_RATE
        max_volume = APP.MAX_VOLUME
        use_mock = APP.USE_MOCK_DEVICE

        detail = (
            f"USE_MOCK_DEVICE: {use_mock}\n"
            f"Selected device: {current_name} ({current_addr})\n"
            f"Last connect error: {last_err}\n"
            f"Seconds since last packet: {last_packet:.1f}\n"
            f"Latest signal quality: {signal}\n"
            f"Battery level (raw): {battery}\n"
            f"Audio sample rate: {sample_rate} Hz\n"
            f"Max volume: {max_volume}\n"
            f"Paired BT devices ({len(paired)}):\n{paired_summary}\n"
        )

        self._report("user_diagnostics", detail, force=True)
