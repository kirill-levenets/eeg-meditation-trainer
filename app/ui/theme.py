"""Visual theme for EEG Meditation Trainer.

Centralized palette, typography, spacing, and custom styled widgets.
Design direction: calm, focused, minimal — dark theme with soft accents.
"""

from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import (
    BooleanProperty,
    ListProperty,
    NumericProperty,
    StringProperty,
)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label


# ── Color palette ────────────────────────────────────────────────────

class C:
    """Color constants (RGBA tuples). Semantic names."""

    # Backgrounds
    BG_DARK = (0.06, 0.06, 0.10, 1.0)       # deepest background
    BG = (0.09, 0.09, 0.14, 1.0)             # main screen background
    BG_CARD = (0.12, 0.12, 0.18, 1.0)        # card / panel surface
    BG_INPUT = (0.10, 0.10, 0.16, 1.0)       # text input background
    BG_OVERLAY = (0.0, 0.0, 0.0, 0.75)       # modal overlay

    # Accents
    PRIMARY = (0.30, 0.65, 0.90, 1.0)        # calm blue — main accent
    PRIMARY_DIM = (0.20, 0.45, 0.70, 1.0)    # pressed / muted blue
    ACCENT = (0.45, 0.80, 0.65, 1.0)         # sage green — success / go
    ACCENT_DIM = (0.30, 0.60, 0.45, 1.0)     # pressed green
    WARM = (0.85, 0.65, 0.30, 1.0)           # warm amber — pause / caution
    WARM_DIM = (0.65, 0.50, 0.20, 1.0)       # pressed amber
    DANGER = (0.75, 0.30, 0.30, 1.0)         # muted red — stop / delete
    DANGER_DIM = (0.55, 0.20, 0.20, 1.0)     # pressed red
    PURPLE = (0.55, 0.35, 0.70, 1.0)         # soft purple — marker / special
    PURPLE_DIM = (0.40, 0.25, 0.55, 1.0)     # pressed purple

    # Text
    TEXT = (0.88, 0.88, 0.92, 1.0)           # primary text
    TEXT_SECONDARY = (0.55, 0.55, 0.62, 1.0) # secondary / hint
    TEXT_MUTED = (0.40, 0.40, 0.46, 1.0)     # disabled / placeholder
    TEXT_ON_ACCENT = (0.06, 0.06, 0.10, 1.0) # dark text on bright bg

    # Borders / dividers
    BORDER = (0.22, 0.22, 0.28, 1.0)         # subtle separator
    BORDER_FOCUS = (0.30, 0.65, 0.90, 0.6)   # focused input border

    # Metric colors (shared across graphs)
    SHAMATHA = (0.30, 0.85, 0.55, 1.0)       # green
    DISTRACTION = (0.90, 0.35, 0.35, 1.0)    # red
    SINKING = (0.80, 0.55, 0.15, 1.0)        # orange
    SUBTLE = (0.85, 0.85, 0.30, 1.0)         # yellow
    ATTENTION = (0.55, 0.35, 0.85, 1.0)      # purple
    MEDITATION = (0.35, 0.80, 0.85, 1.0)     # cyan
    CUSTOM = (0.90, 0.45, 0.75, 1.0)         # magenta
    MED_SCORE = (0.30, 0.60, 0.95, 1.0)      # blue

    # Graph
    GRAPH_BG = (0.07, 0.07, 0.11, 1.0)
    GRAPH_GRID = (0.18, 0.18, 0.24, 1.0)
    GRAPH_BORDER = (0.25, 0.25, 0.32, 1.0)
    THRESHOLD_LINE = (0.90, 0.30, 0.90, 0.7)

    # Status
    CONNECTED = (0.35, 0.80, 0.50, 1.0)
    CONNECTING = (0.85, 0.75, 0.30, 1.0)
    DISCONNECTED = (0.70, 0.30, 0.30, 1.0)
    DEVICE_IDLE = (0.40, 0.65, 0.90, 1.0)

    # State colors (live session)
    STATE_FOCUS = (0.30, 0.85, 0.50, 1.0)
    STATE_SUBTLE = (0.85, 0.85, 0.30, 1.0)
    STATE_DISTRACTED = (0.90, 0.35, 0.35, 1.0)
    STATE_SINKING = (0.80, 0.55, 0.15, 1.0)
    STATE_NEUTRAL = (0.55, 0.55, 0.62, 1.0)


