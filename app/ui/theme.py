"""Visual theme for EEG Meditation Trainer.

Centralized palette, typography, spacing, and custom styled widgets.
Design direction: calm, focused, minimal — dark theme with soft accents.
"""

import os
import struct
import zlib

from kivy.core.text import LabelBase
from kivy.core.window import Window
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
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

# ── Icon font ────────────────────────────────────────────────────────

_FONT_NAME = "materialdesignicons-webfont.ttf"
_ICON_FONT_CANDIDATES = [
    # Standard: app/assets/fonts/ relative to app/ui/theme.py
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts", _FONT_NAME),
    # Android: Buildozer puts files relative to the app root
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                 "app", "assets", "fonts", _FONT_NAME),
    # Fallback: same directory as this file
    os.path.join(os.path.dirname(__file__), _FONT_NAME),
]
_ICON_FONT = ""
for _candidate in _ICON_FONT_CANDIDATES:
    if os.path.exists(_candidate):
        _ICON_FONT = _candidate
        break
ICONS_AVAILABLE = False
if _ICON_FONT:
    LabelBase.register("Icons", _ICON_FONT)
    ICONS_AVAILABLE = True


def format_duration(seconds: int) -> str:
    """Human-friendly duration: seconds if <1m, minutes if <1h, hours otherwise."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s:02d}s"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}h {m:02d}m"


def make_scroll_popup(title, rows, footer=None, *, width_hint=0.85, row_h=None,
                      est_rows=None, max_height_hint=0.85, auto_dismiss=True):
    """Popup with a vertically-scrolling list of fixed-height `rows` and an optional
    pinned `footer`. Sizes to content but caps at `max_height_hint` of the window so
    long lists scroll instead of overflowing the screen. `est_rows` overrides the
    row-count used for the height estimate (for a row that is itself a multi-row grid).
    Returns the Popup."""
    row_h = row_h or dp(44)
    inner = BoxLayout(orientation="vertical", spacing=S.GAP_SM, size_hint_y=None)
    inner.bind(minimum_height=inner.setter("height"))
    for w in rows:
        w.size_hint_y = None
        if not w.height:
            w.height = row_h
        inner.add_widget(w)
    scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
    scroll.add_widget(inner)
    body = BoxLayout(orientation="vertical", spacing=S.GAP_SM, padding=S.GAP)
    body.add_widget(scroll)
    if footer is not None:
        footer.size_hint_y = None
        if not footer.height:
            footer.height = row_h
        body.add_widget(footer)
    n = (est_rows if est_rows is not None else len(rows)) + (1 if footer is not None else 0)
    content_h = n * (row_h + S.GAP_SM) + dp(90)  # rows + title bar + padding chrome
    height = min(content_h, Window.height * max_height_hint)
    return Popup(title=title, content=body, size_hint=(width_hint, None),
                 height=height, auto_dismiss=auto_dismiss)


class Icons:
    """Material Design Icon codepoints (used with font_name='Icons')."""
    PLAY = "\U000F040A"
    PAUSE = "\U000F03E4"
    STOP = "\U000F04DB"
    PENCIL = "\U000F03EB"
    DELETE = "\U000F01B4"
    CHECK = "\U000F012C"
    CLOSE = "\U000F0156"
    CLOSE_CIRCLE = "\U000F0159"
    CLOSE_CIRCLE_OUTLINE = "\U000F015A"
    CHEVRON_LEFT = "\U000F0141"
    CHEVRON_DOWN = "\U000F0140"
    CHEVRON_RIGHT = "\U000F0142"
    CHEVRON_UP = "\U000F0143"
    MENU_DOWN = "\U000F035D"
    MENU_UP = "\U000F0360"
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
    SWAP_HORIZONTAL = "\U000F01B6"


# ── Color palette ────────────────────────────────────────────────────

# ── Accordion styling via kv ──────────────────────────────────────────

def _create_solid_png(rgba, path):
    """Write a 1x1 solid-color PNG file for use as accordion background."""
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
    "CUSTOM2": (1.0, 0.50, 0.0, 1.0),
    "CUSTOM3": (0.40, 0.75, 0.95, 1.0),
    "MED_SCORE": (0.30, 0.60, 0.95, 1.0),
    "WARM2": (0.95, 0.50, 0.55, 1.0),
    "WARM3": (0.75, 0.55, 0.90, 1.0),
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

# Kivy's Popup chrome (background + title) is always dark and is never themed,
# so popup body text must stay light in every palette — the themed C.TEXT is
# dark in the light themes and renders dark-on-dark (invisible).
POPUP_TEXT = (0.93, 0.93, 0.95, 1.0)


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

class CenteredTextInput(TextInput):
    """Single-line input with text centered horizontally and vertically.

    Kivy's TextInput supports `halign` but has no `valign`, so the vertical
    centering is done by padding the single line to the field's height.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("halign", "center")
        super().__init__(**kwargs)
        self.bind(height=self._recenter, line_height=self._recenter,
                  font_size=self._recenter)
        self._recenter()

    def _recenter(self, *_args):
        pad = self.padding  # [left, top, right, bottom]
        pad_v = max(0, (self.height - self.line_height) / 2.0)
        new = [pad[0], pad_v, pad[2], pad_v]
        if new != list(pad):
            self.padding = new


