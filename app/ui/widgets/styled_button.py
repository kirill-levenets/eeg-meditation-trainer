"""The app's button: a rounded fill that shifts when pressed, its glyph colour readable on it, an optional icon."""

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label

from app.ui.theme import ICONS_AVAILABLE, C, F, S, ThemedMixin, dimmed_fg, readable_fg, text_fills_box, text_width


class StyledButton(ThemedMixin, ButtonBehavior, BoxLayout):
    """Rounded button with press color shift. Replaces default Kivy Button.

    Usage:
        btn = StyledButton(text="Start", bg_color=C.ACCENT)  # glyph colour: AUTO for the fill
        btn.bind(on_release=callback)
    """
    text = StringProperty("")
    bg_color = ListProperty(list(C.PRIMARY))
    bg_pressed = ListProperty([0, 0, 0, 0])  # auto-derived if left empty
    text_color = ListProperty(list(C.TEXT))
    font_size = NumericProperty(0)  # F.BODY unless given; its text and icon follow it (_follow_font_size)
    bold = BooleanProperty(True)
    icon = StringProperty("")  # optional left-side icon text
    outline = BooleanProperty(False)  # draw border instead of fill
    _ring_alpha = NumericProperty(0.0)  # press-ring opacity: snaps on at press, fades on release

    _RING_MAX = 0.9
    _RING_FADE = 0.28  # seconds

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", S.BTN_H)
        kwargs.setdefault("bg_color", C.PRIMARY)
        kwargs.setdefault("font_size", F.BODY)
        vertical = kwargs.pop("vertical", False)
        padding = kwargs.pop("padding", None)  # fixed sides; by default they fit the text (_fit_padding)
        # AUTO while text_color is None (the default; assign None to return to it): the light or dark glyph with the
        # higher contrast against THIS button's bg, re-picked whenever the bg changes. A palette text_color (C.X)
        # follows the theme through ThemedMixin; any other is fixed. A selected state is an accent fill + AUTO.
        self._auto_text = True
        super().__init__(**kwargs)
        self._apply_role_text()
        self.orientation = "vertical" if vertical else "horizontal"
        self.padding = padding if padding is not None else ([dp(2), dp(2)] if vertical else [S.BTN_PAD, 0])
        self._fits_padding = padding is None and not vertical
        self._fit_measure: tuple = ((), 0.0)  # (what was measured, its one-line width)
        self._vertical = vertical
        self._build_children()

        self._confirming = False
        self._confirm_orig = None
        self._confirm_ev = None

        self.bind(
            text=self._update_label,
            bold=self._update_label,
            text_color=self._paint_glyphs,
            bg_color=self._repaint,
            size=self._redraw,
            pos=self._redraw,
            disabled=self._on_disabled,
            _ring_alpha=self._redraw,
            font_size=self._follow_font_size,
        )
        if self._fits_padding:
            self.bind(width=self._fit_padding, text=self._fit_padding, bold=self._fit_padding, icon=self._fit_padding)
            self._fit_padding()
        self._redraw()
        C.add_listener(self._repaint)

    def _build_children(self) -> None:
        """The text label, with the icon beside it, above it (vertical) or instead of it (no text)."""
        self._label = Label(text=self.text, color=self.text_color, font_size=self._text_font(), bold=self.bold,
                            halign="center", valign="middle")
        text_fills_box(self._label)
        self._icon_label, self._icon_extra = None, 0.0  # the icon's size over the button's font
        if self.icon and ICONS_AVAILABLE:
            if not self.text:
                self._icon_extra, layout = dp(6), {"centred": True}
            elif self._vertical:  # icon on top, text under it: the mobile tab-bar convention
                self._icon_extra, layout = dp(2), {"centred": True, "size_hint_y": 0.6}
                self._label.size_hint_y = 0.4
            else:
                self._icon_extra, layout = dp(4), {"centred": False, "size_hint_x": None, "width": dp(26)}
            self._icon_label = self._make_icon_label(**layout)
            self.add_widget(self._icon_label)
        if self._icon_label is None or self.text:  # an icon-only button shows no text label
            self.add_widget(self._label)

    def _make_icon_label(self, centred: bool, **layout) -> Label:
        """The icon glyph _icon_extra above the button's font; a centred one fills its box."""
        label = Label(text=self.icon, font_name="Icons", font_size=self.font_size + self._icon_extra,
                      color=self.text_color, **layout)
        if centred:
            label.halign, label.valign = "center", "middle"
            text_fills_box(label)
        return label

    def _text_font(self) -> float:
        return float(F.TINY) if self._vertical and self.icon else self.font_size  # a plain Label takes a plain size

    def _follow_font_size(self, *_args) -> None:
        """The text and icon take the button's font, as a text size change re-applies it."""
        self._label.font_size = self._text_font()
        if self._icon_label is not None:
            self._icon_label.font_size = self.font_size + self._icon_extra
        if self._fits_padding:
            self._fit_padding()

    def _one_line_width(self) -> float:
        """The width the text (and icon) take on one line, measured once per text, icon and size."""
        text_shown = self._label.parent is not None and bool(self._label.text) and not self._label.markup
        key = (self._label.text, self.icon, self._label.font_size, self.bold, text_shown, self.spacing)
        if key != self._fit_measure[0]:
            width = 0.0
            if text_shown:
                width += text_width(self._label.text, self._label.font_size, self.bold)
            if self._icon_label is not None:
                if self._icon_label.size_hint_x is None:
                    width += self._icon_label.width + (self.spacing if text_shown else 0)
                else:  # an icon-only button: the glyph's own width
                    width += text_width(self._icon_label.text, self._icon_label.font_size, font_name="Icons")
            self._fit_measure = (key, width)
        return self._fit_measure[1]

    def _fit_padding(self, *_args) -> None:
        """BTN_PAD sides, narrower (to BTN_PAD_NARROW) on a button too narrow for its text on one line."""
        side = (self.width - self._one_line_width()) / 2 - dp(1)  # 2 dp spare: a text that just fits wraps on some screens
        self.padding = [max(S.BTN_PAD_NARROW, min(S.BTN_PAD, side)), 0]

    def _ring_rgb(self):
        """Press-ring colour: derived from the SURROUNDING surface (C.TEXT tracks the theme —
        light on dark, dark on light), NOT the button fill, so the ring stays visible on the
        card/app bg it's drawn onto. Same rule as the graph expand glyph."""
        return list(C.TEXT)[:3]

    def set_icon(self, glyph: str) -> None:
        """Swap the icon glyph (a chevron's open/folded state); a button built without an icon font shows none."""
        if self._icon_label is not None:
            self._icon_label.text = glyph  # before `icon`, whose change re-fits the sides to the glyph shown
        self.icon = glyph

    def flash_confirm(self, text="Saved", icon=None, confirm_color=None, duration=1.1):
        """Briefly morph the label/icon (and optionally the fill) to a success cue, then
        revert. Main-thread only. Reentrant: a repeat tap restarts the timer but keeps the
        true original."""
        if self._confirming:
            Clock.unschedule(self._confirm_ev)
        else:
            orig_icon = self._icon_label.text if self._icon_label else None
            self._confirm_orig = (self.text, orig_icon, self.assigned_color("bg_color"), self._label.markup)
            self._confirming = True
        if icon is not None and self._icon_label is not None:
            self._icon_label.text = icon
        # Only touch the text label when it's actually in the tree (an icon-only button's
        # _label is never added — writing to it would be invisible). Render the glyph inline
        # via Icons-font markup for a text-only button, but only when the font is available
        # (else a bare [font=Icons] tag is tofu); otherwise keep the button's own markup mode.
        if self._label.parent is not None:
            use_inline = (icon is not None and self._icon_label is None and ICONS_AVAILABLE)
            if use_inline:
                self._label.markup = True
                self.text = f"[font=Icons]{icon}[/font] {text}"
            else:
                self._label.markup = self._confirm_orig[3]
                self.text = text
        if confirm_color is not None:
            self.bg_color = list(confirm_color)
        self._confirm_ev = Clock.schedule_once(self._end_confirm, duration)

    def _end_confirm(self, *_args):
        if not self._confirming:
            return
        text, icon, bg, markup = self._confirm_orig
        self._label.markup = markup
        if self._label.parent is not None:
            self.text = text
        if icon is not None and self._icon_label is not None:
            self._icon_label.text = icon
        self.bg_color = bg
        self._confirming = False
        self._confirm_ev = None

    def _repaint(self, *_args) -> None:
        """A fill change (AUTO's glyph colour follows it) or a theme switch (the disabled and outline fills and the press
        ring come from the palette): the glyph colour again, then the drawing."""
        self._apply_role_text()
        self._redraw()

    def __setattr__(self, name, value):
        if name == "text_color":
            self._auto_text = value is None
            if value is None:
                value = readable_fg(self.bg_color)
        super().__setattr__(name, value)

    def _apply_role_text(self):
        """AUTO: resolve the glyph colour against the current bg (-> _update_colors via binding)."""
        if self._auto_text:
            super().__setattr__("text_color", readable_fg(self.bg_color))  # past our __setattr__: stays AUTO

    def _update_label(self, *args):
        self._label.text = self.text
        self._label.bold = self.bold

    def _get_bg(self):
        if self.disabled:
            return C.BG_CARD
        if self.state == "down":
            if self.bg_pressed != [0, 0, 0, 0]:
                return self.bg_pressed
            # Auto-dim: darken by 30%
            return [c * 0.7 for c in self.bg_color[:3]] + [self.bg_color[3]]
        return self.bg_color

    def _redraw(self, *args):
        self.canvas.before.clear()
        bg = self._get_bg()
        with self.canvas.before:
            if self.outline:
                # Pressed, the fill stays the card (the text is often the border's colour) and the border thickens.
                down = self.state == "down"
                Color(*C.BG_CARD)
                RoundedRectangle(pos=self.pos, size=self.size, radius=[S.RADIUS])
                Color(*(self.bg_color if down else bg)[:3], 1.0 if down else 0.8)
                Line(
                    rounded_rectangle=[
                        self.x, self.y, self.width, self.height, S.RADIUS,
                    ],
                    width=2.0 if down else 1.2,
                )
            else:
                Color(*bg)
                RoundedRectangle(pos=self.pos, size=self.size, radius=[S.RADIUS])
            # Press ring (issue #33): edge-visible cue that lingers on release. Colour
            # contrasts with the surrounding surface, not the fill (see _ring_rgb).
            if self._ring_alpha > 0 and not self.disabled:
                Color(*self._ring_rgb(), self._ring_alpha)
                Line(
                    rounded_rectangle=[self.x, self.y, self.width, self.height, S.RADIUS],
                    width=dp(2),
                )
        self._paint_glyphs()

    def _paint_glyphs(self, *_args) -> None:
        """The one writer of the text and icon colour: the glyph colour, or on a disabled button 60 % of the readable one
        on its grey fill, legible (~4:1) without reading as live; pressed, only the fill dims. A disabled Label draws
        disabled_color, so both are set."""
        fg = dimmed_fg(self._get_bg()) if self.disabled else list(self.text_color)
        for label in (self._label, self._icon_label):
            if label is not None:
                label.color = label.disabled_color = fg

    def on_state(self, *args):
        if self.state == "down":
            Animation.cancel_all(self, "_ring_alpha")
            self._ring_alpha = self._RING_MAX  # snap on: visible before the fade
        else:
            Animation(_ring_alpha=0.0, duration=self._RING_FADE, t="out_quad").start(self)
        self._redraw()

    def _on_disabled(self, *args):
        # Disabling a pressed button gives no release event, so clear the ring here — else
        # re-enabling later repaints a stuck full-opacity ring.
        if self.disabled:
            Animation.cancel_all(self, "_ring_alpha")
            self._ring_alpha = 0.0
        self._redraw()


def cancel_button(text: str = "Cancel", **kwargs) -> StyledButton:
    """A modal's dismiss button (Cancel / Close): one neutral look in every popup, never mistaken for its action."""
    kwargs.setdefault("bg_color", C.BG_CARD)
    kwargs.setdefault("text_color", C.TEXT_SECONDARY)
    return StyledButton(text=text, **kwargs)