# ── Typography ───────────────────────────────────────────────────────

class F:
    """Font sizes (dp)."""
    DISPLAY = dp(48)    # timer countdown
    H1 = dp(22)         # screen title
    H2 = dp(16)         # section header
    H3 = dp(14)         # subsection / important label
    BODY = dp(13)       # standard text
    SMALL = dp(11)      # secondary info
    TINY = dp(9)        # axis labels, metadata


# ── Spacing ──────────────────────────────────────────────────────────

class S:
    """Spacing and sizing constants (dp)."""
    PAGE_PAD = dp(12)     # screen edge padding
    CARD_PAD = dp(10)     # inside card padding
    GAP = dp(8)           # default spacing between elements
    GAP_SM = dp(4)        # compact spacing
    GAP_LG = dp(16)       # section spacing

    ROW_H = dp(42)        # standard interactive row height
    ROW_SM = dp(32)       # compact row
    BTN_H = dp(44)        # button height
    NAV_H = dp(46)        # top nav bar height
    RADIUS = 8            # corner radius (raw px, used in RoundedRectangle)


# ── Styled widgets ───────────────────────────────────────────────────

class StyledButton(ButtonBehavior, BoxLayout):
    """Rounded button with press color shift. Replaces default Kivy Button.

    Usage:
        btn = StyledButton(text="Start", bg_color=C.ACCENT, text_color=C.TEXT)
        btn.bind(on_release=callback)
    """
    text = StringProperty("")
    bg_color = ListProperty(list(C.PRIMARY))
    bg_pressed = ListProperty([0, 0, 0, 0])  # auto-derived if left empty
    text_color = ListProperty(list(C.TEXT))
    font_size = NumericProperty(F.BODY)
    bold = BooleanProperty(True)
    icon = StringProperty("")  # optional left-side icon text

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", S.BTN_H)
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.padding = [dp(12), 0]

        self._label = Label(
            text=self.text,
            color=self.text_color,
            font_size=self.font_size,
            bold=self.bold,
            halign="center",
            valign="middle",
        )
        self._label.bind(size=self._label.setter("text_size"))

        self._icon_label = None
        if self.icon:
            self._icon_label = Label(
                text=self.icon,
                font_size=self.font_size + dp(2),
                color=self.text_color,
                size_hint_x=None,
                width=dp(24),
            )
            self.add_widget(self._icon_label)

        self.add_widget(self._label)

        self.bind(
            text=self._update_label,
            text_color=self._update_colors,
            bg_color=self._redraw,
            size=self._redraw,
            pos=self._redraw,
            disabled=self._redraw,
        )
        self._redraw()

    def _update_label(self, *args):
        self._label.text = self.text

    def _update_colors(self, *args):
        self._label.color = self.text_color
        if self._icon_label:
            self._icon_label.color = self.text_color

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
        with self.canvas.before:
            Color(*self._get_bg())
            RoundedRectangle(pos=self.pos, size=self.size, radius=[S.RADIUS])
        if self.disabled:
            self._label.color = list(C.TEXT_MUTED)
        else:
            self._label.color = list(self.text_color)

    def on_state(self, *args):
        self._redraw()


class Card(BoxLayout):
    """Rounded card container with subtle background."""

    bg_color = ListProperty(list(C.BG_CARD))

    def __init__(self, **kwargs):
        kwargs.setdefault("padding", S.CARD_PAD)
        kwargs.setdefault("spacing", S.GAP_SM)
        super().__init__(**kwargs)
        self.bind(size=self._redraw, pos=self._redraw, bg_color=self._redraw)
        self._redraw()

    def _redraw(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*self.bg_color)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[S.RADIUS])