_FG_LIGHT = [0.96, 0.96, 0.98, 1]   # near-white glyph for dark backgrounds
_FG_DARK = [0.13, 0.13, 0.16, 1]    # near-black glyph for light backgrounds


def _rel_luminance(rgba):
    def _ch(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgba[:3]
    return 0.2126 * _ch(r) + 0.7152 * _ch(g) + 0.0722 * _ch(b)


def _contrast(a, b):
    la, lb = _rel_luminance(a), _rel_luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def readable_fg(bg):
    """Light or dark glyph colour, whichever has the higher WCAG contrast with bg."""
    return _FG_DARK if _contrast(_FG_DARK, bg) >= _contrast(_FG_LIGHT, bg) else _FG_LIGHT


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
        vertical = kwargs.pop("vertical", False)
        # Glyph colour role (re-applied on bg/theme change so it never keeps a stale snapshot;
        # the class default is a frozen import-time ~white that rendered icons invisible on
        # light themes). AUTO (no text_color) = pick light/dark for the highest contrast with
        # THIS button's bg — fixes both light-icon-on-light-fill and dark-on-saturated cases.
        # Explicit C.TEXT / C.TEXT_SECONDARY follow that theme role; any other colour is fixed.
        passed = kwargs.get("text_color")
        super().__init__(**kwargs)
        if passed is None:
            self._text_role = "AUTO"
        elif list(passed) == list(C.TEXT):
            self._text_role = "TEXT"
        elif list(passed) == list(C.TEXT_SECONDARY):
            self._text_role = "TEXT_SECONDARY"
        else:
            self._text_role = None
        self._apply_role_text()
        self.orientation = "vertical" if vertical else "horizontal"
        self.padding = [dp(2), dp(2)] if vertical else [dp(12), 0]

        # Text-only label sizing depends on layout direction.
        text_font = (F.TINY if vertical and self.icon else self.font_size)
        self._label = Label(
            text=self.text,
            color=self.text_color,
            font_size=text_font,
            bold=self.bold,
            halign="center",
            valign="middle",
        )
        self._label.bind(size=self._label.setter("text_size"))

        self._icon_label = None
        if self.icon and ICONS_AVAILABLE:
            icon_kwargs = {"font_name": "Icons"}
            if not self.text:
                self._icon_label = Label(
                    text=self.icon,
                    font_size=self.font_size + dp(6),
                    color=self.text_color,
                    halign="center",
                    valign="middle",
                    **icon_kwargs,
                )
                self._icon_label.bind(size=self._icon_label.setter("text_size"))
                self.add_widget(self._icon_label)
            elif vertical:
                # Icon on top, text on bottom — mobile tab-bar convention.
                self._icon_label = Label(
                    text=self.icon,
                    font_size=self.font_size + dp(2),
                    color=self.text_color,
                    halign="center",
                    valign="middle",
                    size_hint_y=0.6,
                    **icon_kwargs,
                )
                self._icon_label.bind(size=self._icon_label.setter("text_size"))
                self._label.size_hint_y = 0.4
                self.add_widget(self._icon_label)
                self.add_widget(self._label)
            else:
                self._icon_label = Label(
                    text=self.icon,
                    font_size=self.font_size + dp(4),
                    color=self.text_color,
                    size_hint_x=None,
                    width=dp(26),
                    **icon_kwargs,
                )
                self.add_widget(self._icon_label)
                self.add_widget(self._label)
        else:
            self.add_widget(self._label)

        self.bind(
            text=self._update_label,
            text_color=self._update_colors,
            bg_color=self._on_bg_change,
            size=self._redraw,
            pos=self._redraw,
            disabled=self._redraw,
        )
        self._redraw()
        C.add_listener(self._on_theme_change)

    def _on_theme_change(self, *args):
        """Re-apply the glyph colour role, then repaint."""
        self._apply_role_text()
        self._redraw()

    def _on_bg_change(self, *args):
        """Background changed — AUTO contrast depends on it; re-resolve then repaint."""
        self._apply_role_text()
        self._redraw()

    def _apply_role_text(self):
        """Resolve the glyph colour role into text_color (-> _update_colors via binding)."""
        if self._text_role == "AUTO":
            self.text_color = readable_fg(self.bg_color)
        elif self._text_role == "TEXT":
            self.text_color = list(C.TEXT)
        elif self._text_role == "TEXT_SECONDARY":
            self.text_color = list(C.TEXT_SECONDARY)

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
        # Disabled: dim BOTH label and icon to 60% of the max-contrast glyph for the
        # (greyed) disabled bg. The greyed background already signals 'disabled', so the
        # glyph stays legible (~4:1) instead of washing into a light card the way the
        # theme's light TEXT_MUTED did. Enabled restores the live text colour; pressed
        # leaves the glyph alone (only the background dims).
        if self.disabled:
            tgt = readable_fg(bg)
            fg = [tgt[i] * 0.6 + bg[i] * 0.4 for i in range(3)] + [1]
        else:
            fg = list(self.text_color)
        self._label.color = fg
        if self._icon_label:
            self._icon_label.color = fg

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
        # Also re-fire _update_height when grandchild widgets resize the
        # content (e.g. populate_bt_devices appending rows after the section
        # was already opened). Without this, _scroll.height keeps the value
        # snapshotted on the original add_widget call and the ScrollView
        # clips later additions to a single visible row.
        self._content.bind(minimum_height=lambda *_: self._update_height())
        self._scroll = ScrollView(size_hint_y=None, height=0)
        self._scroll.add_widget(self._content)
        super().add_widget(self._scroll)

        if collapsed:
            self._scroll.height = 0
            self._scroll.opacity = 0
            self._scroll.remove_widget(self._content)

        self._scroll.bind(height=self._recalc_height)
        self._recalc_height()
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

    def open(self):
        """Programmatically expand this section and collapse siblings."""
        if self._accordion:
            self._accordion._on_section_open(self)
        if self._collapsed:
            self._set_collapsed(False)

    def _set_collapsed(self, collapsed, notify=True):
        self._collapsed = collapsed
        if collapsed:
            # Detach the content so a collapsed section has no geometry below its
            # header. Otherwise its display-clipped widgets still overlap the
            # sections beneath in the touch layer and, via the nested-ScrollView
            # simulated click, steal taps aimed at those section headers.
            if self._content.parent is self._scroll:
                self._scroll.remove_widget(self._content)
            self._scroll.height = 0
            self._scroll.opacity = 0
            if not self._header_icon_text:
                self._header._icon_label.text = Icons.CHEVRON_RIGHT
        else:
            if self._content.parent is not self._scroll:
                self._scroll.add_widget(self._content)
            self._scroll.opacity = 1
            self._update_height()
            if not self._header_icon_text:
                self._header._icon_label.text = Icons.CHEVRON_DOWN

    def _recalc_height(self, *args):
        """Set section height = header + scroll content height."""
        self.height = dp(38) + self._scroll.height

    def _update_height(self):
        if self._collapsed:
            self._scroll.height = 0
        else:
            content_h = self._content.minimum_height
            self._scroll.height = min(content_h, dp(500))

    def _refresh_theme(self):
        self._header.bg_color = C.BG_CARD
        self._header.text_color = C.TEXT_SECONDARY


class RevealBox(BoxLayout):
    """Touch-safe conditional row: shows/hides its content by DETACHING the children,
    never collapse-in-place. Hidden = height 0 and no attached children, so it can't
    overflow or eat a neighbour's taps. (Kivy's Widget.on_touch_down consumes a tap on
    any colliding `disabled` widget, so the height=0/opacity=0/disabled idiom turns a
    hidden row into an invisible tap-eater — use this instead.)"""

    def __init__(self, content_height, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        super().__init__(**kwargs)
        self._content_height = content_height
        self._content_widgets: list = []
        self._revealed = False
        self.height = 0

    def set_content(self, *widgets) -> None:
        """Register the row's widgets; the row starts hidden (children detached)."""
        self._content_widgets = list(widgets)
        self._refresh()

    def reveal(self, show: bool) -> None:
        if bool(show) == self._revealed:
            return
        self._revealed = bool(show)
        self._refresh()

    @property
    def revealed(self) -> bool:
        return self._revealed

    def _refresh(self) -> None:
        self.clear_widgets()
        if self._revealed:
            for w in self._content_widgets:
                self.add_widget(w)
            self.height = self._content_height
        else:
            self.height = 0


class PresetRow(BoxLayout):
    """Row of quick-pick value buttons for a slider or action.

    Two APIs:
        # numeric presets
        presets = PresetRow(values=[30, 50, 70], callback=slider_set, fmt="{}")

        # labelled presets (allows non-numeric entries like "Free")
        presets = PresetRow(
            items=[("5 min", 5), ("Free", None)],
            callback=handler,
        )

    Optional selection highlight:
        presets.set_selected(5)      # highlights the "5 min" button
        presets.set_selected(None)   # highlights "Free" if present, else clears all
    """

    def __init__(self, values=None, items=None, callback=None, fmt="{}", **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(28))
        kwargs.setdefault("spacing", S.GAP_SM)
        super().__init__(**kwargs)

        if items is None:
            if values is None:
                raise ValueError("PresetRow requires either 'values' or 'items'")
            items = [(fmt.format(v), v) for v in values]

        self._buttons: dict = {}
        self._default_bg = list(C.BG_CARD)
        self._default_text = list(C.TEXT_MUTED)
        self._selected_bg = list(C.ACCENT)
        self._selected_text = list(C.TEXT)

        for label, value in items:
            btn = StyledButton(
                text=label,
                bg_color=self._default_bg,
                text_color=self._default_text,
                font_size=F.TINY,
                height=dp(26),
                bold=False,
            )
            btn._preset_value = value
            if callback:
                btn.bind(on_release=lambda b, cb=callback, val=value: cb(val))
            self._buttons[value] = btn
            self.add_widget(btn)

    def set_selected(self, value) -> None:
        """Highlight the button whose stored value equals `value`; clear others.

        If `value` is not a key, all buttons are un-highlighted.
        """
        for key, btn in self._buttons.items():
            if key == value:
                btn.bg_color = self._selected_bg
                btn.text_color = self._selected_text
                btn.bold = True
            else:
                btn.bg_color = self._default_bg
                btn.text_color = self._default_text
                btn.bold = False


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
        if icon and ICONS_AVAILABLE:
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
