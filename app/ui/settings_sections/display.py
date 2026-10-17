"""Settings → Display: text size, the scored line's colours, line width, screen rotation and the marker hotkey."""

from kivy.core.window import Keyboard, Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.slider import Slider

from app.ui.hooks import Hook
from app.ui.line_colours import LINE_COLOURS, MONO, GradientStrip
from app.ui.line_colours import OPTIONS as LINE_OPTIONS
from app.ui.theme import (
    TEXT_SIZES,
    C,
    F,
    PresetRow,
    S,
    StyledButton,
    ThemedLabel,
    fit_row_to_text,
)


class DisplaySection:
    """Builds the section's content into `section` and reports the user's actions through its callbacks."""

    on_line_width_change = Hook()
    on_rotate_screen = Hook()
    on_text_size = Hook()
    on_line_colours = Hook()

    def __init__(self, section) -> None:
        self._build(section)

    def _build(self, section) -> None:

        # Text size: every font in the app, applied at once (F.set_scale).
        ts_label = ThemedLabel(text="Text size:", font_size=F.BODY, color=C.TEXT, halign="left", size_hint_y=None,
                               height=dp(28))
        ts_label.bind(size=ts_label.setter("text_size"))
        section.add_widget(ts_label)
        self._text_size_presets = PresetRow(items=[(name, scale) for scale, name in TEXT_SIZES],
                                            callback=self._on_text_size_pressed)
        section.add_widget(self._text_size_presets)
        self._show_text_size()
        F.add_listener(self._show_text_size)

        # Scored line colours (#94): the trained series in its own colour or a gradient by value, on every graph at once.
        lc_label = ThemedLabel(text="Scored line colours:", font_size=F.BODY, color=C.TEXT, halign="left",
                               size_hint_y=None, height=dp(28))
        lc_label.bind(size=lc_label.setter("text_size"))
        section.add_widget(lc_label)
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
        section.add_widget(lw_row)

        lw_presets = PresetRow(
            values=[0.5, 1.0, 1.5, 2.0, 3.0],
            callback=lambda v: setattr(self._line_width_slider, 'value', v),
            fmt="{}",
        )
        section.add_widget(lw_presets)

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
        section.add_widget(self._rotate_btn)

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
        section.add_widget(marker_row)
        self._marker_hotkey: str = "m"
        self._waiting_for_hotkey: bool = False

    def _on_line_width_slider(self, instance, value) -> None:
        val = round(value, 1)
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