class Divider(BoxLayout):
    """Thin horizontal line separator."""

    color = ListProperty(list(C.BORDER))

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(1))
        super().__init__(**kwargs)
        self.bind(size=self._redraw, pos=self._redraw)
        self._redraw()

    def _redraw(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*self.color)
            Rectangle(pos=self.pos, size=self.size)


class SectionLabel(Label):
    """Section header label with consistent styling."""

    def __init__(self, **kwargs):
        kwargs.setdefault("font_size", F.H2)
        kwargs.setdefault("bold", True)
        kwargs.setdefault("color", C.TEXT_SECONDARY)
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", S.ROW_SM)
        kwargs.setdefault("halign", "left")
        kwargs.setdefault("valign", "middle")
        super().__init__(**kwargs)
        self.bind(size=self.setter("text_size"))


class CollapsibleSection(BoxLayout):
    """Tappable section header that expands/collapses its content.

    Usage:
        section = CollapsibleSection(title="Audio", collapsed=True)
        section.add_content(widget1)
        section.add_content(widget2)
        parent.add_widget(section)
    """

    collapsed = BooleanProperty(False)

    def __init__(self, title="", collapsed=False, **kwargs):
        self._init_done = False
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_y", None)

        # Create content before super().__init__ to avoid issues
        self._content = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=S.GAP,
            padding=[dp(4), S.GAP_SM],
        )
        self._content.bind(minimum_height=self._content.setter("height"))

        super().__init__(**kwargs)
        self._title = title

        # Header row (tappable via on_touch_down)
        self._header = BoxLayout(
            size_hint_y=None, height=S.ROW_SM + dp(4),
            padding=[0, dp(2)],
        )
        self._arrow = Label(
            text="v" if not collapsed else ">",
            font_size=F.BODY,
            color=C.TEXT_MUTED,
            size_hint_x=None,
            width=dp(20),
        )
        self._label = Label(
            text=title,
            font_size=F.H2,
            bold=True,
            color=C.TEXT_SECONDARY,
            halign="left",
            valign="middle",
        )
        self._label.bind(size=self._label.setter("text_size"))
        self._header.add_widget(self._arrow)
        self._header.add_widget(self._label)
        super().add_widget(self._header)

        super().add_widget(Divider())
        super().add_widget(self._content)

        if collapsed:
            self._content.height = 0
            self._content.opacity = 0

        self.bind(minimum_height=self.setter("height"))
        self._header.bind(on_touch_down=self._on_header_tap)
        self._init_done = True

    def add_content(self, widget):
        """Add a widget to the collapsible content area."""
        self._content.add_widget(widget)

    def _on_header_tap(self, widget, touch):
        if not self._header.collide_point(*touch.pos):
            return False
        self.collapsed = not self.collapsed
        return True

    def on_collapsed(self, *args):
        if self.collapsed:
            self._content.saved_height = self._content.height
            self._content.height = 0
            self._content.opacity = 0
            self._arrow.text = ">"
        else:
            self._content.opacity = 1
            # Force recalc
            self._content.height = 0
            self._content.bind(minimum_height=self._content.setter("height"))
            self._arrow.text = "v"

    def add_widget(self, widget, *args, **kwargs):
        """Redirect add_widget to content area after init."""
        if hasattr(self, "_init_done"):
            self._content.add_widget(widget, *args, **kwargs)
        else:
            super().add_widget(widget, *args, **kwargs)


class PresetRow(BoxLayout):
    """Row of quick-pick value buttons for a slider.

    Usage:
        presets = PresetRow(values=[30, 50, 70, 85, 100], callback=slider_set)
    """

    def __init__(self, values, callback=None, fmt="{}", **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(28))
        kwargs.setdefault("spacing", S.GAP_SM)
        super().__init__(**kwargs)
        for v in values:
            btn = StyledButton(
                text=fmt.format(v),
                bg_color=C.BG_CARD,
                text_color=C.TEXT_MUTED,
                font_size=F.TINY,
                height=dp(26),
                bold=False,
            )
            btn._preset_value = v
            if callback:
                btn.bind(on_release=lambda b, cb=callback, val=v: cb(val))
            self.add_widget(btn)


