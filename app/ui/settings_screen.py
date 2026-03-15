from typing import Callable, Dict, Optional

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider

from app.config import APP, METRICS


class SettingsScreen(Screen):
    """Settings screen with threshold, audio controls, device info, and toggles."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "settings"
        self._on_threshold_change: Optional[Callable] = None
        self._on_toggle_change: Optional[Callable] = None
        self._on_test_audio: Optional[Callable] = None
        self._on_sinking_alert_toggle: Optional[Callable] = None
        self._on_disconnect_alert_toggle: Optional[Callable] = None
        self._on_device_mode_toggle: Optional[Callable] = None
        self._on_scan_devices: Optional[Callable] = None
        self._on_device_select: Optional[Callable] = None
        self._graph_toggles: Dict[str, bool] = {
            "meditation_score": True,
            "shamatha_score": True,
            "distraction": True,
            "sinking": True,
            "subtle_distraction": True,
        }
        self._build_ui()

    def _build_ui(self) -> None:
        scroll = ScrollView()
        layout = BoxLayout(
            orientation="vertical",
            padding=dp(16),
            spacing=dp(12),
            size_hint_y=None,
        )
        layout.bind(minimum_height=layout.setter("height"))

        title = Label(
            text="Settings",
            font_size=dp(22),
            bold=True,
            size_hint_y=None,
            height=dp(40),
        )
        layout.add_widget(title)

        # --- Device Status section ---
        layout.add_widget(self._section_label("Device"))

        self._device_status_label = Label(
            text="Not connected",
            font_size=dp(13),
            size_hint_y=None,
            height=dp(24),
            color=(0.8, 0.3, 0.3, 1.0),
            halign="left",
        )
        self._device_status_label.bind(size=self._device_status_label.setter("text_size"))
        layout.add_widget(self._device_status_label)

        self._device_meta_label = Label(
            text="Mode: Mock Data",
            font_size=dp(11),
            size_hint_y=None,
            height=dp(20),
            color=(0.5, 0.5, 0.5, 1.0),
            halign="left",
        )
        self._device_meta_label.bind(size=self._device_meta_label.setter("text_size"))
        layout.add_widget(self._device_meta_label)

        # Mock / Real device switch
        device_mode_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        self._device_mode_cb = CheckBox(
            active=APP.USE_MOCK_DEVICE, size_hint_x=0.15,
        )
        self._device_mode_cb.bind(active=self._on_device_mode_change)
        device_mode_lbl = Label(
            text="Use Mock Data (uncheck for real device)",
            font_size=dp(13),
            size_hint_x=0.85,
            halign="left",
        )
        device_mode_lbl.bind(size=device_mode_lbl.setter("text_size"))
        device_mode_row.add_widget(self._device_mode_cb)
        device_mode_row.add_widget(device_mode_lbl)
        layout.add_widget(device_mode_row)

        # Scan + device list (visible when mock is off)
        self._bt_section = BoxLayout(
            orientation="vertical", size_hint_y=None, spacing=dp(4),
        )
        self._bt_section.bind(minimum_height=self._bt_section.setter("height"))

        self._scan_btn = Button(
            text="Scan Paired Devices",
            font_size=dp(13),
            size_hint_y=None,
            height=dp(36),
            background_color=(0.25, 0.4, 0.55, 1.0),
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
        layout.add_widget(self._bt_section)

        # --- Threshold section ---
        layout.add_widget(self._section_label("Meditation Threshold"))

        slider_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self._threshold_slider = Slider(
            min=20,
            max=100,
            value=METRICS.MEDITATION_THRESHOLD_DEFAULT,
            step=1,
            size_hint_x=0.8,
        )
        self._threshold_value_label = Label(
            text=str(METRICS.MEDITATION_THRESHOLD_DEFAULT),
            font_size=dp(16),
            bold=True,
            size_hint_x=0.2,
        )
        self._threshold_slider.bind(value=self._on_slider_value)
        slider_row.add_widget(self._threshold_slider)
        slider_row.add_widget(self._threshold_value_label)
        layout.add_widget(slider_row)

        # --- Audio section ---
        layout.add_widget(self._section_label("Audio Feedback"))

        audio_desc = Label(
            text=(
                "Ch1: White noise — volume decreases as meditation deepens\n"
                "Ch2: Sinking bell — alert when sinking exceeds threshold"
            ),
            font_size=dp(11),
            size_hint_y=None,
            height=dp(40),
            color=(0.6, 0.6, 0.6, 1.0),
            halign="left",
        )
        audio_desc.bind(size=audio_desc.setter("text_size"))
        layout.add_widget(audio_desc)

        # Test Audio button
        self._test_audio_btn = Button(
            text="▶ Test Audio",
            font_size=dp(14),
            bold=True,
            size_hint_y=None,
            height=dp(40),
            background_color=(0.2, 0.5, 0.7, 1.0),
        )
        self._test_audio_btn.bind(on_release=self._on_test_audio_pressed)
        layout.add_widget(self._test_audio_btn)

        # Sinking alert toggle
        sinking_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        self._sinking_alert_cb = CheckBox(active=True, size_hint_x=0.15)
        self._sinking_alert_cb.bind(active=self._on_sinking_alert_change)
        sinking_lbl = Label(
            text="Enable Sinking Alert Bell",
            font_size=dp(13),
            size_hint_x=0.85,
            halign="left",
        )
        sinking_lbl.bind(size=sinking_lbl.setter("text_size"))
        sinking_row.add_widget(self._sinking_alert_cb)
        sinking_row.add_widget(sinking_lbl)
        layout.add_widget(sinking_row)

        # Disconnect alert toggle
        disconnect_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        self._disconnect_alert_cb = CheckBox(
            active=APP.DISCONNECT_ALERT_ENABLED, size_hint_x=0.15,
        )
        self._disconnect_alert_cb.bind(active=self._on_disconnect_alert_change)
        disconnect_lbl = Label(
            text="Audio alert on disconnect / signal loss",
            font_size=dp(13),
            size_hint_x=0.85,
            halign="left",
        )
        disconnect_lbl.bind(size=disconnect_lbl.setter("text_size"))
        disconnect_row.add_widget(self._disconnect_alert_cb)
        disconnect_row.add_widget(disconnect_lbl)
        layout.add_widget(disconnect_row)

        # --- Graph toggles ---
        layout.add_widget(self._section_label("Graph Metrics"))

        toggle_names = {
            "meditation_score": "Meditation Score",
            "shamatha_score": "Shamatha Score",
            "distraction": "Distraction",
            "sinking": "Sinking",
            "subtle_distraction": "Subtle Distraction",
        }
        self._checkboxes: Dict[str, CheckBox] = {}
        for key, display_name in toggle_names.items():
            row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
            cb = CheckBox(active=True, size_hint_x=0.15)
            cb.metric_key = key
            cb.bind(active=self._on_toggle)
            lbl = Label(
                text=display_name,
                font_size=dp(14),
                size_hint_x=0.85,
                halign="left",
            )
            lbl.bind(size=lbl.setter("text_size"))
            row.add_widget(cb)
            row.add_widget(lbl)
            layout.add_widget(row)
            self._checkboxes[key] = cb

        # --- Info section ---
        spacer = Label(size_hint_y=None, height=dp(20))
        layout.add_widget(spacer)

        info = Label(
            text=(
                "EEG Meditation Trainer v1.0\n"
                "Shamatha meditation with neurofeedback"
            ),
            font_size=dp(11),
            color=(0.5, 0.5, 0.5, 1.0),
            size_hint_y=None,
            height=dp(40),
            halign="center",
        )
        layout.add_widget(info)

        scroll.add_widget(layout)
        self.add_widget(scroll)

    @staticmethod
    def _section_label(text: str) -> Label:
        """Create a styled section header label."""
        lbl = Label(
            text=text,
            font_size=dp(16),
            size_hint_y=None,
            height=dp(30),
            halign="left",
            bold=True,
        )
        lbl.bind(size=lbl.setter("text_size"))
        return lbl

    def _on_slider_value(self, instance, value) -> None:
        val = int(value)
        self._threshold_value_label.text = str(val)
        if self._on_threshold_change:
            self._on_threshold_change(val)

    def _on_toggle(self, checkbox, active) -> None:
        key = getattr(checkbox, "metric_key", None)
        if key:
            self._graph_toggles[key] = active
            if self._on_toggle_change:
                self._on_toggle_change(key, active)

    def _on_test_audio_pressed(self, *args) -> None:
        if self._on_test_audio:
            self._on_test_audio()

    def _on_sinking_alert_change(self, checkbox, active) -> None:
        if self._on_sinking_alert_toggle:
            self._on_sinking_alert_toggle(active)

    def _on_disconnect_alert_change(self, checkbox, active) -> None:
        if self._on_disconnect_alert_toggle:
            self._on_disconnect_alert_toggle(active)

    def _on_device_mode_change(self, checkbox, active) -> None:
        if self._on_device_mode_toggle:
            self._on_device_mode_toggle(active)

    def _on_scan_pressed(self, *args) -> None:
        if self._on_scan_devices:
            self._on_scan_devices()

    def _on_bt_device_pressed(self, btn) -> None:
        address = getattr(btn, "bt_address", "")
        name = getattr(btn, "bt_name", "")
        if address and self._on_device_select:
            self._on_device_select(address, name)

    @property
    def threshold(self) -> int:
        return int(self._threshold_slider.value)

    @property
    def use_mock_device(self) -> bool:
        return self._device_mode_cb.active

    def set_threshold_callback(self, callback: Callable) -> None:
        self._on_threshold_change = callback

    def set_toggle_callback(self, callback: Callable) -> None:
        self._on_toggle_change = callback

    def set_test_audio_callback(self, callback: Callable) -> None:
        self._on_test_audio = callback

    def set_sinking_alert_callback(self, callback: Callable) -> None:
        self._on_sinking_alert_toggle = callback

    def set_disconnect_alert_callback(self, callback: Callable) -> None:
        self._on_disconnect_alert_toggle = callback

    def set_device_mode_callback(self, callback: Callable) -> None:
        self._on_device_mode_toggle = callback

    def set_scan_devices_callback(self, callback: Callable) -> None:
        self._on_scan_devices = callback

    def set_device_select_callback(self, callback: Callable) -> None:
        self._on_device_select = callback

    def populate_bt_devices(self, devices: list) -> None:
        """Populate the BT device list with scan results."""
        self._bt_device_list.clear_widgets()
        if not devices:
            lbl = Label(
                text="No paired devices found",
                font_size=dp(11),
                size_hint_y=None,
                height=dp(28),
                color=(0.6, 0.6, 0.6, 1.0),
            )
            self._bt_device_list.add_widget(lbl)
            return
        for dev in devices:
            btn = Button(
                text=f"{dev['name']}  ({dev['address']})",
                font_size=dp(11),
                size_hint_y=None,
                height=dp(32),
                background_color=(0.18, 0.18, 0.25, 1.0),
            )
            btn.bt_address = dev["address"]
            btn.bt_name = dev["name"]
            btn.bind(on_release=self._on_bt_device_pressed)
            self._bt_device_list.add_widget(btn)

    def update_device_status(
        self, connected: bool, name: str = "", meta: str = ""
    ) -> None:
        """Update device status display in settings."""
        if connected:
            self._device_status_label.text = f"Connected: {name}" if name else "Connected"
            self._device_status_label.color = (0.2, 0.9, 0.4, 1.0)
        else:
            self._device_status_label.text = "Not connected"
            self._device_status_label.color = (0.8, 0.3, 0.3, 1.0)
        if meta:
            self._device_meta_label.text = meta
        elif self._device_mode_cb.active:
            self._device_meta_label.text = "Mode: Mock Data"
        else:
            self._device_meta_label.text = "Mode: Real Device"

    @property
    def graph_toggles(self) -> Dict[str, bool]:
        return dict(self._graph_toggles)
