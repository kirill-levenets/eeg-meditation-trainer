"""The headset the app talks to: which paired MindWave (or the mock), what its user calls it, Settings → Device's
choices, the startup auto-scan and the diagnostics report."""
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
    """The Bluetooth link is always to the selected headset (NeuroSkyStream.set_device closes another), and a switch is
    refused while a session runs. A headset's alias is the same for every profile: it is the same headset whoever uses
    it."""

    def __init__(self, db, stream, device_section, live_screen, *, user_id: Callable[[], int | None],
                 refused_while_session_runs: Callable[[str], bool], waiting_for_bt: Callable[[], bool],
                 switch_to_settings: Callable[[], None], serial_override: Callable[[], str | None],
                 report: Callable[..., None]) -> None:
        self._db = db
        self._stream = stream
        self._device_section = device_section
        self._live_screen = live_screen
        self._user_id = user_id
        self._refused = refused_while_session_runs
        self._waiting_for_bt = waiting_for_bt
        self._switch_to_settings = switch_to_settings
        self._serial_override = serial_override
        self._report = report  # report_soft_error(label, detail, force=...) shown by the app
        # address -> the name its user gave the headset; replaced, never changed in place (the tick thread reads it)
        self.aliases: Mapping[str, str] = MappingProxyType({})

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

    def on_mode_toggle(self, use_mock: bool) -> None:
        APP.USE_MOCK_DEVICE = use_mock
        if use_mock:
            self._device_section.update_device_status(False, meta="Mode: Mock Data")
            self._live_screen.update_device_status(False, device_name="Mock EEG")
        else:
            addr = self._stream._device_address or "none"
            self._device_section.update_device_status(False, meta=f"Mode: Real Device ({addr})")
            self._live_screen.update_device_status(False, device_name=self.name())
        uid = self._user_id()
        if uid:
            self._db.set_user_setting(uid, "use_mock", str(use_mock))
        logger.info(f"Device mode: {'Mock' if use_mock else 'Real'}")

    def on_scan(self) -> None:
        """Scan for paired Bluetooth devices and send to settings screen."""
        devices = NeuroSkyStream.scan_paired_devices()
        self.list_devices(devices)
        logger.info(f"BT scan found {len(devices)} paired devices")

    def on_select(self, address: str, name: str) -> None:
        """User selected a BT device from the list."""
        if address != self._stream._device_address and self._refused("switching headsets"):
            return
        self._stream.set_device(address, name)
        # Auto-switch to real device mode
        APP.USE_MOCK_DEVICE = False
        self._device_section._device_mode_cb.active = False
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

    def auto_scan(self) -> None:
        """Background-scan paired BT devices at startup and auto-select MindWave."""
        if self._serial_override():
            return
        if self._stream._device_address:
            # Already have a saved device from user settings
            return

        def _scan_thread():
            return NeuroSkyStream.scan_paired_devices()

        def _on_scan_done(devices):
            if not devices:
                return
            matches = filter_mindwave(devices)
            if len(matches) == 1:
                self.on_select(matches[0]["address"], matches[0]["name"])
                logger.info(f"Auto-selected BT device: {matches[0]['name']}")
                return
            if len(matches) > 1:
                # Multiple NeuroSky devices paired — user must choose explicitly.
                logger.info(
                    f"Found {len(matches)} MindWave devices — routing to settings picker"
                )
                self.list_devices(matches)
                self._switch_to_settings()
                self._device_section.focus_device_section(
                    f"Found {len(matches)} MindWave devices.\n"
                    "Pick the one you want to use."
                )
                return
            # No MindWave found — populate settings list for manual pick
            self.list_devices(devices)

        def _run():
            try:
                devices = _scan_thread()
                Clock.schedule_once(lambda dt: _on_scan_done(devices))
            except Exception as e:  # noqa: BLE001 - a failed scan leaves the headset to be picked by hand; logged
                logger.warning(f"Auto-scan failed: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def on_copy_diagnostics(self) -> None:
        """Build a diagnostic report and show it via the soft-error dialog.

        User-initiated, so we bypass the per-label cooldown — the user
        explicitly asked for the report.
        """

        try:
            paired = NeuroSkyStream.scan_paired_devices()
        except Exception as e:  # noqa: BLE001 - the report goes out with what is known; logged
            paired = []
            logger.warning(f"Diagnostics: BT scan failed: {e}")

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
