"""Settings → Display: text size, the scored line's colours, line width, screen rotation and the marker hotkey."""

from kivy.core.window import Keyboard, Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.slider import Slider

from app.ui.hooks import Hook
from app.ui.line_colours import LINE_COLOURS, MONO, GradientStrip
from app.ui.line_colours import OPTIONS as LINE_OPTIONS
from app.ui.theme import TEXT_SIZES, C, F, S, ThemedLabel, fit_row_to_text, text_fills_box
from app.ui.widgets.rows import PresetRow
from app.ui.widgets.styled_button import StyledButton


def _line_width(slider_value: float) -> float:
    """The width a slider position stands for: its 0.1 step, without the float error a drag leaves."""
    return round(slider_value, 1)


_KEY_NAMES: dict[int, str] = {}
for _name, _code in Keyboard.keycodes.items():
    _KEY_NAMES.setdefault(_code, _name)  # the first name of a code, as Keyboard.keycode_to_string gives it


def key_name(key: int, codepoint: str | None) -> str:
    """A key as the marker hotkey names it: its character, else Kivy's name for it ("f5"), else its code."""
    return codepoint or _KEY_NAMES.get(key) or str(key)


class DisplaySection:
    """Builds the section's content into `section` and reports the user's actions through its callbacks."""

    on_line_width_change = Hook()
    on_rotate_screen = Hook()
    on_text_size = Hook()
    on_line_colours = Hook()

    def __init__(self, section) -> None:
        self._current_rotation: int = 0
        self._marker_hotkey: str = "m"
        self._waiting_for_hotkey: bool = False
        self._build_text_size(section)
        self._build_line_colours(section)
        self._build_line_width(section)
        self._build_rotation(section)
        self._build_marker_hotkey(section)

    @staticmethod
    def _heading(section, text: str) -> None:
        label = ThemedLabel(text=text, font_size=F.BODY, color=C.TEXT, halign="left", size_hint_y=None, height=dp(28))
        text_fills_box(label)
        section.add_widget(label)

    def _build_text_size(self, section) -> None:
        """Text size: every font in the app, applied at once (F.set_scale)."""
        self._heading(section, "Text size:")
        self._text_size_presets = PresetRow(items=[(name, scale) for scale, name in TEXT_SIZES],
                                            callback=self._on_text_size_pressed)
        section.add_widget(self._text_size_presets)
        self._show_text_size()
        F.add_listener(self._show_text_size)

    def _build_line_colours(self, section) -> None:
        """Scored line colours (#94): the trained series in its own colour or a gradient by value, on every graph."""
        self._heading(section, "Scored line colours:")
        self._line_colour_rows = [PresetRow(items=[(label, name) for name, label in LINE_OPTIONS[i:i + 3]],
                                            callback=self._on_line_colours_pressed, height=dp(34))
                                  for i in (0, 3)]
        for row in self._line_colour_rows:
            for name, btn in row.buttons().items():
                if name != MONO:
                    GradientStrip(btn, name)
            section.add_widget(row)
        self._show_line_colours()
        LINE_COLOURS.add_listener(self._show_line_colours)

    def _build_line_width(self, section) -> None:
        """Line width: a slider and presets."""
        lw_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP)
        lw_label = ThemedLabel(text="Line Width:", font_size=F.BODY, color=C.TEXT, size_hint_x=0.3, halign="left")
        text_fills_box(lw_label)
        self._line_width_slider = Slider(min=0.5, max=4.0, value=1.2, step=0.1, size_hint_x=0.5)
        self._line_width_value = ThemedLabel(text="1.2", font_size=F.BODY, bold=True, color=C.TEXT, size_hint_x=0.2)
        self._line_width_slider.bind(value=self._on_line_width_slider)
        for widget in (lw_label, self._line_width_slider, self._line_width_value):
            lw_row.add_widget(widget)
        section.add_widget(lw_row)
        section.add_widget(PresetRow(values=[0.5, 1.0, 1.5, 2.0, 3.0],
                                     callback=lambda v: setattr(self._line_width_slider, "value", v), fmt="{}"))

    def _build_rotation(self, section) -> None:
        self._rotate_btn = StyledButton(text="Rotate Screen (0\u00b0)", font_size=F.BODY, bg_color=C.PRIMARY_DIM,
                                        size_hint_y=None, height=dp(36))
        self._rotate_btn.bind(on_release=self._on_rotate_pressed)
        section.add_widget(self._rotate_btn)

    def _build_marker_hotkey(self, section) -> None:
        """The marker hotkey: its key, picked by pressing it, and Clear."""
        marker_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=S.GAP)
        marker_lbl = ThemedLabel(text="Marker Hotkey:", font_size=F.BODY, color=C.TEXT, size_hint_x=0.35,
                                 halign="left", valign="middle")
        self._marker_hotkey_btn = StyledButton(text="m", font_size=F.BODY, bold=True, bg_color=C.BG_CARD,
                                               text_color=C.PRIMARY, size_hint_x=0.35, size_hint_y=None, height=dp(36))
        self._marker_hotkey_btn.bind(on_release=self._on_marker_hotkey_pressed)
        self._marker_hotkey_clear = StyledButton(text="Clear", font_size=F.SMALL, bg_color=C.BG_CARD,
                                                 text_color=C.DANGER, size_hint_x=0.3, size_hint_y=None, height=dp(36))
        self._marker_hotkey_clear.bind(on_release=self._on_marker_hotkey_clear)
        for widget in (marker_lbl, self._marker_hotkey_btn, self._marker_hotkey_clear):
            marker_row.add_widget(widget)
        fit_row_to_text(marker_row, marker_lbl, dp(36))
        section.add_widget(marker_row)

    @property
    def line_width(self) -> float:
        return self._line_width_slider.value

    def show_line_width(self, width: float) -> None:
        """The slider shows `width`; one already showing it (a drag's unrounded value) is left as it is: a write would
        fire its hook again."""
        if _line_width(self._line_width_slider.value) != width:
            self._line_width_slider.value = width

    def _on_line_width_slider(self, instance, value) -> None:
        val = _line_width(value)
        self._line_width_value.text = f"{val:.1f}"
        self.on_line_width_change(val)

    def _on_rotate_pressed(self, *args) -> None:
        self._current_rotation = (self._current_rotation + 90) % 360
        self._rotate_btn.text = f"Rotate Screen ({self._current_rotation}\u00b0)"
        self.on_rotate_screen(self._current_rotation)

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
        self._marker_hotkey = key_name(key, codepoint)
        self._marker_hotkey_btn.text = self._marker_hotkey if self._marker_hotkey != str(key) else f"key {key}"
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

    def is_marker_key(self, key: int, codepoint: str | None) -> bool:
        """The key pressed is the marker hotkey, named as its capture named it (no key matches a cleared one: a name is
        never empty); never while a new one is being picked."""
        return not self._waiting_for_hotkey and key_name(key, codepoint) == self._marker_hotkey

    @property
    def marker_hotkey(self) -> str:
        return self._marker_hotkey

    @marker_hotkey.setter
    def marker_hotkey(self, value: str) -> None:
        self._marker_hotkey = value
        self._marker_hotkey_btn.text = value if value else "(none)"

    def _show_text_size(self) -> None:
        """Select the size in use, whoever applied it (this picker or a profile's settings load)."""
        self._text_size_presets.set_selected(F.SCALE)

    def _on_text_size_pressed(self, size: float) -> None:
        F.set_scale(size)
        self.on_text_size(size)

    def _show_line_colours(self) -> None:
        """Select the line colours in use, whoever applied them (these rows or a profile's settings load)."""
        for row in self._line_colour_rows:
            row.set_selected(LINE_COLOURS.name)

    def _on_line_colours_pressed(self, name: str) -> None:
        LINE_COLOURS.set(name)
        self.on_line_colours(name)
