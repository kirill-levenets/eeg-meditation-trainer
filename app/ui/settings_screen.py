import os
import threading
from collections.abc import Callable
from typing import Optional

from kivy.clock import Clock
from kivy.core.window import Keyboard, Window
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput

from app.config import APP, METRICS
from app.ui.theme import (
    POPUP_TEXT,
    THEMES,
    C,
    Divider,
    F,
    Icons,
    PresetRow,
    S,
    StyledButton,
    ThemedAccordion,
)
from app.ui.widgets.user_picker import UserPickerForm


def _load_help_topics(lang: str = "en") -> list[tuple[str, str]]:
    """Load help topics from app/assets/help/help_{lang}.txt.

    File format: sections separated by '## Title' lines.
    Returns list of (title, body) tuples.
    """
    help_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "assets", "help",
    )
    path = os.path.join(help_dir, f"help_{lang}.txt")
    if not os.path.exists(path):
        # Fallback to English
        path = os.path.join(help_dir, "help_en.txt")
    if not os.path.exists(path):
        return [("Help", "Help file not found")]

    topics: list[tuple[str, str]] = []
    current_title = ""
    current_body: list[str] = []

    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("## "):
                if current_title:
                    topics.append((current_title, "\n".join(current_body).strip()))
                current_title = line[3:].strip()
                current_body = []
            else:
                current_body.append(line.rstrip())

    if current_title:
        topics.append((current_title, "\n".join(current_body).strip()))

    return topics