class IconLabel(Label):
    """Label that renders a text icon character at a given size."""

    def __init__(self, icon="", **kwargs):
        kwargs.setdefault("font_size", F.H2)
        kwargs.setdefault("color", C.TEXT_SECONDARY)
        kwargs.setdefault("size_hint_x", None)
        kwargs.setdefault("width", dp(28))
        kwargs.setdefault("halign", "center")
        kwargs.setdefault("valign", "middle")
        super().__init__(text=icon, **kwargs)
        self.bind(size=self.setter("text_size"))


class BottomNav(BoxLayout):
    """3-tab bottom navigation bar.

    Usage:
        nav = BottomNav(tabs=[
            ("Session", "session"),
            ("History", "history"),
            ("Settings", "settings"),
        ], callback=on_tab_switch)
    """

    active_tab = StringProperty("")

    def __init__(self, tabs, callback=None, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", S.NAV_H)
        kwargs.setdefault("spacing", 0)
        super().__init__(orientation="horizontal", **kwargs)
        self._callback = callback
        self._tab_widgets = {}

        with self.canvas.before:
            Color(*C.BG_DARK)
            self._bg = Rectangle(size=self.size, pos=self.pos)
            # Top border line
            Color(*C.BORDER)
            self._border = Rectangle(
                size=(self.size[0], dp(1)),
                pos=(self.pos[0], self.pos[1] + self.size[1] - dp(1)),
            )
        self.bind(size=self._update_bg, pos=self._update_bg)

        for label, key in tabs:
            tab = _NavTab(label=label, key=key)
            tab.bind(on_release=self._on_tab_press)
            self._tab_widgets[key] = tab
            self.add_widget(tab)

        if tabs:
            self.active_tab = tabs[0][1]

    def _update_bg(self, *args):
        self._bg.size = self.size
        self._bg.pos = self.pos
        self._border.size = (self.size[0], dp(1))
        self._border.pos = (self.pos[0], self.pos[1] + self.size[1] - dp(1))

    def _on_tab_press(self, tab):
        self.active_tab = tab.key
        if self._callback:
            self._callback(tab.key)

    def on_active_tab(self, *args):
        for key, tab in self._tab_widgets.items():
            tab.active = (key == self.active_tab)


class _NavTab(ButtonBehavior, BoxLayout):
    """Single tab in the bottom nav."""

    active = BooleanProperty(False)

    def __init__(self, label="", key="", **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.key = key
        self.padding = [0, dp(4)]

        self._label = Label(
            text=label,
            font_size=F.SMALL,
            bold=True,
            halign="center",
            valign="middle",
            color=C.TEXT_MUTED,
        )
        self._label.bind(size=self._label.setter("text_size"))
        self._indicator = BoxLayout(size_hint_y=None, height=dp(3))

        self.add_widget(self._label)
        self.add_widget(self._indicator)
        self.bind(active=self._redraw)
        self._redraw()

    def _redraw(self, *args):
        self._indicator.canvas.before.clear()
        if self.active:
            self._label.color = C.PRIMARY
            with self._indicator.canvas.before:
                Color(*C.PRIMARY)
                RoundedRectangle(
                    pos=self._indicator.pos,
                    size=self._indicator.size,
                    radius=[dp(2)],
                )
            self._indicator.bind(pos=self._redraw_indicator, size=self._redraw_indicator)
        else:
            self._label.color = C.TEXT_MUTED

    def _redraw_indicator(self, *args):
        if self.active:
            self._indicator.canvas.before.clear()
            with self._indicator.canvas.before:
                Color(*C.PRIMARY)
                RoundedRectangle(
                    pos=self._indicator.pos,
                    size=self._indicator.size,
                    radius=[dp(2)],
                )