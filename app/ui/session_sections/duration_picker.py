"""The Session screen's duration picker: Start's companion button showing the session's length (its minutes, ∞ for
none, P for a program), and its popup of presets and saved programs."""
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout

from app.ui.hooks import Hook
from app.ui.theme import (
    ICONS_AVAILABLE,
    C,
    F,
    Icons,
    S,
    ThemedLabel,
    dimmed_fg,
    readable_fg,
    text_fills_box,
    text_width,
)
from app.ui.widgets.popups import make_scroll_popup
from app.ui.widgets.styled_button import StyledButton, cancel_button

_DURATION_PRESETS = [
    ("5 min", 5),
    ("10 min", 10),
    ("15 min", 15),
    ("20 min", 20),
    ("30 min", 30),
    ("1 h", 60),
    ("1 h 30 min", 90),
    ("2 h", 120),
    ("Free", None),
]


class _DurationPickerButton(BoxLayout):
    """Compact 2-row duration picker: text on top, chevron on bottom.

    Press feedback via on_touch_down/up; uses a callback for activation.
    """

    def __init__(self, on_release=None, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.padding = 0
        self.spacing = 0
        self._on_release = on_release
        self._pressed = False

        self._text_label = ThemedLabel(
            text="",
            font_size=F.capped(F.TINY),  # the bottom bar's width is fixed
            bold=True,
            color=C.TEXT,
            halign="center",
            valign="middle",
            size_hint_y=0.55,
        )
        text_fills_box(self._text_label)
        F.add_listener(self._fit_width)
        self._fit_width()

        self._chevron_label = ThemedLabel(
            text=Icons.MENU_DOWN if ICONS_AVAILABLE else "v",
            font_name="Icons" if ICONS_AVAILABLE else "Roboto",
            font_size=F.SMALL,
            color=C.TEXT,
            halign="center",
            valign="middle",
            size_hint_y=0.45,
        )
        text_fills_box(self._chevron_label)
        self.add_widget(self._text_label)
        self.add_widget(self._chevron_label)

        self.bind(size=self._redraw, pos=self._redraw, disabled=self._redraw)
        C.add_listener(self._redraw)
        self._redraw()

    @property
    def text(self) -> str:
        return self._text_label.text

    @text.setter
    def text(self, value: str) -> None:
        self._text_label.text = value
        self._fit_width()

    def _fit_width(self, *_args) -> None:
        """As wide as its text on one line ("105m"), at least 20 dp at the text size in use."""
        label = self._text_label
        self.width = max(F.box(20, F.CAPPED_MAX),
                         text_width(label.text, label.font_size, label.bold, label.font_name) + dp(4))

    def set_label(self, text: str, large: bool = False) -> None:
        """Set the button text; `large` bumps the font (used for the program 'P')."""
        self._text_label.font_size = F.capped(F.H3 if large else F.TINY)
        self._text_label.text = text
        self._fit_width()

    def _redraw(self, *args) -> None:
        self.canvas.before.clear()
        if self.disabled:
            bg = C.BG_CARD
        elif self._pressed:
            bg = C.ACCENT_DIM
        else:
            bg = C.ACCENT
        with self.canvas.before:
            Color(*bg)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[S.RADIUS])
        # The glyph Start's own text takes on the same fill: a pressed fill keeps it, as a StyledButton's does.
        label_color = dimmed_fg(bg) if self.disabled else readable_fg(C.ACCENT)
        for label in (self._text_label, self._chevron_label):
            label.color = label.disabled_color = label_color

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            if self.disabled:
                return True
            self._pressed = True
            self._redraw()
            touch.grab(self)
            return True
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            was_inside = self.collide_point(*touch.pos)
            self._pressed = False
            self._redraw()
            if was_inside and self._on_release is not None:
                self._on_release(self)
            return True
        return super().on_touch_up(touch)



