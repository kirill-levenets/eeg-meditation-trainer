"""Visual theme for EEG Meditation Trainer.

Centralized palette, typography, spacing, and custom styled widgets.
Design direction: calm, focused, minimal — dark theme with soft accents.
"""

import os

from kivy.core.text import LabelBase
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
from kivy.uix.scrollview import ScrollView


# ── Icon font ────────────────────────────────────────────────────────

_ICON_FONT = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "assets", "fonts", "materialdesignicons-webfont.ttf",
)
if os.path.exists(_ICON_FONT):
    LabelBase.register("Icons", _ICON_FONT)


class Icons:
    """Material Design Icon codepoints (used with font_name='Icons')."""
    PLAY = "\U000F040A"
    PAUSE = "\U000F03E4"
    STOP = "\U000F04DB"
    PENCIL = "\U000F03EB"
    DELETE = "\U000F01B4"
    CHECK = "\U000F012C"
    CLOSE = "\U000F0156"
    CHEVRON_LEFT = "\U000F0141"
    CHEVRON_DOWN = "\U000F0140"
    CHEVRON_RIGHT = "\U000F0142"
    COG = "\U000F0493"
    HISTORY = "\U000F02DA"
    TIMER = "\U000F013B"
    ACCOUNT = "\U000F0004"
    BLUETOOTH = "\U000F00AF"
    VOLUME = "\U000F057E"
    CHART = "\U000F0128"
    TUNE = "\U000F062E"
    PALETTE = "\U000F0400"
    MARKER = "\U000F034E"
    BRAIN = "\U000F09D8"
    PLUS = "\U000F0415"
    REFRESH = "\U000F0450"


# ── Color palette ────────────────────────────────────────────────────

# ── Accordion styling via kv ──────────────────────────────────────────

def _create_solid_png(rgba, path):
    """Write a 1x1 solid-color PNG file for use as accordion background."""
    import struct, zlib
    r = int(rgba[0] * 255)
    g = int(rgba[1] * 255)
    b = int(rgba[2] * 255)
    a = int(rgba[3] * 255) if len(rgba) > 3 else 255

    def _chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)

    raw = zlib.compress(bytes([0, r, g, b, a]))
    png = b'\x89PNG\r\n\x1a\n'
    png += _chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))
    png += _chunk(b'IDAT', raw)
    png += _chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(png)


# Generate solid-color PNGs for accordion backgrounds
import tempfile as _tempfile
_ACCORDION_DIR = _tempfile.mkdtemp(prefix="eeg_theme_")


def get_accordion_bg(color_key="BG_CARD"):
    """Return path to a solid-color PNG for accordion backgrounds."""
    color = getattr(C, color_key)
    name = f"acc_{color_key}.png"
    path = os.path.join(_ACCORDION_DIR, name)
    if not os.path.exists(path):
        _create_solid_png(color, path)
    return path


def style_accordion(accordion):
    """Apply theme colors to all AccordionItems."""
    bg_normal = get_accordion_bg("BG_CARD")
    bg_selected = get_accordion_bg("PRIMARY_DIM")
    for item in accordion.children:
        if hasattr(item, 'background_normal'):
            item.background_normal = bg_normal
            item.background_selected = bg_selected


# ── Theme palettes ───────────────────────────────────────────────────

# Metric colors are shared across all themes
_METRICS = {
    "SHAMATHA": (0.30, 0.85, 0.55, 1.0),
    "DISTRACTION": (0.90, 0.35, 0.35, 1.0),
    "SINKING": (0.80, 0.55, 0.15, 1.0),
    "SUBTLE": (0.85, 0.85, 0.30, 1.0),
    "ATTENTION": (0.55, 0.35, 0.85, 1.0),
    "MEDITATION": (0.35, 0.80, 0.85, 1.0),
    "CUSTOM": (0.90, 0.45, 0.75, 1.0),
    "MED_SCORE": (0.30, 0.60, 0.95, 1.0),
    "THRESHOLD_LINE": (0.90, 0.30, 0.90, 0.7),
    "STATE_FOCUS": (0.30, 0.85, 0.50, 1.0),
    "STATE_SUBTLE": (0.85, 0.85, 0.30, 1.0),
    "STATE_DISTRACTED": (0.90, 0.35, 0.35, 1.0),
    "STATE_SINKING": (0.80, 0.55, 0.15, 1.0),
    "CONNECTED": (0.35, 0.80, 0.50, 1.0),
    "CONNECTING": (0.85, 0.75, 0.30, 1.0),
    "DISCONNECTED": (0.70, 0.30, 0.30, 1.0),
}

