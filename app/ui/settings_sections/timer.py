"""Settings → Timer / Program: Simple or Program mode, the simple timer, the program editor in Program mode, and the
timer's end sound, which either mode plays."""
from collections.abc import Callable

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.slider import Slider

from app.logger import logger
from app.ui.hooks import Hook
from app.ui.settings_sections.common import checkbox_row, open_sound_picker, source_label
from app.ui.settings_sections.program_editor import ProgramEditor
from app.ui.theme import C, F, S, ThemedLabel, text_fills_box
from app.ui.widgets.choice_toggle import ChoiceToggle
from app.ui.widgets.rows import PresetRow
from app.ui.widgets.styled_button import StyledButton

_PRESETS = (("5m", 5), ("10m", 10), ("15m", 15), ("20m", 20), ("30m", 30), ("1h", 60), ("1h30", 90), ("2h", 120))
_TIMER_SOUND_OPTIONS: tuple[tuple[str, str], ...] = (("Default bell", ""), ("Custom file...", "custom"))


class TimerSection:
    """Builds the mode and the simple timer into `section`, and shows the mode's controls: Simple's Enable Timer,
    duration and presets, or Program's editor (`editor`). A pick of the mode is reported through its hook."""

    on_mode = Hook()

    def __init__(self, section, *, saved_formulas: Callable[[], list[dict]]) -> None:
        self.editor = ProgramEditor(saved_formulas)
        row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP)
        row.add_widget(ThemedLabel(text="Mode:", font_size=F.BODY, color=C.TEXT_SECONDARY, size_hint_x=0.25,
                                   halign="left", valign="middle"))
        self._mode_toggle = ChoiceToggle([("simple", "Simple"), ("program", "Program")], "simple", self._on_mode_chosen,
                                         button={"font_size": F.SMALL, "size_hint_y": None, "height": dp(28)},
                                         size_hint_x=0.75, spacing=S.GAP)
        row.add_widget(self._mode_toggle)
        section.add_widget(row)
        # Holds the mode's controls alone: the other mode's are detached, since a hidden box's children would still
        # overflow it and take taps meant for the controls around it.
        self._mode_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=S.GAP_SM)
        self._mode_box.bind(minimum_height=self._mode_box.setter("height"))
        section.add_widget(self._mode_box)
        self._simple_box = self._build_simple()
        self.show_mode("simple")

    def _build_simple(self) -> BoxLayout:
        """Enable Timer (Program mode always times), the duration slider and its presets."""
        box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=S.GAP)
        box.bind(minimum_height=box.setter("height"))
        enable_row, self._enable_box = checkbox_row("Enable Timer", S.ROW_SM, active=False)
        box.add_widget(enable_row)
        row = BoxLayout(size_hint_y=None, height=S.ROW_SM, spacing=S.GAP)
        label = ThemedLabel(text="Duration:", font_size=F.BODY, color=C.TEXT_SECONDARY, size_hint_x=0.25, halign="left")
        text_fills_box(label)
        self._slider = Slider(min=1, max=120, value=20, step=1, size_hint_x=0.55)
        self._minutes_label = ThemedLabel(text="20 min", font_size=F.BODY, bold=True, color=C.TEXT, size_hint_x=0.2)
        self._slider.bind(value=lambda _slider, value: setattr(self._minutes_label, "text", f"{int(value)} min"))
        row.add_widget(label)
        row.add_widget(self._slider)
        row.add_widget(self._minutes_label)
        box.add_widget(row)
        box.add_widget(PresetRow(items=list(_PRESETS), callback=lambda v: setattr(self._slider, "value", v)))
        return box

    def show_mode(self, mode: str) -> None:
        """The mode on its toggle, with its controls (nothing reported)."""
        mode = "program" if mode == "program" else "simple"
        self._mode_toggle.show(mode)
        self._mode_box.clear_widgets()
        self._mode_box.add_widget(self.editor.box if mode == "program" else self._simple_box)

    def _on_mode_chosen(self, mode: str) -> None:
        logger.info(f"Timer mode -> {mode}")
        self.show_mode(mode)
        self.on_mode(mode)

    @property
    def timer_enabled(self) -> bool:
        return self._enable_box.active

    @timer_enabled.setter
    def timer_enabled(self, value: bool) -> None:
        self._enable_box.active = value

    @property
    def timer_minutes(self) -> int:
        return int(self._slider.value)

    @timer_minutes.setter
    def timer_minutes(self, value: int) -> None:
        self._slider.value = value
        self._minutes_label.text = f"{value} min"


def _timer_sound_label(path: str) -> str:
    return source_label("custom", path) if path else "Default bell"


class TimerSound:
    """Builds the timer's end sound into `section`: a button naming it (the default bell or a file), and Test, which
    plays it until it ends or is tapped again. A pick and the Test taps are reported through its hooks."""

    on_change = Hook()  # (the file's path; "" for the default bell)
    on_test = Hook()
    on_stop = Hook()

    def __init__(self, section) -> None:
        self.path = ""  # the default bell
        self._testing = False
        label = ThemedLabel(text="Timer End Sound (optional)", font_size=F.SMALL, color=C.TEXT_SECONDARY,
                            size_hint_y=None, height=dp(20), halign="left")
        text_fills_box(label)
        section.add_widget(label)
        row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP_SM)
        self.button = StyledButton(text=_timer_sound_label(self.path), font_size=F.SMALL, bg_color=C.BG_CARD,
                                   text_color=C.TEXT, size_hint_x=0.75, size_hint_y=None, height=dp(36))
        self.button.bind(on_release=lambda *_a: open_sound_picker("Timer end sound", _TIMER_SOUND_OPTIONS,
                                                                  lambda _source, path: self._apply(path)))
        # Test doubles as Stop: a long custom file would otherwise play on with nothing to interrupt it.
        self.test_button = StyledButton(text="Test", font_size=F.SMALL, bg_color=C.PRIMARY_DIM, size_hint_x=0.25,
                                        size_hint_y=None, height=dp(36))
        self.test_button.bind(on_release=self._on_test_pressed)
        row.add_widget(self.button)
        row.add_widget(self.test_button)
        section.add_widget(row)

    def show(self, path: str) -> None:
        """A loaded sound, on the button (nothing reported)."""
        self.path = path or ""
        self.button.text = _timer_sound_label(self.path)

    def _apply(self, path: str) -> None:
        """The picker's choice ("" for the default bell), shown and reported."""
        self.show(path)
        self.on_change(self.path)

    def _on_test_pressed(self, *_args) -> None:
        if self._testing:
            self.on_stop()
            self.test_ended()
        else:
            self.on_test()
            self._testing = True
            self.test_button.text = "Stop"

    def test_ended(self) -> None:
        """The test sound stopped or played to its end: the button reads Test again."""
        self._testing = False
        self.test_button.text = "Test"