class DurationPicker:
    """The button and its popups, on a copy of Settings → Timer's enable, minutes and program flag."""

    on_program_pick = Hook()  # a saved program picked, by its index
    on_preset = Hook()  # a duration preset picked: minutes, or None for no timer

    def __init__(self) -> None:
        self.button = _DurationPickerButton(
            size_hint_x=None,
            size_hint_y=None,
            height=S.BTN_H,
            on_release=self._open_popup,
        )
        self.button.text = "\u221e"  # updated by refresh
        self._timer_enabled = False
        self._timer_minutes = 0
        self._program_active = False
        self._popup = None
        self._programs: list = []  # the saved programs the "Programs…" picker offers
        self._program_name: str = ""  # the loaded program's (button + highlight)

    def _preset_button(self, label: str, minutes: int | None) -> StyledButton:
        """A preset's button, filled when it is the duration set (None: no timer)."""
        chosen = minutes == self._timer_minutes if self._timer_enabled else minutes is None
        btn = StyledButton(text=label, bg_color=C.ACCENT if chosen else C.BG_CARD,
                           text_color=None if chosen else C.TEXT_SECONDARY, bold=chosen, size_hint_y=None,
                           height=dp(44))
        btn.bind(on_release=lambda _b: self._pick_preset(minutes))
        return btn

    def _open_popup(self, *_args) -> None:
        """The presets: the timed ones two to a row, Free (no timer) across under them, then Programs."""
        timed = [(lbl, v) for lbl, v in _DURATION_PRESETS if v is not None]
        free = [(lbl, v) for lbl, v in _DURATION_PRESETS if v is None]
        grid = GridLayout(cols=2, spacing=S.GAP_SM, size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        for lbl, v in timed:
            grid.add_widget(self._preset_button(lbl, v))
        rows = [grid]
        rows.extend(self._preset_button(lbl, v) for lbl, v in free)

        # Programs picker: jump straight to a saved program from the session
        # screen. The button shows the loaded program's name when one is active.
        programs_btn = StyledButton(
            text=(f"Program: {self._program_name}"
                  if self._program_name else "Programs…"),
            bg_color=C.PRIMARY_DIM,
            size_hint_y=None,
            height=dp(44),
        )
        programs_btn.bind(on_release=lambda *_a: self._open_program_picker())
        rows.append(programs_btn)

        # The grid is one row widget but spans ceil(timed/2) visual rows — count those
        # so the popup sizes to the real content height.
        est = (len(timed) + 1) // 2 + len(free) + 1
        self._popup = make_scroll_popup("Session duration", rows, est_rows=est)
        self._popup.open()

    def set_programs(self, programs: list, current_name: str = "") -> None:
        """Cache the saved programs (+ the loaded one's name) for the picker."""
        self._programs = programs or []
        self._program_name = current_name or ""

    def _open_program_picker(self) -> None:
        """List saved programs; tapping one asks AppManager to load it."""
        if self._popup is not None:
            self._popup.dismiss()
            self._popup = None

        def _pick(index):
            popup.dismiss()
            self.on_program_pick(index)

        rows = []
        if not self._programs:
            rows.append(ThemedLabel(text="No saved programs", color=C.TEXT,
                              size_hint_y=None, height=dp(44)))
        else:
            for i, entry in enumerate(self._programs):
                name = entry.get("name", f"Program {i + 1}")
                is_current = name == self._program_name
                btn = StyledButton(
                    text=name,
                    bg_color=C.ACCENT if is_current else C.BG_CARD,
                    text_color=None if is_current else C.TEXT_SECONDARY,
                    bold=is_current,
                    size_hint_y=None, height=dp(44),
                )
                btn.bind(on_release=lambda _b, idx=i: _pick(idx))
                rows.append(btn)
        cancel = cancel_button(size_hint_y=None, height=dp(44))
        popup = make_scroll_popup("Choose program", rows, footer=cancel)
        cancel.bind(on_release=lambda *_a: popup.dismiss())
        popup.open()

    def _pick_preset(self, value) -> None:
        self.on_preset(value)
        if self._popup is not None:
            self._popup.dismiss()
            self._popup = None

    def refresh(self, timer_enabled: bool, timer_minutes: int, program_active: bool = False) -> None:
        """Cache timer state and update the button's label."""
        self._timer_enabled = timer_enabled
        self._timer_minutes = timer_minutes
        self._program_active = program_active
        self._apply_label()

    def _apply_label(self) -> None:
        # Program mode owns the timer (its total drives the countdown) — show a
        # large "P" instead of a duration so the user sees a program will run.
        if self._program_active:
            self.button.set_label("P", large=True)
        elif not self._timer_enabled:
            self.button.set_label("∞")
        elif self._timer_minutes >= 60 and self._timer_minutes % 60 == 0:
            self.button.set_label(f"{self._timer_minutes // 60}h")
        else:
            self.button.set_label(f"{self._timer_minutes}m")