_DARK_BLUE = {
    **_METRICS,
    "BG_DARK": (0.06, 0.06, 0.10, 1.0),
    "BG": (0.09, 0.09, 0.14, 1.0),
    "BG_CARD": (0.12, 0.12, 0.18, 1.0),
    "BG_INPUT": (0.10, 0.10, 0.16, 1.0),
    "BG_OVERLAY": (0.0, 0.0, 0.0, 0.75),
    "PRIMARY": (0.30, 0.65, 0.90, 1.0),
    "PRIMARY_DIM": (0.20, 0.45, 0.70, 1.0),
    "ACCENT": (0.45, 0.80, 0.65, 1.0),
    "ACCENT_DIM": (0.30, 0.60, 0.45, 1.0),
    "WARM": (0.85, 0.65, 0.30, 1.0),
    "WARM_DIM": (0.65, 0.50, 0.20, 1.0),
    "DANGER": (0.75, 0.30, 0.30, 1.0),
    "DANGER_DIM": (0.55, 0.20, 0.20, 1.0),
    "PURPLE": (0.55, 0.35, 0.70, 1.0),
    "PURPLE_DIM": (0.40, 0.25, 0.55, 1.0),
    "TEXT": (0.88, 0.88, 0.92, 1.0),
    "TEXT_SECONDARY": (0.55, 0.55, 0.62, 1.0),
    "TEXT_MUTED": (0.40, 0.40, 0.46, 1.0),
    "TEXT_ON_ACCENT": (0.06, 0.06, 0.10, 1.0),
    "BORDER": (0.22, 0.22, 0.28, 1.0),
    "BORDER_FOCUS": (0.30, 0.65, 0.90, 0.6),
    "GRAPH_BG": (0.07, 0.07, 0.11, 1.0),
    "GRAPH_GRID": (0.18, 0.18, 0.24, 1.0),
    "GRAPH_BORDER": (0.25, 0.25, 0.32, 1.0),
    "DEVICE_IDLE": (0.40, 0.65, 0.90, 1.0),
    "STATE_NEUTRAL": (0.55, 0.55, 0.62, 1.0),
}

_DARK_GREEN = {
    **_DARK_BLUE,
    "BG_DARK": (0.05, 0.08, 0.06, 1.0),
    "BG": (0.08, 0.12, 0.09, 1.0),
    "BG_CARD": (0.10, 0.15, 0.11, 1.0),
    "BG_INPUT": (0.09, 0.13, 0.10, 1.0),
    "PRIMARY": (0.40, 0.75, 0.55, 1.0),
    "PRIMARY_DIM": (0.28, 0.55, 0.40, 1.0),
    "BORDER": (0.18, 0.25, 0.20, 1.0),
    "BORDER_FOCUS": (0.40, 0.75, 0.55, 0.6),
    "GRAPH_BG": (0.06, 0.09, 0.07, 1.0),
    "GRAPH_GRID": (0.14, 0.20, 0.16, 1.0),
    "GRAPH_BORDER": (0.20, 0.28, 0.22, 1.0),
    "DEVICE_IDLE": (0.40, 0.70, 0.55, 1.0),
}

_LIGHT_CREAM = {
    **_METRICS,
    "BG_DARK": (0.90, 0.87, 0.82, 1.0),
    "BG": (0.95, 0.93, 0.88, 1.0),
    "BG_CARD": (1.00, 0.98, 0.94, 1.0),
    "BG_INPUT": (0.98, 0.96, 0.92, 1.0),
    "BG_OVERLAY": (0.0, 0.0, 0.0, 0.50),
    "PRIMARY": (0.20, 0.50, 0.75, 1.0),
    "PRIMARY_DIM": (0.15, 0.40, 0.60, 1.0),
    "ACCENT": (0.30, 0.65, 0.45, 1.0),
    "ACCENT_DIM": (0.22, 0.50, 0.35, 1.0),
    "WARM": (0.80, 0.55, 0.20, 1.0),
    "WARM_DIM": (0.60, 0.42, 0.15, 1.0),
    "DANGER": (0.75, 0.25, 0.25, 1.0),
    "DANGER_DIM": (0.60, 0.18, 0.18, 1.0),
    "PURPLE": (0.50, 0.30, 0.65, 1.0),
    "PURPLE_DIM": (0.38, 0.22, 0.50, 1.0),
    "TEXT": (0.15, 0.15, 0.18, 1.0),
    "TEXT_SECONDARY": (0.40, 0.40, 0.45, 1.0),
    "TEXT_MUTED": (0.60, 0.58, 0.55, 1.0),
    "TEXT_ON_ACCENT": (0.98, 0.98, 0.96, 1.0),
    "BORDER": (0.82, 0.80, 0.76, 1.0),
    "BORDER_FOCUS": (0.20, 0.50, 0.75, 0.6),
    "GRAPH_BG": (0.97, 0.95, 0.91, 1.0),
    "GRAPH_GRID": (0.85, 0.83, 0.80, 1.0),
    "GRAPH_BORDER": (0.78, 0.76, 0.72, 1.0),
    "DEVICE_IDLE": (0.30, 0.55, 0.80, 1.0),
    "STATE_NEUTRAL": (0.45, 0.45, 0.50, 1.0),
}

