from typing import Callable, Dict, Optional

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput

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
        self._on_line_width_change: Optional[Callable] = None
        self._on_rotate_screen: Optional[Callable] = None
        self._on_custom_formula_change: Optional[Callable] = None
        self._on_save_formula: Optional[Callable] = None
        self._on_load_formula: Optional[Callable] = None
        self._on_delete_formula: Optional[Callable] = None
        self._on_export_formulas: Optional[Callable] = None
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

        # Audio threshold metric picker
        audio_metric_label = Label(
            text="Audio control metric:",
            font_size=dp(13),
            size_hint_y=None,
            height=dp(24),
            color=(0.6, 0.6, 0.6, 1.0),
            halign="left",
        )
        audio_metric_label.bind(size=audio_metric_label.setter("text_size"))
        layout.add_widget(audio_metric_label)

        self._audio_metric_radios: Dict[str, CheckBox] = {}
        self._audio_metric_selected: str = "shamatha_score"
        self._on_audio_metric_change: Optional[Callable] = None
        audio_metric_options = {
            "shamatha_score": "Shamatha Score",
            "native_meditation": "NS Meditation",
            "native_attention": "NS Attention",
            "custom_formula": "Custom Formula",
        }
        for key, display_name in audio_metric_options.items():
            row = BoxLayout(size_hint_y=None, height=dp(32), spacing=dp(8))
            rb = CheckBox(
                group="audio_metric",
                active=(key == "shamatha_score"),
                size_hint_x=0.15,
            )
            rb.audio_metric_key = key
            rb.bind(active=self._on_audio_metric_radio)
            lbl = Label(
                text=display_name,
                font_size=dp(13),
                size_hint_x=0.85,
                halign="left",
            )
            lbl.bind(size=lbl.setter("text_size"))
            row.add_widget(rb)
            row.add_widget(lbl)
            layout.add_widget(row)
            self._audio_metric_radios[key] = rb

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

        # --- Display section ---
        layout.add_widget(self._section_label("Display"))

        # Line width slider
        lw_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        lw_label = Label(
            text="Line Width:", font_size=dp(13),
            size_hint_x=0.3, halign="left",
        )
        lw_label.bind(size=lw_label.setter("text_size"))
        self._line_width_slider = Slider(
            min=0.5, max=4.0, value=1.2, step=0.1, size_hint_x=0.5,
        )
        self._line_width_value = Label(
            text="1.2", font_size=dp(13), bold=True, size_hint_x=0.2,
        )
        self._line_width_slider.bind(value=self._on_line_width_slider)
        lw_row.add_widget(lw_label)
        lw_row.add_widget(self._line_width_slider)
        lw_row.add_widget(self._line_width_value)
        layout.add_widget(lw_row)

        # Screen rotation button
        self._rotate_btn = Button(
            text="Rotate Screen (0\u00b0)",
            font_size=dp(13),
            size_hint_y=None,
            height=dp(36),
            background_color=(0.25, 0.35, 0.5, 1.0),
        )
        self._rotate_btn.bind(on_release=self._on_rotate_pressed)
        self._current_rotation: int = 0
        layout.add_widget(self._rotate_btn)

        # --- Graph toggles ---
        layout.add_widget(self._section_label("Graph Metrics"))

        toggle_names = {
            "shamatha_score": "Shamatha Score",
            "distraction": "Distraction",
            "sinking": "Sinking",
            "subtle_distraction": "Subtle Distraction",
            "native_attention": "NS Attention",
            "native_meditation": "NS Meditation",
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

        # Custom formula visibility toggle
        cf_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        self._custom_formula_cb = CheckBox(active=False, size_hint_x=0.15)
        self._custom_formula_cb.bind(active=self._on_custom_formula_toggle)
        self._on_custom_formula_visible_change: Optional[Callable] = None
        cf_lbl = Label(
            text="Show Custom Formula",
            font_size=dp(14),
            size_hint_x=0.85,
            halign="left",
        )
        cf_lbl.bind(size=cf_lbl.setter("text_size"))
        cf_row.add_widget(self._custom_formula_cb)
        cf_row.add_widget(cf_lbl)
        layout.add_widget(cf_row)

        # --- Custom Formula section ---
        layout.add_widget(self._section_label("Custom Formula"))

        formula_desc = Label(
            text=(
                "Enter a Python-style formula to track as an extra metric.\n"
                "Leave empty to disable."
            ),
            font_size=dp(11),
            size_hint_y=None,
            height=dp(32),
            color=(0.6, 0.6, 0.6, 1.0),
            halign="left",
        )
        formula_desc.bind(size=formula_desc.setter("text_size"))
        layout.add_widget(formula_desc)

        self._formula_input = TextInput(
            text="",
            hint_text="e.g. (alpha1 + alpha2) / (beta1 + beta2 + 1)",
            font_size=dp(13),
            size_hint_y=None,
            height=dp(40),
            multiline=False,
            background_color=(0.12, 0.12, 0.18, 1.0),
            foreground_color=(0.9, 0.9, 0.9, 1.0),
        )
        self._formula_input.bind(on_text_validate=self._on_formula_submit)
        layout.add_widget(self._formula_input)

        formula_btns = BoxLayout(
            size_hint_y=None, height=dp(34), spacing=dp(6)
        )
        formula_btn = Button(
            text="Apply",
            font_size=dp(13),
            background_color=(0.25, 0.4, 0.55, 1.0),
        )
        formula_btn.bind(on_release=self._on_formula_submit)
        formula_btns.add_widget(formula_btn)

        save_btn = Button(
            text="Save",
            font_size=dp(13),
            background_color=(0.3, 0.45, 0.3, 1.0),
        )
        save_btn.bind(on_release=self._on_save_formula_pressed)
        formula_btns.add_widget(save_btn)
        layout.add_widget(formula_btns)

        self._formula_status = Label(
            text="",
            font_size=dp(11),
            size_hint_y=None,
            height=dp(20),
            color=(0.5, 0.8, 0.5, 1.0),
            halign="left",
        )
        self._formula_status.bind(size=self._formula_status.setter("text_size"))
        layout.add_widget(self._formula_status)

        # Saved formulas header with export button
        saved_header = BoxLayout(size_hint_y=None, height=dp(26), spacing=dp(6))
        saved_label = Label(
            text="Saved Formulas:",
            font_size=dp(12),
            size_hint_x=0.6,
            color=(0.6, 0.6, 0.6, 1.0),
            halign="left",
        )
        saved_label.bind(size=saved_label.setter("text_size"))
        saved_header.add_widget(saved_label)

        export_formulas_btn = Button(
            text="Export to .txt",
            font_size=dp(11),
            size_hint_x=0.4,
            background_color=(0.3, 0.3, 0.45, 1.0),
        )
        export_formulas_btn.bind(on_release=self._on_export_formulas_pressed)
        saved_header.add_widget(export_formulas_btn)
        layout.add_widget(saved_header)

        self._saved_formulas_box = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(0),
            spacing=dp(2),
        )
        layout.add_widget(self._saved_formulas_box)

        examples = Label(
            text=(
                "Examples:\n"
                "  (alpha1 + alpha2) / (beta1 + beta2 + 1)\n"
                "  sqrt(alpha_norm) * 100\n"
                "  meditation_score * 0.7 + shamatha_score * 0.3\n"
                "  avg(alpha1 + beta1, 10)\n"
                "  avg(sqrt(alpha_norm) * 100, 30)\n"
                "  avg(meditation_score, 20) - avg(distraction, 20)"
            ),
            font_size=dp(13),
            size_hint_y=None,
            height=dp(130),
            color=(0.5, 0.5, 0.5, 1.0),
            halign="left",
            valign="top",
        )
        examples.bind(size=examples.setter("text_size"))
        layout.add_widget(examples)

        ref = Label(
            text=(
                "Bands: alpha1 alpha2 beta1 beta2\n"
                "  gamma1 gamma2 theta delta\n"
                "Combined: alpha beta gamma\n"
                "Sqrt-relative: s_alpha1 s_alpha2 s_beta1\n"
                "  s_beta2 s_theta s_delta\n"
                "Normalized: alpha_norm beta_norm gamma_norm\n"
                "  theta_norm delta_norm total_power\n"
                "Metrics: meditation_score shamatha_score\n"
                "  distraction sinking subtle_distraction\n"
                "  stability calmness\n"
                "  native_attention native_meditation\n"
                "Functions: sqrt abs log log10 log2 exp pow\n"
                "  min max sin cos tanh\n"
                "Windowed: avg(expr, N) \u2014 mean of last N ticks\n"
                "  N = 1..600 (at 2Hz: 10=5s, 60=30s, 120=1min)"
            ),
            font_size=dp(12),
            size_hint_y=None,
            height=dp(225),
            color=(0.45, 0.45, 0.55, 1.0),
            halign="left",
            valign="top",
        )
        ref.bind(size=ref.setter("text_size"))
        layout.add_widget(ref)

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

    def _on_line_width_slider(self, instance, value) -> None:
        val = round(value, 1)
        self._line_width_value.text = f"{val:.1f}"
        if self._on_line_width_change:
            self._on_line_width_change(val)

    def _on_formula_submit(self, *args) -> None:
        formula = self._formula_input.text.strip()
        if self._on_custom_formula_change:
            self._on_custom_formula_change(formula)

    def set_formula_status(self, text: str, is_error: bool = False) -> None:
        self._formula_status.text = text
        if is_error:
            self._formula_status.color = (0.9, 0.3, 0.3, 1.0)
        else:
            self._formula_status.color = (0.5, 0.8, 0.5, 1.0)

    def _on_rotate_pressed(self, *args) -> None:
        self._current_rotation = (self._current_rotation + 90) % 360
        self._rotate_btn.text = f"Rotate Screen ({self._current_rotation}\u00b0)"
        if self._on_rotate_screen:
            self._on_rotate_screen(self._current_rotation)

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

    def set_line_width_callback(self, callback: Callable) -> None:
        self._on_line_width_change = callback

    def set_rotate_screen_callback(self, callback: Callable) -> None:
        self._on_rotate_screen = callback

    def set_custom_formula_callback(self, callback: Callable) -> None:
        self._on_custom_formula_change = callback

    def set_save_formula_callback(self, callback: Callable) -> None:
        self._on_save_formula = callback

    def set_load_formula_callback(self, callback: Callable) -> None:
        self._on_load_formula = callback

    def set_delete_formula_callback(self, callback: Callable) -> None:
        self._on_delete_formula = callback

    def set_export_formulas_callback(self, callback: Callable) -> None:
        self._on_export_formulas = callback

    def _on_export_formulas_pressed(self, *args) -> None:
        if self._on_export_formulas:
            self._on_export_formulas()

    def _on_save_formula_pressed(self, *args) -> None:
        formula = self._formula_input.text.strip()
        if not formula:
            self.set_formula_status("Nothing to save", is_error=True)
            return
        if self._on_save_formula:
            self._on_save_formula(formula)

    def _on_load_formula_pressed(self, btn) -> None:
        idx = getattr(btn, "formula_index", -1)
        if idx >= 0 and self._on_load_formula:
            self._on_load_formula(idx)

    def _on_delete_formula_pressed(self, btn) -> None:
        idx = getattr(btn, "formula_index", -1)
        if idx >= 0 and self._on_delete_formula:
            self._on_delete_formula(idx)

    def populate_saved_formulas(self, formulas) -> None:
        """Update the saved formulas list. formulas: [{name, formula}, ...]"""
        box = self._saved_formulas_box
        box.clear_widgets()
        row_height = dp(30)
        box.height = row_height * len(formulas) if formulas else dp(0)

        for i, entry in enumerate(formulas):
            row = BoxLayout(size_hint_y=None, height=row_height, spacing=dp(4))

            load_btn = Button(
                text=entry.get("name", entry.get("formula", "")[:30]),
                font_size=dp(11),
                size_hint_x=0.65,
                background_color=(0.2, 0.2, 0.3, 1.0),
                halign="left",
            )
            load_btn.formula_index = i
            load_btn.bind(on_release=self._on_load_formula_pressed)
            row.add_widget(load_btn)

            del_btn = Button(
                text="X",
                font_size=dp(12),
                size_hint_x=0.12,
                background_color=(0.5, 0.2, 0.2, 1.0),
            )
            del_btn.formula_index = i
            del_btn.bind(on_release=self._on_delete_formula_pressed)
            row.add_widget(del_btn)

            box.add_widget(row)

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

    # --- Custom formula visibility ---

    def _on_custom_formula_toggle(self, checkbox, active) -> None:
        if self._on_custom_formula_visible_change:
            self._on_custom_formula_visible_change(active)

    def set_custom_formula_visible_callback(self, callback: Callable) -> None:
        self._on_custom_formula_visible_change = callback

    @property
    def custom_formula_visible(self) -> bool:
        return self._custom_formula_cb.active

    @custom_formula_visible.setter
    def custom_formula_visible(self, value: bool) -> None:
        self._custom_formula_cb.active = value

    # --- Audio threshold metric picker ---

    def _on_audio_metric_radio(self, checkbox, active) -> None:
        if not active:
            return
        key = getattr(checkbox, "audio_metric_key", None)
        if key:
            self._audio_metric_selected = key
            if self._on_audio_metric_change:
                self._on_audio_metric_change(key)

    def set_audio_metric_callback(self, callback: Callable) -> None:
        self._on_audio_metric_change = callback

    @property
    def audio_metric(self) -> str:
        return self._audio_metric_selected

    @audio_metric.setter
    def audio_metric(self, key: str) -> None:
        self._audio_metric_selected = key
        for k, rb in self._audio_metric_radios.items():
            rb.active = (k == key)