class SettingsScreen(Screen):
    """Settings screen with threshold, audio controls, device info, and toggles."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "settings"
        self._on_profile_switch: Optional[Callable] = None
        self._on_profile_create: Optional[Callable] = None
        self._on_profile_delete: Optional[Callable] = None
        self._session_counter: Optional[Callable[[int], int]] = None
        self._on_backup_pressed: Optional[Callable] = None
        self._on_restore_pressed: Optional[Callable] = None
        self._on_threshold_change: Optional[Callable] = None
        self._on_test_audio: Optional[Callable] = None
        self._on_sinking_alert_toggle: Optional[Callable] = None
        self._on_subtle_alert_toggle: Optional[Callable] = None
        self._on_disconnect_alert_toggle: Optional[Callable] = None
        self._on_device_mode_toggle: Optional[Callable] = None
        self._on_scan_devices: Optional[Callable] = None
        self._on_device_select: Optional[Callable] = None
        self._on_copy_diagnostics: Optional[Callable] = None
        self._on_timer_sound_change: Optional[Callable] = None
        self._on_test_timer_sound: Optional[Callable] = None
        self._on_stop_timer_sound: Optional[Callable] = None
        self._timer_sound_test_playing: bool = False
        self._on_line_width_change: Optional[Callable] = None
        self._on_rotate_screen: Optional[Callable] = None
        self._on_formula_slot_change: Optional[Callable] = None
        self._on_save_formula: Optional[Callable] = None
        self._on_load_formula: Optional[Callable] = None
        self._on_delete_formula: Optional[Callable] = None
        self._on_export_formulas: Optional[Callable] = None
        self._on_theme_change: Optional[Callable] = None
        self._graph_toggles: dict[str, bool] = {
            "shamatha_score": True,
            "distraction": False,
            "sinking": False,
            "subtle_distraction": False,
            "native_attention": False,
            "native_meditation": False,
        }
        self._build_ui()

    def _build_ui(self) -> None:
        root = BoxLayout(orientation="vertical")

        # Screen background
        with root.canvas.before:
            Color(*C.BG)
            self._bg_rect = Rectangle(size=root.size, pos=root.pos)
        root.bind(size=self._update_bg, pos=self._update_bg)

        scroll = ScrollView()
        accordion = ThemedAccordion()

        # --- Profile section ---
        profile_section = accordion.add_section("User Profile", collapsed=False)

        self._profile_current_label = Label(
            text="No user selected",
            font_size=F.BODY,
            color=C.PRIMARY,
            bold=True,
            size_hint_y=None,
            height=dp(24),
            halign="left",
        )
        self._profile_current_label.bind(
            width=lambda w, v: setattr(w, "text_size", (v, None))
        )
        profile_section.add_widget(self._profile_current_label)

        self._user_picker_form = UserPickerForm(
            on_create=self._on_form_create_pressed,
            on_pick_existing=self._on_form_pick_existing,
            on_count=self._count_user_sessions,
            on_delete=self._on_form_delete_pressed,
        )
        profile_section.add_widget(self._user_picker_form)

        # --- Timer section ---
        timer_section = accordion.add_section("Timer", collapsed=True)

        timer_toggle_row = BoxLayout(size_hint_y=None, height=S.ROW_SM, spacing=S.GAP)
        self._timer_enable_cb = CheckBox(
            active=False, size_hint_x=0.15,
            size_hint_y=None, height=S.ROW_SM,
        )
        timer_enable_lbl = Label(
            text="Enable Timer",
            font_size=F.BODY,
            color=C.TEXT,
            size_hint_x=0.85,
            halign="left", valign="middle",
        )
        timer_enable_lbl.bind(size=timer_enable_lbl.setter("text_size"))
        timer_toggle_row.add_widget(self._timer_enable_cb)
        timer_toggle_row.add_widget(timer_enable_lbl)
        timer_section.add_widget(timer_toggle_row)

        timer_dur_row = BoxLayout(size_hint_y=None, height=S.ROW_SM, spacing=S.GAP)
        timer_dur_lbl = Label(
            text="Duration:", font_size=F.BODY, color=C.TEXT_SECONDARY,
            size_hint_x=0.25, halign="left",
        )
        timer_dur_lbl.bind(size=timer_dur_lbl.setter("text_size"))
        self._timer_duration_slider = Slider(
            min=1, max=120, value=20, step=1, size_hint_x=0.55,
        )
        self._timer_duration_label = Label(
            text="20 min", font_size=F.BODY, bold=True, color=C.TEXT,
            size_hint_x=0.2,
        )
        self._timer_duration_slider.bind(
            value=lambda inst, val: setattr(
                self._timer_duration_label, "text", f"{int(val)} min"
            )
        )
        timer_dur_row.add_widget(timer_dur_lbl)
        timer_dur_row.add_widget(self._timer_duration_slider)
        timer_dur_row.add_widget(self._timer_duration_label)
        timer_section.add_widget(timer_dur_row)

        timer_presets = PresetRow(
            items=[("5m", 5), ("10m", 10), ("15m", 15), ("20m", 20),
                   ("30m", 30), ("1h", 60), ("1h30", 90), ("2h", 120)],
            callback=lambda v: setattr(self._timer_duration_slider, "value", v),
        )
        timer_section.add_widget(timer_presets)

        # Custom timer-end sound: path input + browse + test buttons.
        # When empty, the synthesised tingsha bell is used.
        timer_sound_lbl = Label(
            text="Timer End Sound (optional)",
            font_size=F.SMALL,
            color=C.TEXT_SECONDARY,
            size_hint_y=None, height=dp(20),
            halign="left",
        )
        timer_sound_lbl.bind(size=timer_sound_lbl.setter("text_size"))
        timer_section.add_widget(timer_sound_lbl)

        timer_sound_row = BoxLayout(
            size_hint_y=None, height=dp(36), spacing=S.GAP_SM,
        )
        self._timer_sound_input = TextInput(
            hint_text="Default bell",
            text="",
            multiline=False,
            font_size=F.SMALL,
            foreground_color=C.TEXT,
            background_color=list(C.BG_INPUT),
            size_hint_x=0.5,
        )
        self._timer_sound_input.bind(text=self._on_timer_sound_path_change)
        self._timer_sound_browse_btn = StyledButton(
            text="Browse",
            font_size=F.SMALL,
            bg_color=C.BG_CARD,
            text_color=C.TEXT,
            size_hint_x=0.25,
            size_hint_y=None,
            height=dp(36),
        )
        self._timer_sound_browse_btn.bind(on_release=self._on_timer_sound_browse)
        self._timer_sound_test_btn = StyledButton(
            text="Test",
            font_size=F.SMALL,
            bg_color=C.PRIMARY_DIM,
            size_hint_x=0.25,
            size_hint_y=None,
            height=dp(36),
        )
        self._timer_sound_test_btn.bind(on_release=self._on_timer_sound_test)
        timer_sound_row.add_widget(self._timer_sound_input)
        timer_sound_row.add_widget(self._timer_sound_browse_btn)
        timer_sound_row.add_widget(self._timer_sound_test_btn)
        timer_section.add_widget(timer_sound_row)

        # --- Device Status section ---
        device_section = accordion.add_section("Device", collapsed=True)
        self._device_section = device_section

        # One-shot banner used by focus_device_section(message). Empty/0-height
        # by default so it doesn't take space; populated when we route the
        # user here (e.g. multiple MindWave devices found, scan returned 0).
        self._device_picker_banner = Label(
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
        device_section.add_widget(self._device_picker_banner)

        self._device_status_label = Label(
            text="Not connected",
            font_size=F.BODY,
            size_hint_y=None,
            height=dp(24),
            color=C.DISCONNECTED,
            halign="left",
        )
        self._device_status_label.bind(size=self._device_status_label.setter("text_size"))
        device_section.add_widget(self._device_status_label)

        self._device_meta_label = Label(
            text="Mode: Mock Data",
            font_size=F.SMALL,
            size_hint_y=None,
            height=dp(20),
            color=C.TEXT_MUTED,
            halign="left",
        )
        self._device_meta_label.bind(size=self._device_meta_label.setter("text_size"))
        device_section.add_widget(self._device_meta_label)

        # Mock / Real device switch
        device_mode_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP)
        self._device_mode_cb = CheckBox(
            active=APP.USE_MOCK_DEVICE, size_hint_x=0.15,
            size_hint_y=None, height=dp(36),
        )
        self._device_mode_cb.bind(active=self._on_device_mode_change)
        device_mode_lbl = Label(
            text="Use Mock Data (uncheck for real device)",
            font_size=F.BODY,
            color=C.TEXT,
            size_hint_x=0.85,
            halign="left", valign="middle",
        )
        device_mode_lbl.bind(size=device_mode_lbl.setter("text_size"))
        device_mode_row.add_widget(self._device_mode_cb)
        device_mode_row.add_widget(device_mode_lbl)
        device_section.add_widget(device_mode_row)

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
        device_section.add_widget(self._bt_section)

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
        device_section.add_widget(self._diagnostics_btn)

        # --- Data Backup section ---
        backup_section = accordion.add_section("Data Backup", collapsed=True)

        self._backup_btn = StyledButton(
            text="Backup database",
            bg_color=C.ACCENT,
            bg_pressed=C.ACCENT_DIM,
            font_size=F.BODY,
            size_hint_y=None,
            height=dp(40),
        )
        self._restore_btn = StyledButton(
            text="Restore database",
            bg_color=C.PRIMARY,
            bg_pressed=C.PRIMARY_DIM,
            font_size=F.BODY,
            size_hint_y=None,
            height=dp(40),
        )
        self._backup_status = Label(
            text="",
            font_size=F.SMALL,
            color=C.TEXT_MUTED,
            size_hint_y=None,
            height=dp(22),
            halign="left",
            valign="middle",
        )
        self._backup_status.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))

        self._backup_btn.bind(on_release=lambda *a: (
            self._on_backup_pressed() if self._on_backup_pressed else None
        ))
        self._restore_btn.bind(on_release=lambda *a: (
            self._on_restore_pressed() if self._on_restore_pressed else None
        ))

        backup_section.add_widget(self._backup_btn)
        backup_section.add_widget(self._restore_btn)
        backup_section.add_widget(self._backup_status)

        # --- Threshold section ---
        threshold_section = accordion.add_section("Threshold", collapsed=True)

        slider_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=S.GAP_SM)
        minus_btn = StyledButton(
            text="−", font_size=F.H2, bg_color=C.BG_CARD,
            size_hint_x=None, width=dp(48),
        )
        plus_btn = StyledButton(
            text="+", font_size=F.H2, bg_color=C.BG_CARD,
            size_hint_x=None, width=dp(48),
        )
        self._threshold_slider = Slider(
            min=20,
            max=180,
            value=METRICS.MEDITATION_THRESHOLD_DEFAULT,
            step=1,
            size_hint_x=1,
        )
        self._threshold_value_label = Label(
            text=str(METRICS.MEDITATION_THRESHOLD_DEFAULT),
            font_size=F.H2,
            bold=True,
            color=C.TEXT,
            size_hint_x=None,
            width=dp(48),
        )
        self._threshold_slider.bind(value=self._on_slider_value)
        minus_btn.bind(on_release=lambda *a: self._step_threshold(-5))
        plus_btn.bind(on_release=lambda *a: self._step_threshold(5))
        slider_row.add_widget(minus_btn)
        slider_row.add_widget(self._threshold_slider)
        slider_row.add_widget(self._threshold_value_label)
        slider_row.add_widget(plus_btn)
        threshold_section.add_widget(slider_row)

        threshold_presets = PresetRow(
            values=[50, 80, 100, 130, 160],
            callback=lambda v: setattr(self._threshold_slider, 'value', v),
        )
        threshold_section.add_widget(threshold_presets)

        # Audio threshold metric picker
        audio_metric_label = Label(
            text="Audio control metric:",
            font_size=F.BODY,
            size_hint_y=None,
            height=dp(24),
            color=C.TEXT_SECONDARY,
            halign="left",
        )
        audio_metric_label.bind(size=audio_metric_label.setter("text_size"))
        threshold_section.add_widget(audio_metric_label)

        self._audio_metric_radios: dict[str, CheckBox] = {}
        self._audio_metric_selected: str = "shamatha_score"
        self._on_audio_metric_change: Optional[Callable] = None
        self._on_audio_formula_index_cb: Optional[Callable] = None
        self._audio_formula_index_selected: int = 0
        self._audio_formula_index_buttons: list[StyledButton] = []
        audio_metric_options = {
            "shamatha_score": "Shamatha Score",
            "native_meditation": "NS Meditation",
            "native_attention": "NS Attention",
            "custom_formula": "Custom Formula",
        }
        for key, display_name in audio_metric_options.items():
            row = BoxLayout(size_hint_y=None, height=dp(32), spacing=S.GAP)
            rb = CheckBox(
                group="audio_metric",
                active=(key == "shamatha_score"),
                size_hint_x=0.15,
                size_hint_y=None, height=dp(32),
            )
            rb.audio_metric_key = key
            rb.bind(active=self._on_audio_metric_radio)
            lbl = Label(
                text=display_name,
                font_size=F.BODY,
                color=C.TEXT,
                size_hint_x=0.85,
                halign="left", valign="middle",
            )
            lbl.bind(size=lbl.setter("text_size"))
            row.add_widget(rb)
            row.add_widget(lbl)
            threshold_section.add_widget(row)
            self._audio_metric_radios[key] = rb

        # Formula slot index selector (shown below the custom-formula radio)
        index_row = BoxLayout(size_hint_y=None, height=dp(32), spacing=S.GAP)
        index_row.add_widget(Label(
            text="    Slot:",
            font_size=F.SMALL,
            color=C.TEXT_SECONDARY,
            size_hint_x=0.25,
            halign="left", valign="middle",
        ))
        btn_box = BoxLayout(size_hint_x=0.75, spacing=S.GAP)
        for slot_idx, slot_label in enumerate(("1", "2", "3")):
            btn = StyledButton(
                text=slot_label,
                font_size=F.SMALL,
                size_hint_y=None,
                height=dp(28),
                bg_color=C.ACCENT if slot_idx == 0 else C.BG_CARD,
                text_color=C.TEXT,
            )
            btn._slot_idx = slot_idx
            btn.bind(on_release=self._on_audio_formula_index_pressed)
            btn_box.add_widget(btn)
            self._audio_formula_index_buttons.append(btn)
        index_row.add_widget(btn_box)
        threshold_section.add_widget(index_row)

        # --- Audio section ---
        audio_section = accordion.add_section("Audio", collapsed=True)

        audio_desc = Label(
            text=(
                "Rain noise — volume decreases as meditation deepens\n"
                "Test: noise sweep (0-max-0), sinking bell (dullness > 60, every 15s),\n"
                "distraction chime (subtle > 30, every 20s), disconnect warble (device lost)"
            ),
            font_size=F.SMALL,
            size_hint_y=None,
            height=dp(50),
            color=C.TEXT_SECONDARY,
            halign="left",
        )
        audio_desc.bind(size=audio_desc.setter("text_size"))
        audio_section.add_widget(audio_desc)

        # Test Audio button
        self._test_audio_btn = StyledButton(
            text="Test Audio",
            font_size=F.H3,
            bold=True,
            bg_color=C.PRIMARY,
            size_hint_y=None,
            height=dp(40),
        )
        self._test_audio_btn.bind(on_release=self._on_test_audio_pressed)
        audio_section.add_widget(self._test_audio_btn)

        # Sinking alert toggle
        sinking_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP)
        self._sinking_alert_cb = CheckBox(
            active=False, size_hint_x=0.15,
            size_hint_y=None, height=dp(36),
        )
        self._sinking_alert_cb.bind(active=self._on_sinking_alert_change)
        sinking_lbl = Label(
            text="Enable Sinking Alert Bell",
            font_size=F.BODY,
            color=C.TEXT,
            size_hint_x=0.85,
            halign="left", valign="middle",
        )
        sinking_lbl.bind(size=sinking_lbl.setter("text_size"))
        sinking_row.add_widget(self._sinking_alert_cb)
        sinking_row.add_widget(sinking_lbl)
        audio_section.add_widget(sinking_row)

        # Subtle distraction alert toggle
        subtle_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP)
        self._subtle_alert_cb = CheckBox(
            active=False, size_hint_x=0.15,
            size_hint_y=None, height=dp(36),
        )
        self._subtle_alert_cb.bind(active=self._on_subtle_alert_change)
        subtle_lbl = Label(
            text="Enable Distraction Chime",
            font_size=F.BODY,
            color=C.TEXT,
            size_hint_x=0.85,
            halign="left", valign="middle",
        )
        subtle_lbl.bind(size=subtle_lbl.setter("text_size"))
        subtle_row.add_widget(self._subtle_alert_cb)
        subtle_row.add_widget(subtle_lbl)
        audio_section.add_widget(subtle_row)

        # Disconnect alert toggle
        disconnect_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP)
        self._disconnect_alert_cb = CheckBox(
            active=APP.DISCONNECT_ALERT_ENABLED, size_hint_x=0.15,
            size_hint_y=None, height=dp(36),
        )
        self._disconnect_alert_cb.bind(active=self._on_disconnect_alert_change)
        disconnect_lbl = Label(
            text="Audio alert on disconnect / signal loss",
            font_size=F.BODY,
            color=C.TEXT,
            size_hint_x=0.85,
            halign="left", valign="middle",
        )
        disconnect_lbl.bind(size=disconnect_lbl.setter("text_size"))
        disconnect_row.add_widget(self._disconnect_alert_cb)
        disconnect_row.add_widget(disconnect_lbl)
        audio_section.add_widget(disconnect_row)

        # --- Display section ---
        display_section = accordion.add_section("Display", collapsed=True)

        # Line width slider
        lw_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP)
        lw_label = Label(
            text="Line Width:", font_size=F.BODY,
            color=C.TEXT,
            size_hint_x=0.3, halign="left",
        )
        lw_label.bind(size=lw_label.setter("text_size"))
        self._line_width_slider = Slider(
            min=0.5, max=4.0, value=1.2, step=0.1, size_hint_x=0.5,
        )
        self._line_width_value = Label(
            text="1.2", font_size=F.BODY, bold=True, color=C.TEXT, size_hint_x=0.2,
        )
        self._line_width_slider.bind(value=self._on_line_width_slider)
        lw_row.add_widget(lw_label)
        lw_row.add_widget(self._line_width_slider)
        lw_row.add_widget(self._line_width_value)
        display_section.add_widget(lw_row)

        lw_presets = PresetRow(
            values=[0.5, 1.0, 1.5, 2.0, 3.0],
            callback=lambda v: setattr(self._line_width_slider, 'value', v),
            fmt="{}",
        )
        display_section.add_widget(lw_presets)

        # Screen rotation button
        self._rotate_btn = StyledButton(
            text="Rotate Screen (0\u00b0)",
            font_size=F.BODY,
            bg_color=C.PRIMARY_DIM,
            size_hint_y=None,
            height=dp(36),
        )
        self._rotate_btn.bind(on_release=self._on_rotate_pressed)
        self._current_rotation: int = 0
        display_section.add_widget(self._rotate_btn)

        # Marker hotkey picker
        marker_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP)
        marker_lbl = Label(
            text="Marker Hotkey:", font_size=F.BODY,
            color=C.TEXT,
            size_hint_x=0.35, halign="left",
        )
        marker_lbl.bind(size=marker_lbl.setter("text_size"))
        self._marker_hotkey_btn = StyledButton(
            text="m",
            font_size=F.BODY,
            bold=True,
            bg_color=C.BG_CARD,
            text_color=C.PRIMARY,
            size_hint_x=0.35,
            size_hint_y=None,
            height=dp(36),
        )
        self._marker_hotkey_btn.bind(on_release=self._on_marker_hotkey_pressed)
        self._marker_hotkey_clear = StyledButton(
            text="Clear",
            font_size=F.SMALL,
            bg_color=C.BG_CARD,
            text_color=C.DANGER,
            size_hint_x=0.3,
            size_hint_y=None,
            height=dp(36),
        )
        self._marker_hotkey_clear.bind(on_release=self._on_marker_hotkey_clear)
        marker_row.add_widget(marker_lbl)
        marker_row.add_widget(self._marker_hotkey_btn)
        marker_row.add_widget(self._marker_hotkey_clear)
        display_section.add_widget(marker_row)
        self._marker_hotkey: str = "m"
        self._waiting_for_hotkey: bool = False

        # Graph series are now chosen via the on-graph series picker (combobox);
        # the former "Graph Metrics" checkbox section was removed (subsumed).
        # _graph_toggles (above) remains as the first-run default selection.

        # --- Custom Formula section ---
        formula_section = accordion.add_section("Custom Formula", collapsed=True)

        formula_desc = Label(
            text=(
                "Enter a Python-style formula to track as an extra metric.\n"
                "Leave empty to disable."
            ),
            font_size=F.SMALL,
            size_hint_y=None,
            height=dp(32),
            color=C.TEXT_SECONDARY,
            halign="left",
        )
        formula_desc.bind(size=formula_desc.setter("text_size"))
        formula_section.add_widget(formula_desc)

        # Three named formula slots, each with name + formula inputs,
        # Apply/Save buttons, and a status label.
        self._formula_inputs: list[TextInput] = []
        self._formula_name_inputs: list[TextInput] = []
        self._formula_statuses: list[Label] = []
        for i in range(3):
            slot_header = Label(
                text=f"Formula {i + 1}",
                font_size=F.SMALL,
                bold=True,
                size_hint_y=None,
                height=dp(20),
                color=C.TEXT_SECONDARY,
                halign="left",
            )
            slot_header.bind(size=slot_header.setter("text_size"))
            formula_section.add_widget(slot_header)

            name_input = TextInput(
                text="",
                hint_text=f"name (default Custom {i + 1})",
                font_size=F.SMALL,
                size_hint_y=None,
                height=dp(36),
                multiline=False,
                background_color=list(C.BG_INPUT),
                foreground_color=C.TEXT,
            )
            name_input.bind(on_text_validate=lambda _w, idx=i: self._submit_slot(idx))
            self._formula_name_inputs.append(name_input)
            formula_section.add_widget(name_input)

            formula_input = TextInput(
                text="",
                hint_text="e.g. (alpha1 + alpha2) / (beta1 + beta2 + 1)",
                font_size=F.BODY,
                size_hint_y=None,
                height=dp(40),
                multiline=False,
                background_color=list(C.BG_INPUT),
                foreground_color=C.TEXT,
            )
            formula_input.bind(
                on_text_validate=lambda _w, idx=i: self._submit_slot(idx)
            )
            self._formula_inputs.append(formula_input)
            formula_section.add_widget(formula_input)

            formula_btns = BoxLayout(
                size_hint_y=None, height=dp(34), spacing=S.GAP_SM
            )
            apply_btn = StyledButton(
                text="Apply",
                font_size=F.BODY,
                bg_color=C.PRIMARY,
                size_hint_y=None,
                height=dp(34),
            )
            apply_btn.bind(on_release=lambda _w, idx=i: self._submit_slot(idx))
            formula_btns.add_widget(apply_btn)

            save_btn = StyledButton(
                text="Save",
                font_size=F.BODY,
                bg_color=C.ACCENT,
                size_hint_y=None,
                height=dp(34),
            )
            save_btn.bind(on_release=lambda _w, idx=i: self._save_slot(idx))
            formula_btns.add_widget(save_btn)
            formula_section.add_widget(formula_btns)

            status = Label(
                text="",
                font_size=F.SMALL,
                size_hint_y=None,
                height=dp(20),
                color=C.ACCENT,
                halign="left",
            )
            status.bind(size=status.setter("text_size"))
            self._formula_statuses.append(status)
            formula_section.add_widget(status)

        # Saved formulas header with export button
        saved_header = BoxLayout(size_hint_y=None, height=dp(26), spacing=S.GAP_SM)
        saved_label = Label(
            text="Saved Formulas:",
            font_size=F.SMALL,
            size_hint_x=0.6,
            color=C.TEXT_SECONDARY,
            halign="left",
        )
        saved_label.bind(size=saved_label.setter("text_size"))
        saved_header.add_widget(saved_label)

        export_formulas_btn = StyledButton(
            text="Export to .txt",
            font_size=F.SMALL,
            bg_color=C.BG_CARD,
            text_color=C.TEXT_SECONDARY,
            size_hint_x=0.4,
            size_hint_y=None,
            height=dp(26),
        )
        export_formulas_btn.bind(on_release=self._on_export_formulas_pressed)
        saved_header.add_widget(export_formulas_btn)
        formula_section.add_widget(saved_header)

        self._saved_formulas_box = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(0),
            spacing=dp(2),
        )
        formula_section.add_widget(self._saved_formulas_box)

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
            font_size=F.BODY,
            size_hint_y=None,
            height=dp(130),
            color=C.TEXT_MUTED,
            halign="left",
            valign="top",
        )
        examples.bind(size=examples.setter("text_size"))
        formula_section.add_widget(examples)

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
            font_size=F.SMALL,
            size_hint_y=None,
            height=dp(225),
            color=C.TEXT_MUTED,
            halign="left",
            valign="top",
        )
        ref.bind(size=ref.setter("text_size"))
        formula_section.add_widget(ref)

        # --- Theme section ---
        theme_section = accordion.add_section("Theme", collapsed=True)

        self._theme_buttons = {}
        theme_row = BoxLayout(
            size_hint_y=None, height=dp(36), spacing=S.GAP_SM,
        )
        for theme_name in THEMES:
            is_active = theme_name == C.theme_name
            btn = StyledButton(
                text=theme_name,
                bg_color=C.PRIMARY if is_active else C.BG_CARD,
                text_color=C.TEXT if is_active else C.TEXT_SECONDARY,
                font_size=F.TINY,
                height=dp(34),
                bold=is_active,
            )
            btn._theme_name = theme_name
            btn.bind(on_release=self._on_theme_select)
            theme_row.add_widget(btn)
            self._theme_buttons[theme_name] = btn
        theme_section.add_widget(theme_row)

        theme_note = Label(
            text="Theme change takes effect on next app restart",
            font_size=F.TINY,
            color=C.TEXT_MUTED,
            size_hint_y=None,
            height=dp(18),
            halign="left",
        )
        theme_note.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        theme_section.add_widget(theme_note)

        # --- Developer Tools section ---
        dev_section = accordion.add_section("Developer Tools", collapsed=True)

        dev_desc = Label(
            text="Trigger unhandled exceptions to verify crash-handler hooks.",
            font_size=F.SMALL,
            size_hint_y=None,
            height=dp(20),
            color=C.TEXT_SECONDARY,
            halign="left",
        )
        dev_desc.bind(size=dev_desc.setter("text_size"))
        dev_section.add_widget(dev_desc)

        def _trigger_kivy_crash(_btn):
            raise RuntimeError("dev-trigger kivy-loop")

        def _trigger_clock_crash(_btn):
            def _boom(dt):
                raise RuntimeError("dev-trigger kivy-clock")

            Clock.schedule_once(_boom, 0)

        def _trigger_thread_crash(_btn):

            def _boom():
                raise RuntimeError("dev-trigger thread")

            threading.Thread(target=_boom, daemon=True, name="CrashTestThread").start()

        btn_kivy = StyledButton(
            text="Crash: Kivy event",
            font_size=F.BODY,
            bg_color=C.DANGER,
            size_hint_y=None,
            height=dp(36),
        )
        btn_kivy.bind(on_release=_trigger_kivy_crash)
        dev_section.add_widget(btn_kivy)

        btn_clock = StyledButton(
            text="Crash: Kivy clock",
            font_size=F.BODY,
            bg_color=C.DANGER,
            size_hint_y=None,
            height=dp(36),
        )
        btn_clock.bind(on_release=_trigger_clock_crash)
        dev_section.add_widget(btn_clock)

        btn_thread = StyledButton(
            text="Crash: thread",
            font_size=F.BODY,
            bg_color=C.DANGER,
            size_hint_y=None,
            height=dp(36),
        )
        btn_thread.bind(on_release=_trigger_thread_crash)
        dev_section.add_widget(btn_thread)

        # --- Help section (loaded from app/assets/help/) ---
        help_section = accordion.add_section("Help & Troubleshooting", collapsed=True)
        help_topics = _load_help_topics()
        for topic_title, topic_text in help_topics:
            topic_label = Label(
                text=f"[b]{topic_title}[/b]",
                markup=True,
                font_size=F.BODY,
                color=C.PRIMARY,
                size_hint_y=None,
                height=dp(24),
                halign="left",
            )
            topic_label.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
            help_section.add_widget(topic_label)

            body = Label(
                text=topic_text,
                font_size=F.SMALL,
                color=C.TEXT_SECONDARY,
                size_hint_y=None,
                halign="left",
                valign="top",
            )
            body.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
            body.bind(texture_size=lambda w, v: setattr(w, "height", v[1] + dp(8)))
            help_section.add_widget(body)

            help_section.add_widget(Divider())

        scroll.add_widget(accordion)
        root.add_widget(scroll)
        self._accordion = accordion
        self._settings_scroll = scroll
        self.add_widget(root)

    def _update_bg(self, *args) -> None:
        root = self.children[0] if self.children else None
        if root and hasattr(self, '_bg_rect'):
            self._bg_rect.size = root.size
            self._bg_rect.pos = root.pos

    def _on_slider_value(self, instance, value) -> None:
        val = int(value)
        self._threshold_value_label.text = str(val)
        if self._on_threshold_change:
            self._on_threshold_change(val)

    def _step_threshold(self, delta: int) -> None:
        """Nudge the threshold by `delta`, clamped to the slider range. Setting
        the slider value fires _on_slider_value (label + callback)."""
        s = self._threshold_slider
        s.value = max(s.min, min(s.max, int(s.value) + delta))

    def _on_test_audio_pressed(self, *args) -> None:
        if self._on_test_audio:
            self._on_test_audio()

    def _on_sinking_alert_change(self, checkbox, active) -> None:
        if self._on_sinking_alert_toggle:
            self._on_sinking_alert_toggle(active)

    def _on_subtle_alert_change(self, checkbox, active) -> None:
        if self._on_subtle_alert_toggle:
            self._on_subtle_alert_toggle(active)

    def _on_disconnect_alert_change(self, checkbox, active) -> None:
        if self._on_disconnect_alert_toggle:
            self._on_disconnect_alert_toggle(active)

    def _on_line_width_slider(self, instance, value) -> None:
        val = round(value, 1)
        self._line_width_value.text = f"{val:.1f}"
        if self._on_line_width_change:
            self._on_line_width_change(val)

    def _submit_slot(self, idx: int) -> None:
        if self._on_formula_slot_change:
            name = self._formula_name_inputs[idx].text.strip()
            self._on_formula_slot_change(idx, name, self._formula_inputs[idx].text.strip())

    def _save_slot(self, idx: int) -> None:
        """Save a slot's formula to the library, seeding the entry from its name."""
        if self._on_save_formula:
            self._on_save_formula(idx, self._formula_name_inputs[idx].text.strip(),
                                  self._formula_inputs[idx].text.strip())

    def set_formula_slot_status(self, idx: int, text: str, is_error: bool = False) -> None:
        self._formula_statuses[idx].text = text
        self._formula_statuses[idx].color = C.DANGER if is_error else C.ACCENT

    def set_formula_slot_callback(self, callback: Callable) -> None:
        self._on_formula_slot_change = callback

    def set_formula_slot(self, idx: int, name: str, formula: str) -> None:
        """Reflect a programmatic slot change (load/restore) in the inputs."""
        self._formula_name_inputs[idx].text = name
        self._formula_inputs[idx].text = formula

    def _on_rotate_pressed(self, *args) -> None:
        self._current_rotation = (self._current_rotation + 90) % 360
        self._rotate_btn.text = f"Rotate Screen ({self._current_rotation}\u00b0)"
        if self._on_rotate_screen:
            self._on_rotate_screen(self._current_rotation)

    def _on_marker_hotkey_pressed(self, *args) -> None:
        """Enter hotkey capture mode — next key press sets the marker hotkey."""
        self._waiting_for_hotkey = True
        self._marker_hotkey_btn.text = "Press a key..."
        self._marker_hotkey_btn.bg_color = list(C.WARM)
        Window.bind(on_key_down=self._on_hotkey_capture)

    def _on_hotkey_capture(self, window, key, scancode, codepoint, modifiers) -> bool:
        """Capture a single key press for the marker hotkey."""
        if not self._waiting_for_hotkey:
            return False
        Window.unbind(on_key_down=self._on_hotkey_capture)
        self._waiting_for_hotkey = False
        # Use codepoint (printable char) or Kivy key name
        key_name = codepoint if codepoint else Keyboard.keycode_to_string(Keyboard(), key)
        if key_name:
            self._marker_hotkey = key_name
            self._marker_hotkey_btn.text = key_name
        else:
            self._marker_hotkey_btn.text = f"key {key}"
            self._marker_hotkey = str(key)
        self._marker_hotkey_btn.bg_color = list(C.BG_CARD)
        return True

    def _on_marker_hotkey_clear(self, *args) -> None:
        """Clear the marker hotkey (disable keyboard marker)."""
        if self._waiting_for_hotkey:
            Window.unbind(on_key_down=self._on_hotkey_capture)
            self._waiting_for_hotkey = False
        self._marker_hotkey = ""
        self._marker_hotkey_btn.text = "(none)"
        self._marker_hotkey_btn.bg_color = list(C.BG_CARD)

    @property
    def marker_hotkey(self) -> str:
        return self._marker_hotkey

    @marker_hotkey.setter
    def marker_hotkey(self, value: str) -> None:
        self._marker_hotkey = value
        self._marker_hotkey_btn.text = value if value else "(none)"

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

    def set_test_audio_callback(self, callback: Callable) -> None:
        self._on_test_audio = callback

    def set_sinking_alert_callback(self, callback: Callable) -> None:
        self._on_sinking_alert_toggle = callback

    def set_subtle_alert_callback(self, callback: Callable) -> None:
        self._on_subtle_alert_toggle = callback

    def set_disconnect_alert_callback(self, callback: Callable) -> None:
        self._on_disconnect_alert_toggle = callback

    def set_line_width_callback(self, callback: Callable) -> None:
        self._on_line_width_change = callback

    def set_rotate_screen_callback(self, callback: Callable) -> None:
        self._on_rotate_screen = callback

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
            row = BoxLayout(size_hint_y=None, height=row_height, spacing=S.GAP_SM)

            load_btn = StyledButton(
                text=entry.get("name", entry.get("formula", "")[:30]),
                font_size=F.SMALL,
                bg_color=C.BG_CARD,
                text_color=C.TEXT,
                size_hint_x=0.65,
                size_hint_y=None,
                height=row_height,
                bold=False,
            )
            load_btn.formula_index = i
            load_btn.bind(on_release=self._on_load_formula_pressed)
            row.add_widget(load_btn)

            del_btn = StyledButton(
                text="X",
                font_size=F.SMALL,
                bg_color=C.BG_CARD,
                text_color=C.DANGER,
                size_hint_x=0.12,
                size_hint_y=None,
                height=row_height,
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

    def set_copy_diagnostics_callback(self, callback: Callable) -> None:
        self._on_copy_diagnostics = callback

    def _on_diagnostics_pressed(self, *_args) -> None:
        if self._on_copy_diagnostics:
            self._on_copy_diagnostics()

    # --- Timer end sound: path input, browse, test ----------------------

    @property
    def timer_sound_path(self) -> str:
        return self._timer_sound_input.text.strip()

    @timer_sound_path.setter
    def timer_sound_path(self, value: str) -> None:
        self._timer_sound_input.text = value or ""

    def set_timer_sound_change_callback(self, callback: Callable) -> None:
        self._on_timer_sound_change = callback

    def set_test_timer_sound_callback(self, callback: Callable) -> None:
        self._on_test_timer_sound = callback

    def set_stop_timer_sound_callback(self, callback: Callable) -> None:
        self._on_stop_timer_sound = callback

    def _on_timer_sound_path_change(self, _instance, value: str) -> None:
        if self._on_timer_sound_change:
            self._on_timer_sound_change(value.strip())

    def _on_timer_sound_test(self, *_args) -> None:
        """Toggle play/stop for the test sound — long custom files would
        otherwise keep playing with no UI control to interrupt."""
        if self._timer_sound_test_playing:
            if self._on_stop_timer_sound:
                self._on_stop_timer_sound()
            self.notify_timer_sound_test_ended()
        else:
            if self._on_test_timer_sound:
                self._on_test_timer_sound()
            self._timer_sound_test_playing = True
            self._timer_sound_test_btn.text = "Stop"

    def notify_timer_sound_test_ended(self) -> None:
        """Called by app_manager when the test playback ends naturally
        (Sound.on_stop fires) so the button text reverts."""
        self._timer_sound_test_playing = False
        self._timer_sound_test_btn.text = "Test"

    def _on_timer_sound_browse(self, *_args) -> None:
        """Open a file chooser popup for audio files."""
        start_path = os.path.expanduser("~")
        chooser = FileChooserListView(
            path=start_path,
            filters=["*.wav", "*.mp3", "*.ogg", "*.flac", "*.m4a"],
        )
        content = BoxLayout(orientation="vertical", spacing=dp(8))
        content.add_widget(chooser)
        btn_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        btn_cancel = Button(text="Cancel", font_size=F.SMALL)
        btn_select = Button(
            text="Select", font_size=F.SMALL,
            background_color=(0.2, 0.6, 0.3, 1.0),
        )
        btn_row.add_widget(btn_cancel)
        btn_row.add_widget(btn_select)
        content.add_widget(btn_row)
        popup = Popup(
            title="Choose audio file",
            content=content,
            size_hint=(0.9, 0.85),
        )

        def _on_select(*_):
            sel = chooser.selection
            if sel:
                self._timer_sound_input.text = sel[0]
            popup.dismiss()

        btn_cancel.bind(on_release=popup.dismiss)
        btn_select.bind(on_release=_on_select)
        popup.open()

    def populate_bt_devices(self, devices: list) -> None:
        """Populate the BT device list with scan results."""
        self._bt_device_list.clear_widgets()
        if not devices:
            lbl = Label(
                text="No paired devices found",
                font_size=F.SMALL,
                size_hint_y=None,
                height=dp(28),
                color=C.TEXT_SECONDARY,
            )
            self._bt_device_list.add_widget(lbl)
            return
        for dev in devices:
            btn = StyledButton(
                text=f"{dev['name']}  ({dev['address']})",
                font_size=F.SMALL,
                bg_color=C.BG_CARD,
                text_color=C.TEXT,
                size_hint_y=None,
                height=dp(32),
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
            self._device_status_label.color = C.CONNECTED
            # User has resolved the picker prompt — clear the banner.
            self._set_device_picker_banner("")
        else:
            self._device_status_label.text = "Not connected"
            self._device_status_label.color = C.DISCONNECTED
        if meta:
            self._device_meta_label.text = meta
        elif self._device_mode_cb.active:
            self._device_meta_label.text = "Mode: Mock Data"
        else:
            self._device_meta_label.text = "Mode: Real Device"

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
            scroll = getattr(self, "_settings_scroll", None)
            section = getattr(self, "_device_section", None)
            if scroll is not None and section is not None:
                try:
                    scroll.scroll_to(section)
                except Exception:  # noqa: BLE001
                    pass

        # Defer to next frame so the section's expanded height is laid out
        # before we ask the ScrollView to bring it into view.
        Clock.schedule_once(_scroll, 0)

    # --- Audio threshold metric picker ---

    def _on_audio_metric_radio(self, checkbox, active) -> None:
        if not active:
            return
        key = getattr(checkbox, "audio_metric_key", None)
        if key:
            self._audio_metric_selected = key
            if self._on_audio_metric_change:
                self._on_audio_metric_change(key)

    def _on_theme_select(self, btn) -> None:
        """Handle theme button press."""
        name = btn._theme_name
        C.set_theme(name)
        # Update button visuals
        for tname, tbtn in self._theme_buttons.items():
            if tname == name:
                tbtn.bg_color = C.PRIMARY
                tbtn.text_color = C.TEXT
                tbtn.bold = True
            else:
                tbtn.bg_color = C.BG_CARD
                tbtn.text_color = C.TEXT_SECONDARY
                tbtn.bold = False
        # Save via callback
        if self._on_theme_change:
            self._on_theme_change(name)

    def set_theme_callback(self, callback: Callable) -> None:
        self._on_theme_change = callback

    @property
    def selected_theme(self) -> str:
        return C.theme_name

    def set_audio_metric_callback(self, callback: Callable) -> None:
        self._on_audio_metric_change = callback

    def set_audio_formula_index_callback(self, callback: Callable) -> None:
        self._on_audio_formula_index_cb = callback

    def _on_audio_formula_index_pressed(self, btn) -> None:
        idx = getattr(btn, "_slot_idx", 0)
        self.audio_formula_index = idx
        if self._on_audio_formula_index_cb:
            self._on_audio_formula_index_cb(idx)

    # --- Profile callbacks and methods ---

    def set_profile_callbacks(self, on_switch=None, on_create=None, on_delete=None):
        self._on_profile_switch = on_switch
        self._on_profile_create = on_create
        self._on_profile_delete = on_delete

    def set_session_counter(self, fn):
        """app_manager wires this to count per-user sessions for the form."""
        self._session_counter = fn

    def set_backup_callback(self, cb: Callable) -> None:
        self._on_backup_pressed = cb

    def set_restore_callback(self, cb: Callable) -> None:
        self._on_restore_pressed = cb

    def show_backup_status(self, text: str) -> None:
        self._backup_status.text = text

    def _count_user_sessions(self, user_id: int) -> int:
        if getattr(self, "_session_counter", None) is None:
            return 0
        return self._session_counter(user_id)

    def _on_form_create_pressed(self, name: str) -> None:
        if self._on_profile_create:
            self._on_profile_create(name)

    def _on_form_pick_existing(self, user_id: int) -> None:
        if self._on_profile_switch:
            self._on_profile_switch(user_id)

    def _on_form_delete_pressed(self, user_id: int) -> None:
        # Look up the name from the most recently populated list
        name = ""
        for u in self._user_picker_form._users:
            if u["id"] == user_id:
                name = u["name"]
                break
        self._confirm_user_delete(user_id, name)

    def _confirm_user_delete(self, user_id, user_name):
        """Show confirmation before deleting a user."""
        content = BoxLayout(orientation="vertical", spacing=S.GAP, padding=S.GAP)
        msg_label = Label(
            text=f'Delete user "{user_name}"?\nAll their settings will be lost.',
            font_size=F.BODY, color=POPUP_TEXT,  # dark popup chrome: keep body light
            halign="center", valign="middle", size_hint_y=0.6,
        )
        msg_label.bind(size=msg_label.setter("text_size"))
        content.add_widget(msg_label)
        btn_row = BoxLayout(spacing=S.GAP, size_hint_y=0.4)
        btn_cancel = StyledButton(text="Cancel", bg_color=C.BG_CARD, text_color=C.TEXT_SECONDARY, height=dp(38))
        btn_confirm = StyledButton(text="Delete", icon=Icons.DELETE, bg_color=C.DANGER, height=dp(38))
        btn_row.add_widget(btn_cancel)
        btn_row.add_widget(btn_confirm)
        content.add_widget(btn_row)
        popup = Popup(title="Confirm Delete", content=content, size_hint=(0.7, 0.3), auto_dismiss=True)
        btn_cancel.bind(on_release=popup.dismiss)

        def _do_delete(*args):
            popup.dismiss()
            if self._on_profile_delete:
                self._on_profile_delete(user_id)

        btn_confirm.bind(on_release=_do_delete)
        popup.open()

    def populate_users(self, users, current_user_id=None):
        """Fill the user picker form."""
        self._user_picker_form.populate_users(users)
        if current_user_id is None:
            self._profile_current_label.text = "Current: All Users"
        else:
            for u in users:
                if u["id"] == current_user_id:
                    self._profile_current_label.text = f"Current: {u['name']}"
                    break

    # --- Timer properties ---

    @property
    def timer_enabled(self) -> bool:
        return self._timer_enable_cb.active

    @timer_enabled.setter
    def timer_enabled(self, value: bool):
        self._timer_enable_cb.active = value

    @property
    def timer_minutes(self) -> int:
        return int(self._timer_duration_slider.value)

    @timer_minutes.setter
    def timer_minutes(self, value: int):
        self._timer_duration_slider.value = value
        self._timer_duration_label.text = f"{value} min"

    @property
    def audio_metric(self) -> str:
        return self._audio_metric_selected

    @audio_metric.setter
    def audio_metric(self, key: str) -> None:
        self._audio_metric_selected = key
        for k, rb in self._audio_metric_radios.items():
            rb.active = (k == key)

    @property
    def audio_formula_index(self) -> int:
        return self._audio_formula_index_selected

    @audio_formula_index.setter
    def audio_formula_index(self, idx: int) -> None:
        self._audio_formula_index_selected = idx
        for i, btn in enumerate(self._audio_formula_index_buttons):
            btn.bg_color = C.ACCENT if i == idx else C.BG_CARD