_LIGHT_GREEN = {
    **_LIGHT_CREAM,
    "BG_DARK": (0.85, 0.90, 0.85, 1.0),
    "BG": (0.91, 0.95, 0.91, 1.0),
    "BG_CARD": (0.96, 0.99, 0.96, 1.0),
    "BG_INPUT": (0.93, 0.97, 0.93, 1.0),
    "PRIMARY": (0.25, 0.60, 0.40, 1.0),
    "PRIMARY_DIM": (0.18, 0.45, 0.30, 1.0),
    "BORDER": (0.78, 0.84, 0.78, 1.0),
    "BORDER_FOCUS": (0.25, 0.60, 0.40, 0.6),
    "GRAPH_BG": (0.93, 0.97, 0.93, 1.0),
    "GRAPH_GRID": (0.82, 0.87, 0.82, 1.0),
    "GRAPH_BORDER": (0.74, 0.80, 0.74, 1.0),
    "DEVICE_IDLE": (0.30, 0.60, 0.45, 1.0),
}

THEMES = {
    "Dark Blue": _DARK_BLUE,
    "Dark Green": _DARK_GREEN,
    "Light Cream": _LIGHT_CREAM,
    "Light Green": _LIGHT_GREEN,
}


class _ColorAccessor:
    """Provides attribute access to the active theme palette.

    All existing code uses C.PRIMARY, C.BG etc. — this class makes
    that work while allowing the underlying palette to be swapped at runtime.
    Supports listeners that get called on theme change for live refresh.
    """

    def __init__(self):
        self._palette = dict(_DARK_BLUE)
        self._name = "Dark Blue"
        self._listeners = []

    def __getattr__(self, name):
        if name.startswith("_"):
            return super().__getattribute__(name)
        try:
            return self._palette[name]
        except KeyError:
            raise AttributeError(f"No color '{name}' in theme")

    def set_theme(self, name: str) -> None:
        """Switch the active palette and notify listeners."""
        if name in THEMES:
            self._palette = dict(THEMES[name])
            self._name = name
            for cb in self._listeners:
                try:
                    cb()
                except Exception:
                    pass

    def add_listener(self, callback) -> None:
        """Register a callback to be called when theme changes."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    @property
    def theme_name(self) -> str:
        return self._name


C = _ColorAccessor()


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
    outline = BooleanProperty(False)  # draw border instead of fill

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
            # Icon-only: center the icon, no text label
            if not self.text:
                self._icon_label = Label(
                    text=self.icon,
                    font_name="Icons",
                    font_size=self.font_size + dp(6),
                    color=self.text_color,
                    halign="center",
                    valign="middle",
                )
                self._icon_label.bind(size=self._icon_label.setter("text_size"))
                self.add_widget(self._icon_label)
            else:
                # Icon + text
                self._icon_label = Label(
                    text=self.icon,
                    font_name="Icons",
                    font_size=self.font_size + dp(4),
                    color=self.text_color,
                    size_hint_x=None,
                    width=dp(26),
                )
                self.add_widget(self._icon_label)
                self.add_widget(self._label)
        else:
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
        C.add_listener(self._redraw)

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
        bg = self._get_bg()
        with self.canvas.before:
            if self.outline and self.state != "down":
                Color(*C.BG_CARD)
                RoundedRectangle(pos=self.pos, size=self.size, radius=[S.RADIUS])
                Color(*bg[:3], 0.8)
                Line(
                    rounded_rectangle=[
                        self.x, self.y, self.width, self.height, S.RADIUS,
                    ],
                    width=1.2,
                )
            else:
                Color(*bg)
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


class ThemedAccordion(BoxLayout):
    """Custom accordion container — only one section open at a time.

    Usage:
        acc = ThemedAccordion()
        sec = acc.add_section("Device", collapsed=False)
        sec.add_widget(my_widget)
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_y", None)
        super().__init__(**kwargs)
        self._sections = []
        self.bind(minimum_height=self.setter("height"))

    def add_section(self, title, collapsed=True, icon=""):
        section = _AccordionSection(title=title, collapsed=collapsed, icon=icon,
                                    accordion=self)
        super().add_widget(section)
        self._sections.append(section)
        return section

    def _on_section_open(self, opened_section):
        """Close all other sections when one opens."""
        for sec in self._sections:
            if sec is not opened_section and not sec._collapsed:
                sec._set_collapsed(True, notify=False)


