import os
import threading
from collections.abc import Callable
from typing import Optional

from kivy.clock import Clock
from kivy.core.window import Keyboard, Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.checkbox import CheckBox
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider

from app.config import METRICS
from app.ui.line_colours import LINE_COLOURS, MONO, GradientStrip
from app.ui.line_colours import OPTIONS as LINE_OPTIONS
from app.ui.settings_sections.audio import AudioSection
from app.ui.settings_sections.common import (
    checkbox_row,
)
from app.ui.settings_sections.device import DeviceSection
from app.ui.settings_sections.formulas import FormulaSection
from app.ui.settings_sections.timer import TimerSection
from app.ui.theme import (
    TEXT_SIZES,
    THEMES,
    C,
    Divider,
    F,
    Icons,
    PresetRow,
    S,
    StyledButton,
    ThemedAccordion,
    ThemedLabel,
    cancel_button,
    fill_background,
    fit_height_to_text,
    fit_row_to_text,
    format_count,
    make_message_popup,
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
        self._on_line_width_change: Optional[Callable] = None
        self._on_rotate_screen: Optional[Callable] = None
        self._on_theme_change: Optional[Callable] = None
        self._graph_toggles: dict[str, bool] = {
            "shamatha_score": True,
            "meditation_score": False,
            "distraction": False,
            "sinking": False,
            "subtle_distraction": False,
            "native_attention": False,
            "native_meditation": False,
        }
        self._build_ui()

    def _build_ui(self) -> None:
        root = BoxLayout(orientation="vertical")

        fill_background(root, C.BG)

        scroll = ScrollView()
        accordion = ThemedAccordion()

        # --- Profile section ---
        profile_section = accordion.add_section("User Profile", collapsed=False)

        self._profile_current_label = ThemedLabel(
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

        # --- Timer / Program section ---
        self.timer = TimerSection(accordion.add_section("Timer / Program", collapsed=True),
                                  saved_formulas=lambda: self.formulas.saved)

        # --- Device Status section ---
        self.device = DeviceSection(accordion.add_section("Device", collapsed=True), scroll=scroll)

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
        self._backup_status = ThemedLabel(
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
        self._threshold_value_label = ThemedLabel(
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
        self._threshold_controls = (slider_row, threshold_presets)
        for controls in self._threshold_controls:
            controls.fbind("on_touch_down", self._on_threshold_controls_touch)

        # Audio threshold metric picker
        audio_metric_label = ThemedLabel(
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
            row, rb = checkbox_row(display_name, dp(32), group="audio_metric", active=(key == "shamatha_score"))
            rb.audio_metric_key = key
            rb.bind(active=self._on_audio_metric_radio)
            threshold_section.add_widget(row)
            self._audio_metric_radios[key] = rb

        # Formula slot index selector (shown below the custom-formula radio)
        index_row = BoxLayout(size_hint_y=None, height=dp(32), spacing=S.GAP)
        index_row.add_widget(ThemedLabel(
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
            )
            btn._slot_idx = slot_idx
            btn.bind(on_release=self._on_audio_formula_index_pressed)
            btn_box.add_widget(btn)
            self._audio_formula_index_buttons.append(btn)
        index_row.add_widget(btn_box)
        threshold_section.add_widget(index_row)

        # --- Audio section ---
        self.audio = AudioSection(accordion.add_section("Audio", collapsed=True))

        # --- Display section ---
        display_section = accordion.add_section("Display", collapsed=True)

        # Text size: every font in the app, applied at once (F.set_scale).
        ts_label = ThemedLabel(text="Text size:", font_size=F.BODY, color=C.TEXT, halign="left", size_hint_y=None,
                               height=dp(28))
        ts_label.bind(size=ts_label.setter("text_size"))
        display_section.add_widget(ts_label)
        self._on_text_size: Callable[[float], None] | None = None
        self._text_size_presets = PresetRow(items=[(name, scale) for scale, name in TEXT_SIZES],
                                            callback=self._on_text_size_pressed)
        display_section.add_widget(self._text_size_presets)
        self._show_text_size()
        F.add_listener(self._show_text_size)

        # Scored line colours (#94): the trained series in its own colour or a gradient by value, on every graph at once.
        lc_label = ThemedLabel(text="Scored line colours:", font_size=F.BODY, color=C.TEXT, halign="left",
                               size_hint_y=None, height=dp(28))
        lc_label.bind(size=lc_label.setter("text_size"))
        display_section.add_widget(lc_label)
        self._on_line_colours: Callable[[str], None] | None = None
        self._line_colour_rows = [PresetRow(items=[(label, name) for name, label in LINE_OPTIONS[i:i + 3]],
                                            callback=self._on_line_colours_pressed, height=dp(34))
                                  for i in (0, 3)]
        for row in self._line_colour_rows:
            for name, btn in row.buttons().items():
                if name != MONO:
                    GradientStrip(btn, name)
            display_section.add_widget(row)
        self._show_line_colours()
        LINE_COLOURS.add_listener(self._show_line_colours)

        # Line width slider
        lw_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP)
        lw_label = ThemedLabel(
            text="Line Width:", font_size=F.BODY,
            color=C.TEXT,
            size_hint_x=0.3, halign="left",
        )
        lw_label.bind(size=lw_label.setter("text_size"))
        self._line_width_slider = Slider(
            min=0.5, max=4.0, value=1.2, step=0.1, size_hint_x=0.5,
        )
        self._line_width_value = ThemedLabel(
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
        marker_lbl = ThemedLabel(
            text="Marker Hotkey:", font_size=F.BODY,
            color=C.TEXT,
            size_hint_x=0.35, halign="left", valign="middle",
        )
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
        fit_row_to_text(marker_row, marker_lbl, dp(36))
        display_section.add_widget(marker_row)
        self._marker_hotkey: str = "m"
        self._waiting_for_hotkey: bool = False

        # Graph series are now chosen via the on-graph series picker (combobox);
        # the former "Graph Metrics" checkbox section was removed (subsumed).
        # _graph_toggles (above) remains as the first-run default selection.

        # --- Custom Formula section ---
        self.formulas = FormulaSection(accordion.add_section("Custom Formula", collapsed=True))

        # --- Theme section ---
        theme_section = accordion.add_section("Theme", collapsed=True)

        self._theme_buttons = {}
        theme_row = BoxLayout(
            size_hint_y=None, height=dp(36), spacing=S.GAP_SM,
        )
        for theme_name in THEMES:
            btn = StyledButton(text=theme_name, font_size=F.TINY, height=dp(34))
            btn._theme_name = theme_name
            btn.bind(on_release=self._on_theme_select)
            theme_row.add_widget(btn)
            self._theme_buttons[theme_name] = btn
        theme_section.add_widget(theme_row)
        self._show_active_theme()
        C.add_listener(self._show_active_theme)

        # --- Developer Tools section ---
        dev_section = accordion.add_section("Developer Tools", collapsed=True)

        dev_desc = ThemedLabel(
            text="Trigger unhandled exceptions to verify crash-handler hooks.",
            font_size=F.SMALL,
            size_hint_y=None,
            color=C.TEXT_SECONDARY,
            halign="left",
        )
        fit_height_to_text(dev_desc)
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
            topic_label = ThemedLabel(
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

            body = ThemedLabel(
                text=topic_text,
                font_size=F.SMALL,
                color=C.TEXT_SECONDARY,
                size_hint_y=None,
                halign="left",
                valign="top",
            )
            fit_height_to_text(body, extra=dp(8))
            help_section.add_widget(body)

            help_section.add_widget(Divider())

        scroll.add_widget(accordion)
        root.add_widget(scroll)
        self._accordion = accordion
        self._settings_scroll = scroll
        self.add_widget(root)

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

    def _on_line_width_slider(self, instance, value) -> None:
        val = round(value, 1)
        self._line_width_value.text = f"{val:.1f}"
        if self._on_line_width_change:
            self._on_line_width_change(val)

    def _on_rotate_pressed(self, *args) -> None:
        self._current_rotation = (self._current_rotation + 90) % 360
        self._rotate_btn.text = f"Rotate Screen ({self._current_rotation}\u00b0)"
        if self._on_rotate_screen:
            self._on_rotate_screen(self._current_rotation)

    def _on_marker_hotkey_pressed(self, *args) -> None:
        """Enter hotkey capture mode — next key press sets the marker hotkey."""
        self._waiting_for_hotkey = True
        self._marker_hotkey_btn.text = "Press a key..."
        self._marker_hotkey_btn.bg_color = C.WARM
        self._marker_hotkey_btn.text_color = None  # AUTO on the capture fill
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
        self._marker_hotkey_btn.bg_color = C.BG_CARD
        self._marker_hotkey_btn.text_color = C.PRIMARY
        return True

    def _on_marker_hotkey_clear(self, *args) -> None:
        """Clear the marker hotkey (disable keyboard marker)."""
        if self._waiting_for_hotkey:
            Window.unbind(on_key_down=self._on_hotkey_capture)
            self._waiting_for_hotkey = False
        self._marker_hotkey = ""
        self._marker_hotkey_btn.text = "(none)"
        self._marker_hotkey_btn.bg_color = C.BG_CARD
        self._marker_hotkey_btn.text_color = C.PRIMARY

    @property
    def marker_hotkey(self) -> str:
        return self._marker_hotkey

    @marker_hotkey.setter
    def marker_hotkey(self, value: str) -> None:
        self._marker_hotkey = value
        self._marker_hotkey_btn.text = value if value else "(none)"

    @property
    def threshold(self) -> int:
        return int(self._threshold_slider.value)

    @threshold.setter
    def threshold(self, value: int) -> None:
        self._threshold_slider.value = value

    _threshold_lock: Callable[[], bool] | None = None

    def lock_threshold(self, on_touch: Callable[[], bool] | None) -> None:
        """Dim the threshold controls; a touch on them goes to `on_touch` instead, whenever that refuses it."""
        self._threshold_lock = on_touch
        for controls in self._threshold_controls:
            controls.opacity = 0.5 if on_touch else 1.0

    def _on_threshold_controls_touch(self, controls, touch) -> bool:
        if self._threshold_lock is None or not controls.collide_point(*touch.pos):
            return False
        # True: the slider, the -/+ buttons and the presets never see it, a mouse wheel included (it steps the slider)
        return bool(self._threshold_lock())

    def set_threshold_callback(self, callback: Callable) -> None:
        self._on_threshold_change = callback

    def set_line_width_callback(self, callback: Callable) -> None:
        self._on_line_width_change = callback

    def set_rotate_screen_callback(self, callback: Callable) -> None:
        self._on_rotate_screen = callback

    def _show_text_size(self) -> None:
        """Select the size in use, whoever applied it (this picker or a profile's settings load)."""
        self._text_size_presets.set_selected(F.SCALE)

    def set_text_size_callback(self, callback: Callable[[float], None]) -> None:
        self._on_text_size = callback

    def _on_text_size_pressed(self, size: float) -> None:
        F.set_scale(size)
        if self._on_text_size:
            self._on_text_size(size)

    def _show_line_colours(self) -> None:
        """Select the line colours in use, whoever applied them (these rows or a profile's settings load)."""
        for row in self._line_colour_rows:
            row.set_selected(LINE_COLOURS.name)

    def set_line_colours_callback(self, callback: Callable[[str], None]) -> None:
        self._on_line_colours = callback

    def _on_line_colours_pressed(self, name: str) -> None:
        LINE_COLOURS.set(name)
        if self._on_line_colours:
            self._on_line_colours(name)

    def on_pre_enter(self, *args) -> None:
        # The link may have dropped between sessions, with nothing on screen to report it.
        self.device.mark_bt_devices()

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
        name = btn._theme_name
        C.set_theme(name)
        if self._on_theme_change:
            self._on_theme_change(name)

    def _show_active_theme(self) -> None:
        """Highlight the active theme's button, whoever applied it (this selector or a profile's settings load)."""
        for name, btn in self._theme_buttons.items():
            active = name == C.theme_name
            btn.bg_color = C.PRIMARY if active else C.BG_CARD
            btn.text_color = None if active else C.TEXT_SECONDARY
            btn.bold = active

    def set_theme_callback(self, callback: Callable) -> None:
        self._on_theme_change = callback

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
        n = self._count_user_sessions(user_id)
        message = (f'Delete profile "{user_name}"?\n\n'
                   f"Its {format_count(n, 'session')} and all its settings will be permanently deleted.\n"
                   "This cannot be undone.")
        btn_cancel = cancel_button()
        btn_confirm = StyledButton(text="Delete", icon=Icons.DELETE, bg_color=C.DANGER)
        popup = make_message_popup("Confirm Delete", message, [btn_cancel, btn_confirm])
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
