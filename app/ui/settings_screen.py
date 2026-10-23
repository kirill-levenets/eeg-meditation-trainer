import os
import re
import threading
from collections.abc import Callable

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.checkbox import CheckBox
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider

from app import android_jni
from app.config import METRICS
from app.logger import logger
from app.ui.hooks import Hook
from app.ui.settings_sections.audio import AudioSection
from app.ui.settings_sections.common import (
    checkbox_row,
)
from app.ui.settings_sections.device import DeviceSection
from app.ui.settings_sections.display import DisplaySection
from app.ui.settings_sections.formulas import FormulaSection
from app.ui.settings_sections.timer import TimerSection
from app.ui.theme import (
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
    format_count,
    make_message_popup,
)
from app.ui.widgets.user_picker import UserPickerForm

HELP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "help")
_HELP_FILE_LANG = {"uk": "ua"}  # the help files' suffix where it isn't the ISO 639 code


def help_language() -> str:
    """The first wanted language with a help file, else English: Android's locale, or LANGUAGE's list in order and then
    the first of LC_ALL / LC_MESSAGES / LANG (Windows and macOS builds usually set none of these)."""
    try:
        if android_jni.on_android():
            wanted = [android_jni.language()]
        else:
            first_set = next((os.environ[v] for v in ("LC_ALL", "LC_MESSAGES", "LANG") if os.environ.get(v)), "")
            wanted = [*os.environ.get("LANGUAGE", "").split(":"), first_set]
    except Exception:  # noqa: BLE001 - the help falls back to English rather than break the Settings screen
        logger.exception("Device language lookup failed; help in English")
        wanted = []
    for tag in wanted:
        code = re.match(r"[A-Za-z]*", tag).group().lower()
        code = _HELP_FILE_LANG.get(code, code)
        if code and os.path.exists(os.path.join(HELP_DIR, f"help_{code}.txt")):
            return code
    return "en"


def _load_help_topics(lang: str = "en") -> list[tuple[str, str]]:
    """Load help topics from app/assets/help/help_{lang}.txt.

    File format: sections separated by '## Title' lines.
    Returns list of (title, body) tuples.
    """
    path = os.path.join(HELP_DIR, f"help_{lang}.txt")
    if not os.path.exists(path):
        # Fallback to English
        path = os.path.join(HELP_DIR, "help_en.txt")
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

    on_threshold_change = Hook()
    on_theme_change = Hook()
    on_audio_metric_change = Hook()
    on_audio_formula_index = Hook()
    on_profile_switch = Hook()
    on_profile_create = Hook()
    on_profile_delete = Hook()
    session_counter = Hook(default=0)
    on_backup_pressed = Hook()
    on_restore_pressed = Hook()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "settings"
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
            text="Current: none",
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

        self._backup_btn.bind(on_release=lambda *a: self.on_backup_pressed())
        self._restore_btn.bind(on_release=lambda *a: self.on_restore_pressed())

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
        self.display = DisplaySection(accordion.add_section("Display", collapsed=True))

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
        help_topics = _load_help_topics(help_language())
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
        self.on_threshold_change(val)

    def _step_threshold(self, delta: int) -> None:
        """Nudge the threshold by `delta`, clamped to the slider range. Setting
        the slider value fires _on_slider_value (label + callback)."""
        s = self._threshold_slider
        s.value = max(s.min, min(s.max, int(s.value) + delta))

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
            self.on_audio_metric_change(key)

    def _on_theme_select(self, btn) -> None:
        name = btn._theme_name
        C.set_theme(name)
        self.on_theme_change(name)

    def _show_active_theme(self) -> None:
        """Highlight the active theme's button, whoever applied it (this selector or a profile's settings load)."""
        for name, btn in self._theme_buttons.items():
            active = name == C.theme_name
            btn.bg_color = C.PRIMARY if active else C.BG_CARD
            btn.text_color = None if active else C.TEXT_SECONDARY
            btn.bold = active

    def _on_audio_formula_index_pressed(self, btn) -> None:
        idx = getattr(btn, "_slot_idx", 0)
        self.audio_formula_index = idx
        self.on_audio_formula_index(idx)

    # --- Profile callbacks and methods ---

    def show_backup_status(self, text: str) -> None:
        self._backup_status.text = text

    def _count_user_sessions(self, user_id: int) -> int:
        return self.session_counter(user_id)

    def _on_form_create_pressed(self, name: str) -> None:
        self.on_profile_create(name)

    def _on_form_pick_existing(self, user_id: int) -> None:
        self.on_profile_switch(user_id)

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
            self.on_profile_delete(user_id)

        btn_confirm.bind(on_release=_do_delete)
        popup.open()

    def populate_users(self, users, current_user_id=None):
        """Fill the user picker form."""
        self._user_picker_form.populate_users(users)
        name = next((u["name"] for u in users if u["id"] == current_user_id), "none")  # none: the gate is up
        self._profile_current_label.text = f"Current: {name}"

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