class _AccordionSection(BoxLayout):
    """Single section in ThemedAccordion — styled header + collapsible content."""

    def __init__(self, title="", collapsed=True, icon="", accordion=None, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_y", None)
        super().__init__(**kwargs)
        self._collapsed = collapsed
        self._accordion = accordion

        # Header button
        icon_text = icon if icon else (Icons.CHEVRON_RIGHT if collapsed else Icons.CHEVRON_DOWN)
        self._header = StyledButton(
            text=title,
            icon=icon_text,
            bg_color=C.BG_CARD,
            text_color=C.TEXT_SECONDARY,
            font_size=F.H3,
            height=dp(38),
            bold=True,
        )
        self._header.bind(on_release=self._toggle)
        self._header_icon_text = icon  # user icon (empty = use chevron)
        super().add_widget(self._header)

        # Content area (inside ScrollView for long sections)
        self._content = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=S.GAP,
            padding=[S.GAP_SM, S.GAP_SM],
        )
        self._content.bind(minimum_height=self._content.setter("height"))
        self._scroll = ScrollView(size_hint_y=None, height=0)
        self._scroll.add_widget(self._content)
        super().add_widget(self._scroll)

        if collapsed:
            self._scroll.height = 0
            self._scroll.opacity = 0

        self.bind(minimum_height=self.setter("height"))
        C.add_listener(self._refresh_theme)

    def add_widget(self, widget, *args, **kwargs):
        if hasattr(self, "_content"):
            self._content.add_widget(widget, *args, **kwargs)
            self._update_height()
        else:
            super().add_widget(widget, *args, **kwargs)

    def _toggle(self, *args):
        if self._collapsed:
            if self._accordion:
                self._accordion._on_section_open(self)
            self._set_collapsed(False)
        else:
            self._set_collapsed(True)

    def _set_collapsed(self, collapsed, notify=True):
        self._collapsed = collapsed
        if collapsed:
            self._scroll.height = 0
            self._scroll.opacity = 0
            if not self._header_icon_text:
                self._header._icon_label.text = Icons.CHEVRON_RIGHT
        else:
            self._scroll.opacity = 1
            self._update_height()
            if not self._header_icon_text:
                self._header._icon_label.text = Icons.CHEVRON_DOWN

    def _update_height(self):
        if self._collapsed:
            self._scroll.height = 0
        else:
            # Cap content scroll height to avoid giant sections
            content_h = self._content.minimum_height
            self._scroll.height = min(content_h, dp(500))

    def _refresh_theme(self):
        self._header.bg_color = C.BG_CARD
        self._header.text_color = C.TEXT_SECONDARY


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

        _TAB_ICONS = {
            "session": Icons.BRAIN,
            "history": Icons.HISTORY,
            "settings": Icons.COG,
        }
        for label, key in tabs:
            tab = _NavTab(label=label, key=key, icon=_TAB_ICONS.get(key, ""))
            tab.bind(on_release=self._on_tab_press)
            self._tab_widgets[key] = tab
            self.add_widget(tab)

        if tabs:
            self.active_tab = tabs[0][1]
        C.add_listener(self._refresh_theme)

    def _refresh_theme(self):
        self._update_bg()
        self.on_active_tab()

    def _update_bg(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*C.BG_DARK)
            self._bg = Rectangle(size=self.size, pos=self.pos)
            Color(*C.BORDER)
            self._border = Rectangle(
                size=(self.size[0], dp(1)),
                pos=(self.pos[0], self.pos[1] + self.size[1] - dp(1)),
            )

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

    def __init__(self, label="", key="", icon="", **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.key = key
        self.padding = [0, dp(2)]
        self.spacing = 0

        self._icon = None
        if icon:
            self._icon = Label(
                text=icon,
                font_name="Icons",
                font_size=dp(20),
                color=C.TEXT_MUTED,
                size_hint_y=None,
                height=dp(22),
            )
            self.add_widget(self._icon)

        self._label = Label(
            text=label,
            font_size=F.TINY,
            bold=True,
            halign="center",
            valign="middle",
            color=C.TEXT_MUTED,
            size_hint_y=None,
            height=dp(14),
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
            if self._icon:
                self._icon.color = C.PRIMARY
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
            if self._icon:
                self._icon.color = C.TEXT_MUTED

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