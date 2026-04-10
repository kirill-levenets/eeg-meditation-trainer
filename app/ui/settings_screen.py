from typing import Callable, Dict, Optional

from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.accordion import Accordion, AccordionItem
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput

from app.config import APP, METRICS
from app.ui.theme import C, F, S, Icons, StyledButton, SectionLabel, Divider, PresetRow, style_accordion


def _make_section_content() -> BoxLayout:
    """Create a standard vertical BoxLayout for accordion section content."""
    content = BoxLayout(
        orientation="vertical",
        size_hint_y=None,
        spacing=S.GAP,
        padding=[dp(4), S.GAP_SM],
    )
    content.bind(minimum_height=content.setter("height"))
    return content


def _wrap_in_scroll(content: BoxLayout) -> ScrollView:
    """Wrap a content BoxLayout in a ScrollView for accordion items."""
    sv = ScrollView()
    sv.add_widget(content)
    return sv


class SettingsScreen(Screen):
    """Settings screen with threshold, audio controls, device info, and toggles."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "settings"
        self._on_threshold_change: Optional[Callable] = None
        self._on_toggle_change: Optional[Callable] = None
        self._on_test_audio: Optional[Callable] = None
        self._on_sinking_alert_toggle: Optional[Callable] = None
        self._on_subtle_alert_toggle: Optional[Callable] = None
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
        self._on_theme_change: Optional[Callable] = None
        self._graph_toggles: Dict[str, bool] = {
            "meditation_score": True,
            "shamatha_score": True,
            "distraction": True,
            "sinking": True,
            "subtle_distraction": True,
        }
        self._build_ui()

    def _build_ui(self) -> None:
        root = BoxLayout(orientation="vertical")

        # Screen background
        with root.canvas.before:
            Color(*C.BG)
            self._bg_rect = Rectangle(size=root.size, pos=root.pos)
        root.bind(size=self._update_bg, pos=self._update_bg)

        accordion = Accordion(orientation="vertical", min_space=dp(36), anim_duration=0.15)

        # --- Profile section ---
        profile_item = AccordionItem(title="User Profile", collapse=False)
        profile_content = _make_section_content()

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
        profile_content.add_widget(self._profile_current_label)

        create_row = BoxLayout(size_hint_y=None, height=S.ROW_H, spacing=S.GAP)
        self._profile_name_input = TextInput(
            hint_text="New user name...",
            multiline=False,
            font_size=F.BODY,
            foreground_color=C.TEXT,
            background_color=list(C.BG_INPUT),
            size_hint_x=0.6,
        )
        self._profile_create_btn = StyledButton(
            text="Create",
            bg_color=C.ACCENT,
            bg_pressed=C.ACCENT_DIM,
            font_size=F.BODY,
            size_hint_x=0.4,
        )
        create_row.add_widget(self._profile_name_input)
        create_row.add_widget(self._profile_create_btn)
        profile_content.add_widget(create_row)

        self._profile_user_list = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=S.GAP_SM,
        )
        self._profile_user_list.bind(
            minimum_height=self._profile_user_list.setter("height")
        )
        profile_content.add_widget(self._profile_user_list)

        profile_item.add_widget(_wrap_in_scroll(profile_content))
        accordion.add_widget(profile_item)

        # --- Timer section ---
        timer_item = AccordionItem(title="Timer", collapse=True)
        timer_content = _make_section_content()

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
        timer_content.add_widget(timer_toggle_row)

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
        timer_content.add_widget(timer_dur_row)

        timer_presets = PresetRow(
            values=[5, 10, 15, 20, 30],
            callback=lambda v: setattr(self._timer_duration_slider, "value", v),
            fmt="{} min",
        )
        timer_content.add_widget(timer_presets)

        timer_item.add_widget(_wrap_in_scroll(timer_content))
        accordion.add_widget(timer_item)

        # --- Device Status section ---
        device_item = AccordionItem(title="Device", collapse=True)
        device_content = _make_section_content()

        self._device_status_label = Label(
            text="Not connected",
            font_size=F.BODY,
            size_hint_y=None,
            height=dp(24),
            color=C.DISCONNECTED,
            halign="left",
        )
        self._device_status_label.bind(size=self._device_status_label.setter("text_size"))
        device_content.add_widget(self._device_status_label)

        self._device_meta_label = Label(
            text="Mode: Mock Data",
            font_size=F.SMALL,
            size_hint_y=None,
            height=dp(20),
            color=C.TEXT_MUTED,
            halign="left",
        )
        self._device_meta_label.bind(size=self._device_meta_label.setter("text_size"))
        device_content.add_widget(self._device_meta_label)

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
        device_content.add_widget(device_mode_row)

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
        device_content.add_widget(self._bt_section)

        device_item.add_widget(_wrap_in_scroll(device_content))
        accordion.add_widget(device_item)

        # --- Threshold section ---
        threshold_item = AccordionItem(title="Threshold", collapse=True)
        threshold_content = _make_section_content()

        slider_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=S.GAP)
        self._threshold_slider = Slider(
            min=20,
            max=100,
            value=METRICS.MEDITATION_THRESHOLD_DEFAULT,
            step=1,
            size_hint_x=0.8,
        )
        self._threshold_value_label = Label(
            text=str(METRICS.MEDITATION_THRESHOLD_DEFAULT),
            font_size=F.H2,
            bold=True,
            color=C.TEXT,
            size_hint_x=0.2,
        )
        self._threshold_slider.bind(value=self._on_slider_value)
        slider_row.add_widget(self._threshold_slider)
        slider_row.add_widget(self._threshold_value_label)
        threshold_content.add_widget(slider_row)

        threshold_presets = PresetRow(
            values=[30, 50, 70, 85, 100],
            callback=lambda v: setattr(self._threshold_slider, 'value', v),
        )
        threshold_content.add_widget(threshold_presets)

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
        threshold_content.add_widget(audio_metric_label)

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
            threshold_content.add_widget(row)
            self._audio_metric_radios[key] = rb

        threshold_item.add_widget(_wrap_in_scroll(threshold_content))
        accordion.add_widget(threshold_item)

        # --- Audio section ---
        audio_item = AccordionItem(title="Audio", collapse=True)
        audio_content = _make_section_content()

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
        audio_content.add_widget(audio_desc)

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
        audio_content.add_widget(self._test_audio_btn)

        # Sinking alert toggle
        sinking_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP)
        self._sinking_alert_cb = CheckBox(
            active=True, size_hint_x=0.15,
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
        audio_content.add_widget(sinking_row)

        # Subtle distraction alert toggle
        subtle_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP)
        self._subtle_alert_cb = CheckBox(
            active=True, size_hint_x=0.15,
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
        audio_content.add_widget(subtle_row)

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
        audio_content.add_widget(disconnect_row)

        audio_item.add_widget(_wrap_in_scroll(audio_content))
        accordion.add_widget(audio_item)

        # --- Display section ---
        display_item = AccordionItem(title="Display", collapse=True)
        display_content = _make_section_content()

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
        display_content.add_widget(lw_row)

        lw_presets = PresetRow(
            values=[0.5, 1.0, 1.5, 2.0, 3.0],
            callback=lambda v: setattr(self._line_width_slider, 'value', v),
            fmt="{}",
        )
        display_content.add_widget(lw_presets)

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
        display_content.add_widget(self._rotate_btn)

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
        display_content.add_widget(marker_row)
        self._marker_hotkey: str = "m"
        self._waiting_for_hotkey: bool = False

        display_item.add_widget(_wrap_in_scroll(display_content))
        accordion.add_widget(display_item)

        # --- Graph toggles ---
        graph_item = AccordionItem(title="Graph Metrics", collapse=True)
        graph_content = _make_section_content()

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
            row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP)
            cb = CheckBox(
                active=True, size_hint_x=0.15,
                size_hint_y=None, height=dp(36),
            )
            cb.metric_key = key
            cb.bind(active=self._on_toggle)
            lbl = Label(
                text=display_name,
                font_size=F.H3,
                color=C.TEXT,
                size_hint_x=0.85,
                halign="left", valign="middle",
            )
            lbl.bind(size=lbl.setter("text_size"))
            row.add_widget(cb)
            row.add_widget(lbl)
            graph_content.add_widget(row)
            self._checkboxes[key] = cb

        # Custom formula visibility toggle
        cf_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP)
        self._custom_formula_cb = CheckBox(
            active=False, size_hint_x=0.15,
            size_hint_y=None, height=dp(36),
        )
        self._custom_formula_cb.bind(active=self._on_custom_formula_toggle)
        self._on_custom_formula_visible_change: Optional[Callable] = None
        cf_lbl = Label(
            text="Show Custom Formula",
            font_size=F.H3,
            color=C.TEXT,
            size_hint_x=0.85,
            halign="left", valign="middle",
        )
        cf_lbl.bind(size=cf_lbl.setter("text_size"))
        cf_row.add_widget(self._custom_formula_cb)
        cf_row.add_widget(cf_lbl)
        graph_content.add_widget(cf_row)

        graph_item.add_widget(_wrap_in_scroll(graph_content))
        accordion.add_widget(graph_item)

        # --- Custom Formula section ---
        formula_item = AccordionItem(title="Custom Formula", collapse=True)
        formula_content = _make_section_content()

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
        formula_content.add_widget(formula_desc)

        self._formula_input = TextInput(
            text="",
            hint_text="e.g. (alpha1 + alpha2) / (beta1 + beta2 + 1)",
            font_size=F.BODY,
            size_hint_y=None,
            height=dp(40),
            multiline=False,
            background_color=list(C.BG_INPUT),
            foreground_color=C.TEXT,
        )
        self._formula_input.bind(on_text_validate=self._on_formula_submit)
        formula_content.add_widget(self._formula_input)

        formula_btns = BoxLayout(
            size_hint_y=None, height=dp(34), spacing=S.GAP_SM
        )
        formula_btn = StyledButton(
            text="Apply",
            font_size=F.BODY,
            bg_color=C.PRIMARY,
            size_hint_y=None,
            height=dp(34),
        )
        formula_btn.bind(on_release=self._on_formula_submit)
        formula_btns.add_widget(formula_btn)

        save_btn = StyledButton(
            text="Save",
            font_size=F.BODY,
            bg_color=C.ACCENT,
            size_hint_y=None,
            height=dp(34),
        )
        save_btn.bind(on_release=self._on_save_formula_pressed)
        formula_btns.add_widget(save_btn)
        formula_content.add_widget(formula_btns)

        self._formula_status = Label(
            text="",
            font_size=F.SMALL,
            size_hint_y=None,
            height=dp(20),
            color=C.ACCENT,
            halign="left",
        )
        self._formula_status.bind(size=self._formula_status.setter("text_size"))
        formula_content.add_widget(self._formula_status)

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
        formula_content.add_widget(saved_header)

        self._saved_formulas_box = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(0),
            spacing=dp(2),
        )
        formula_content.add_widget(self._saved_formulas_box)

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
        formula_content.add_widget(examples)

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
        formula_content.add_widget(ref)

        formula_item.add_widget(_wrap_in_scroll(formula_content))
        accordion.add_widget(formula_item)

        # --- Theme section ---
        theme_item = AccordionItem(title="Theme", collapse=True)
        theme_content = _make_section_content()

        self._theme_buttons = {}
        theme_row = BoxLayout(
            size_hint_y=None, height=dp(36), spacing=S.GAP_SM,
        )
        from app.ui.theme import THEMES
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
        theme_content.add_widget(theme_row)

        theme_note = Label(
            text="Theme change takes effect on next app restart",
            font_size=F.TINY,
            color=C.TEXT_MUTED,
            size_hint_y=None,
            height=dp(18),
            halign="left",
        )
        theme_note.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        theme_content.add_widget(theme_note)

        theme_item.add_widget(_wrap_in_scroll(theme_content))
        accordion.add_widget(theme_item)

        root.add_widget(accordion)
        self._accordion = accordion
        self.add_widget(root)
        # Defer accordion styling until screen has real size
        from kivy.clock import Clock
        Clock.schedule_once(lambda dt: style_accordion(self._accordion), 0.5)

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

    def _on_formula_submit(self, *args) -> None:
        formula = self._formula_input.text.strip()
        if self._on_custom_formula_change:
            self._on_custom_formula_change(formula)

    def set_formula_status(self, text: str, is_error: bool = False) -> None:
        self._formula_status.text = text
        if is_error:
            self._formula_status.color = C.DANGER
        else:
            self._formula_status.color = C.ACCENT

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
        from kivy.core.window import Keyboard
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

    def set_toggle_callback(self, callback: Callable) -> None:
        self._on_toggle_change = callback

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
        else:
            self._device_status_label.text = "Not connected"
            self._device_status_label.color = C.DISCONNECTED
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

    # --- Profile callbacks and methods ---

    def set_profile_callbacks(self, on_switch=None, on_create=None, on_delete=None):
        self._on_profile_switch = on_switch
        self._on_profile_create = on_create
        self._on_profile_delete = on_delete
        self._profile_create_btn.bind(on_release=self._on_profile_create_pressed)

    def _confirm_user_delete(self, user_id, user_name):
        """Show confirmation before deleting a user."""
        from kivy.uix.popup import Popup
        content = BoxLayout(orientation="vertical", spacing=S.GAP, padding=S.GAP)
        content.add_widget(Label(
            text=f'Delete user "{user_name}"?\nAll their settings will be lost.',
            font_size=F.BODY, color=C.TEXT,
            halign="center", valign="middle", size_hint_y=0.6,
        ))
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

    def _on_profile_create_pressed(self, *args):
        name = self._profile_name_input.text.strip()
        if name and self._on_profile_create:
            self._on_profile_create(name)
            self._profile_name_input.text = ""

    def populate_users(self, users, current_user_id=None):
        """Fill the user list in the Profile section."""
        self._profile_user_list.clear_widgets()
        if current_user_id is None:
            self._profile_current_label.text = "Current: All Users"
        else:
            for u in users:
                if u["id"] == current_user_id:
                    self._profile_current_label.text = f"Current: {u['name']}"
                    break

        for u in users:
            is_active = u["id"] == current_user_id
            row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP_SM)
            btn = StyledButton(
                text=u["name"],
                bg_color=C.ACCENT_DIM if is_active else C.BG_CARD,
                text_color=C.TEXT if is_active else C.TEXT_SECONDARY,
                font_size=F.BODY,
                height=dp(36),
                bold=is_active,
            )
            btn._user_id = u["id"]
            btn.bind(on_release=lambda b: (
                self._on_profile_switch(b._user_id) if self._on_profile_switch else None
            ))
            row.add_widget(btn)

            del_btn = StyledButton(
                text="", icon=Icons.DELETE,
                bg_color=C.DANGER,
                text_color=C.DANGER,
                font_size=F.SMALL,
                height=dp(36),
                size_hint_x=None,
                width=dp(40),
                bold=False,
                outline=True,
            )
            del_btn._user_id = u["id"]
            del_btn._user_name = u["name"]
            del_btn.bind(on_release=lambda b: self._confirm_user_delete(b._user_id, b._user_name))
            row.add_widget(del_btn)
            self._profile_user_list.add_widget(row)

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
