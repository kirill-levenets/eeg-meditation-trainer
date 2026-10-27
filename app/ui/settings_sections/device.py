"""Settings → Device: the mock or real headset, the paired MindWaves to pick from (each can be renamed), the
connection status, what may close a locked session (Android) and the diagnostics copy."""

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app.config import APP
from app.logger import logger
from app.ui.device_labels import MAX_DEVICE_ALIAS, device_row_text
from app.ui.hooks import Hook
from app.ui.settings_sections.common import checkbox_row
from app.ui.theme import (
    C,
    F,
    Icons,
    RenameRow,
    S,
    StyledButton,
    ThemedLabel,
    fit_height_to_text,
)


class DeviceSection:
    """Builds the section's content into `section` and reports the user's actions through its callbacks; `scroll` is
    the Settings scroll view, which focus_device_section brings the section into."""

    on_device_mode_toggle = Hook()
    on_scan_devices = Hook()
    on_device_select = Hook()
    device_state = Hook(default=(None, None))  # (selected, connected) addresses
    on_device_rename = Hook()
    on_copy_diagnostics = Hook()
    on_battery_settings = Hook()
    on_maker_settings = Hook()

    def __init__(self, section, *, scroll) -> None:
        self._scroll = scroll
        self._bt_devices: dict[str, dict] = {}  # address -> the listed device, with the alias its user gave it
        self._bt_rows: dict[str, StyledButton] = {}
        self._bt_pencils: dict[str, StyledButton] = {}
        self._bt_renaming: str | None = None
        self._build(section)

    def _build(self, section) -> None:
        self._device_section = section

        # One-shot banner used by focus_device_section(message). Empty/0-height
        # by default so it doesn't take space; populated when we route the
        # user here (e.g. multiple MindWave devices found, scan returned 0).
        self._device_picker_banner = ThemedLabel(
            text="",
            font_size=F.BODY,
            color=C.WARM,
            bold=True,
            size_hint_y=None,
            height=0,
            halign="left", valign="middle",
            opacity=0,
        )
        self._device_picker_banner.bind(
            size=self._device_picker_banner.setter("text_size")
        )
        section.add_widget(self._device_picker_banner)

        self._device_status_label = ThemedLabel(
            text="Not connected",
            font_size=F.BODY,
            size_hint_y=None,
            height=dp(24),
            color=C.DISCONNECTED,
            halign="left",
        )
        self._device_status_label.bind(size=self._device_status_label.setter("text_size"))
        section.add_widget(self._device_status_label)

        self._device_meta_label = ThemedLabel(
            text="Mode: Mock Data",
            font_size=F.SMALL,
            size_hint_y=None,
            height=dp(20),
            color=C.TEXT_MUTED,
            halign="left",
        )
        self._device_meta_label.bind(size=self._device_meta_label.setter("text_size"))
        section.add_widget(self._device_meta_label)

        # Mock / Real device switch
        device_mode_row, self._device_mode_cb = checkbox_row(
            "Use Mock Data (uncheck for real device)", dp(36), active=APP.USE_MOCK_DEVICE)
        self._device_mode_cb.bind(active=self._on_device_mode_change)
        section.add_widget(device_mode_row)

        # Scan + device list (visible when mock is off)
        self._bt_section = BoxLayout(
            orientation="vertical", size_hint_y=None, spacing=S.GAP_SM,
        )
        self._bt_section.bind(minimum_height=self._bt_section.setter("height"))

        self._scan_btn = StyledButton(
            text="Scan Paired Devices",
            font_size=F.BODY,
            bg_color=C.PRIMARY_DIM,
            size_hint_y=None,
            height=dp(36),
        )
        self._scan_btn.bind(on_release=self._on_scan_pressed)
        self._bt_section.add_widget(self._scan_btn)

        self._bt_device_list = BoxLayout(
            orientation="vertical", size_hint_y=None, spacing=dp(2),
        )
        self._bt_device_list.bind(
            minimum_height=self._bt_device_list.setter("height")
        )
        self._bt_section.add_widget(self._bt_device_list)
        section.add_widget(self._bt_section)
        self._build_device_rename_row()

        # On-demand diagnostics button — useful for users we can't reach in
        # person. Builds a copy-pasteable report with platform/device/audio
        # state and opens the same dialog the crash handler uses.
        self._diagnostics_btn = StyledButton(
            text="Copy Diagnostics",
            font_size=F.SMALL,
            bg_color=C.BG_CARD,
            text_color=C.TEXT_SECONDARY,
            size_hint_y=None,
            height=dp(32),
        )
        self._diagnostics_btn.bind(on_release=self._on_diagnostics_pressed)
        section.add_widget(self._diagnostics_btn)
        self._build_power_box()

    def _build_power_box(self) -> None:
        """What may close a locked session; attached by show_power_state, so off Android it never shows."""
        self._power_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=S.GAP_SM)
        self._power_box.bind(minimum_height=self._power_box.setter("height"))
        title = ThemedLabel(text="Locked-screen sessions", font_size=F.BODY, bold=True, color=C.TEXT,
                            size_hint_y=None, halign="left")
        fit_height_to_text(title)
        self._power_label = ThemedLabel(text="", font_size=F.SMALL, color=C.TEXT_MUTED, size_hint_y=None,
                                        halign="left")
        fit_height_to_text(self._power_label)
        self._power_buttons = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP_SM)
        self._battery_btn = StyledButton(text="Battery", font_size=F.BODY, bg_color=C.PRIMARY_DIM, size_hint_y=None,
                                         height=dp(36))
        self._battery_btn.bind(on_release=lambda *_: self.on_battery_settings())
        self._maker_btn = StyledButton(text="", font_size=F.BODY, bg_color=C.PRIMARY_DIM, size_hint_y=None,
                                       height=dp(36))
        self._maker_btn.bind(on_release=lambda *_: self.on_maker_settings())
        for widget in (title, self._power_label, self._power_buttons):
            self._power_box.add_widget(widget)

    def show_power_state(self, status: str, *, battery: bool, maker: str | None) -> None:
        """Show the locked-session row: `status` says where things stand, `battery` offers leaving battery
        optimisation, `maker` names the maker's own power screen (None: nothing to open)."""
        self._power_label.text = status
        self._power_buttons.clear_widgets()
        if battery:
            self._power_buttons.add_widget(self._battery_btn)
        if maker:
            self._maker_btn.text = maker
            self._power_buttons.add_widget(self._maker_btn)
        if self._power_buttons.children and self._power_buttons.parent is None:
            self._power_box.add_widget(self._power_buttons)
        elif not self._power_buttons.children and self._power_buttons.parent is not None:
            self._power_box.remove_widget(self._power_buttons)
        if self._power_box.parent is None:
            self._device_section.add_widget(self._power_box, index=1)  # above Copy Diagnostics

    def _on_device_mode_change(self, checkbox, active) -> None:
        self.on_device_mode_toggle(active)

    def _on_scan_pressed(self, *args) -> None:
        self.on_scan_devices()

    def _on_bt_device_pressed(self, btn) -> None:
        address = getattr(btn, "bt_address", "")
        name = getattr(btn, "bt_name", "")
        if address:
            self.on_device_select(address, name)

    def _on_diagnostics_pressed(self, *_args) -> None:
        self.on_copy_diagnostics()

    def populate_bt_devices(self, devices: list) -> None:
        """Populate the BT device list with scan results, each with the `alias` its user gave it."""
        self._close_device_rename()
        self._bt_device_list.clear_widgets()
        self._bt_devices = {dev["address"]: dict(dev) for dev in devices}
        self._bt_rows = {}
        self._bt_pencils = {}
        if not devices:
            lbl = ThemedLabel(
                text="No paired devices found",
                font_size=F.SMALL,
                size_hint_y=None,
                height=dp(28),
                color=C.TEXT_SECONDARY,
            )
            self._bt_device_list.add_widget(lbl)
            return
        for dev in devices:
            address = dev["address"]
            row = BoxLayout(size_hint_y=None, height=dp(32), spacing=S.GAP_SM)
            # Built with the link glyph so its slot exists; mark_bt_devices shows it on the connected row only.
            btn = StyledButton(
                text=device_row_text(dev.get("alias") or dev["name"], address),
                icon=Icons.BLUETOOTH,
                font_size=F.SMALL,
                bg_color=C.BG_CARD,
                height=dp(32),
            )
            btn.bt_address = address
            btn.bt_name = dev["name"]
            btn.bind(on_release=self._on_bt_device_pressed)
            pencil = StyledButton(icon=Icons.PENCIL, bg_color=C.BG_CARD, text_color=C.PRIMARY, size_hint_x=None,
                                  width=dp(40), height=dp(32))
            pencil.bind(on_release=lambda _b, a=address: self._toggle_device_rename(a))
            row.add_widget(btn)
            row.add_widget(pencil)
            self._bt_rows[address] = btn
            self._bt_pencils[address] = pencil
            self._bt_device_list.add_widget(row)
        self.mark_bt_devices()

    def mark_bt_devices(self) -> None:
        """Fill the selected headset's row and show the link on the connected one's."""
        selected, connected = self.device_state()
        for address, btn in self._bt_rows.items():
            btn.bg_color = C.ACCENT if address == selected else C.BG_CARD
            btn.set_icon(Icons.BLUETOOTH if address == connected else "")

    def relabel_bt_device(self, address: str, alias: str) -> None:
        dev = self._bt_devices.get(address)
        if dev is None:
            return
        dev["alias"] = alias
        self._bt_rows[address].text = device_row_text(alias or dev["name"], address)

    def _build_device_rename_row(self) -> None:
        self._bt_rename_row = RenameRow(self._save_device_rename, max_length=MAX_DEVICE_ALIAS)
        self._bt_rename_input = self._bt_rename_row.input

    def _toggle_device_rename(self, address: str) -> None:
        """Open the name editor under this headset's row, or close it if it is open there."""
        reopen = self._bt_renaming != address
        self._close_device_rename()
        if not reopen:
            return
        dev = self._bt_devices[address]
        self._bt_renaming = address
        self._bt_rename_input.text = dev.get("alias", "")
        self._bt_rename_input.hint_text = dev["name"]  # blank goes back to the Bluetooth name
        row = self._bt_rows[address].parent
        self._bt_device_list.add_widget(self._bt_rename_row, index=self._bt_device_list.children.index(row))
        self._bt_rename_row.focus_soon()

    def _close_device_rename(self) -> None:
        self._bt_renaming = None
        self._bt_rename_row.close()

    def _save_device_rename(self) -> None:
        address = self._bt_renaming
        if address is None:
            return
        text = self._bt_rename_input.text
        self._close_device_rename()
        self.on_device_rename(address, self._bt_devices[address]["name"], text)

    def update_device_status(
        self, connected: bool, name: str = "", meta: str = ""
    ) -> None:
        """Update device status display in settings."""
        if connected:
            self._device_status_label.text = f"Connected: {name}" if name else "Connected"
            self._device_status_label.color = C.CONNECTED
            # User has resolved the picker prompt — clear the banner.
            self._set_device_picker_banner("")
        else:
            self._device_status_label.text = "Not connected"
            self._device_status_label.color = C.DISCONNECTED
        self.mark_bt_devices()
        if meta:
            self._device_meta_label.text = meta
        elif self._device_mode_cb.active:
            self._device_meta_label.text = "Mode: Mock Data"
        else:
            self._device_meta_label.text = "Mode: Real Device"

    def clear_picker_banner(self) -> None:
        """Start's pick-one prompt is answered: a headset was picked, or another profile loaded."""
        self._set_device_picker_banner("")

    def _set_device_picker_banner(self, message: str) -> None:
        """Show or hide the picker banner above the device list."""
        if message:
            self._device_picker_banner.text = message
            self._device_picker_banner.height = dp(48)
            self._device_picker_banner.opacity = 1
        else:
            self._device_picker_banner.text = ""
            self._device_picker_banner.height = 0
            self._device_picker_banner.opacity = 0

    def focus_device_section(self, message: str = "") -> None:
        """Open the Device accordion, scroll it into view, and surface a prompt.

        Used when the app needs the user's attention on device selection — e.g.
        multiple MindWave devices paired, or a scan returned zero results and we
        want the user to retry / check permissions.
        """
        if hasattr(self, "_device_section") and self._device_section is not None:
            self._device_section.open()
        if message:
            self._set_device_picker_banner(message)
        else:
            self._set_device_picker_banner("")

        def _scroll(_dt):
            scroll = self._scroll
            section = getattr(self, "_device_section", None)
            if scroll is not None and section is not None:
                try:
                    scroll.scroll_to(section)
                except Exception as e:  # noqa: BLE001 - the section is open and its banner shown, just not scrolled to
                    logger.warning(f"Couldn't scroll Settings to the Device section: {e}")

        # Defer to next frame so the section's expanded height is laid out
        # before we ask the ScrollView to bring it into view.
        Clock.schedule_once(_scroll, 0)
