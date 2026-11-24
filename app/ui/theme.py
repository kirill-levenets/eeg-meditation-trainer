"""The app's theme: palettes (C), text sizes (F), spacing (S), the themed label and text input that follow them, text
fitting and contrast. The widgets built on it are in app/ui/widgets/."""

import colorsys
import os
import types
import weakref

from kivy.core.text import Label as CoreLabel
from kivy.core.text import LabelBase
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import ListProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput

from app.logger import logger
from app.ui.kivy_providers import clipboard_without_commands

clipboard_without_commands()  # before any text input asks Kivy for its clipboard

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


class Icons:
    """Material Design Icon codepoints (used with font_name='Icons')."""
    PLAY = "\U000F040A"
    PAUSE = "\U000F03E4"
    STOP = "\U000F04DB"
    PENCIL = "\U000F03EB"
    DELETE = "\U000F01B4"
    CHECK = "\U000F012C"
    CHECKBOX_MARKED = "\U000F0132"
    CHECKBOX_BLANK = "\U000F0131"  # checkbox-blank-outline
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

DEFAULT_THEME = "Dark Blue"

THEMES = {
    "Dark Blue": _DARK_BLUE,
    "Dark Green": _DARK_GREEN,
    "Light Cream": _LIGHT_CREAM,
    "Light Green": _LIGHT_GREEN,
}


class ThemeColor(tuple):
    """A palette RGBA that remembers its role, so a themed widget or ThemedColor given it follows theme switches.
    list() or a slice of it is a plain, fixed colour."""

    def __new__(cls, rgba, role: str):
        color = super().__new__(cls, rgba)
        color.role = role
        return color


class Listeners(dict):
    """Callbacks run after a change, once each; a bound method is held weakly so it never keeps its widget alive."""

    def add(self, callback) -> None:
        if isinstance(callback, types.MethodType):
            ref = weakref.WeakMethod(callback, self._forget)
            self[ref] = ref
        else:
            self[callback] = lambda: callback

    def _forget(self, ref) -> None:
        self.pop(ref, None)

    def notify(self, change: str) -> None:
        for get in list(self.values()):
            callback = get()
            if callback is None:
                continue
            try:
                callback()
            except Exception:
                logger.exception("%s listener %r failed", change, callback)


class _ColorAccessor:
    """The active palette as attributes (C.PRIMARY, C.BG, ...), swappable at runtime.

    A colour read from it carries its role. A theme switch re-applies every role a themed widget property
    (ThemedMixin) or a ThemedColor was given, then calls the listeners for bespoke repaints.
    """

    def __init__(self):
        self._listeners = Listeners()
        self._roles = weakref.WeakKeyDictionary()  # themed widget -> {colour property: role}
        self._canvas_colors = weakref.WeakSet()
        self._use(DEFAULT_THEME)

    def _use(self, name: str) -> None:
        self._palette = {role: ThemeColor(rgba, role) for role, rgba in THEMES[name].items()}
        self._name = name

    def __getattr__(self, name):
        if name.startswith("_"):
            return super().__getattribute__(name)
        try:
            return self._palette[name]
        except KeyError:
            raise AttributeError(f"No color '{name}' in theme")

    def set_theme(self, name: str) -> None:
        """Switch the active palette, re-apply every themed colour, then notify listeners."""
        if name not in THEMES or name == self._name:
            return
        self._use(name)
        for widget, roles in list(self._roles.items()):
            try:
                for prop, role in list(roles.items()):
                    setattr(widget, prop, self._palette[role])
            except Exception:
                logger.exception("Theme repaint of %r failed", widget)
        for instr in list(self._canvas_colors):
            instr.rgba = self._rgba(instr.role, instr.pinned_alpha)
        self._listeners.notify("Theme")

    def add_listener(self, callback) -> None:
        """Call back after every theme switch (Listeners)."""
        self._listeners.add(callback)

    def resolve(self, color):
        """A colour to draw now: a palette colour in the current palette (even one read before a switch, e.g. a
        module-level series colour), any other colour as it is."""
        role = getattr(color, "role", None)
        return self._palette[role] if role else color

    def _rgba(self, role: str, alpha: float | None = None) -> tuple:
        rgba = self._palette[role]
        return tuple(rgba) if alpha is None else (*rgba[:3], alpha)

    def _themed_value(self, widget, prop: str, value):
        """The value to store in a themed widget's colour property: a palette colour is recorded by role and resolved
        in the current palette (even one read before a switch); any other value drops the role and stays fixed."""
        role = getattr(value, "role", None)
        if role is None:
            roles = self._roles.get(widget)
            if roles:
                roles.pop(prop, None)
            return value
        self._roles.setdefault(widget, {})[prop] = role
        return self._palette[role]

    @property
    def theme_name(self) -> str:
        return self._name


C = _ColorAccessor()


# ── Typography ───────────────────────────────────────────────────────

class FontSize(float):
    """A size from F that keeps its normal-size base and cap, so a themed widget given it follows the text size."""

    def __new__(cls, base: float, cap: float | None = None):
        size = super().__new__(cls, base * (F.SCALE if cap is None else min(F.SCALE, cap)))
        size.base = base
        size.cap = cap
        return size


class F:
    """Font sizes at the text size in use; a change re-applies them to themed widgets, then runs the listeners."""
    _BASE = {
        "DISPLAY": 48,  # timer countdown
        "H1": 22,       # screen title
        "H2": 16,       # section header
        "H3": 14,       # subsection / important label
        "BODY": 13,     # standard text
        "SMALL": 11,    # secondary info
        "TINY": 9,      # axis labels, metadata
    }
    SCALE = 1.0
    CAPPED_MAX = 1.2  # the most a capped text grows: one in a box that can't (a fixed bar, a small toggle)
    _sized = weakref.WeakKeyDictionary()  # themed widget -> {font property: (its size at the normal text size, cap)}
    _listeners = Listeners()

    @classmethod
    def px(cls, size: float) -> FontSize:
        """A size off the roles (a graph's labels, Kivy's own defaults) at the text size in use."""
        return FontSize(dp(size))

    @classmethod
    def capped(cls, size: FontSize, cap: float | None = None) -> FontSize:
        """`size` growing only up to `cap` (CAPPED_MAX): for text in a box that can't grow with it."""
        return FontSize(size.base, cls.CAPPED_MAX if cap is None else cap)

    @classmethod
    def box(cls, size: float, cap: float | None = None) -> float:
        """A box sized for its text, as a plain float: its owner re-reads it in an F.add_listener."""
        return dp(size) * (cls.SCALE if cap is None else min(cls.SCALE, cap))

    @staticmethod
    def glyph(size: float) -> float:
        """An icon in fixed chrome (the bottom nav): not text, so it keeps its size whatever the text size."""
        return dp(size)

    @classmethod
    def set_scale(cls, scale: float) -> None:
        """Use another text size; the size in use is a no-op, as a profile load applying it at startup is."""
        if scale == cls.SCALE:
            return
        cls.SCALE = scale
        cls._set_roles()
        for widget, sized in list(cls._sized.items()):
            try:
                for prop, (base, cap) in list(sized.items()):
                    setattr(widget, prop, FontSize(base, cap))
            except Exception:
                logger.exception("Text size change of %r failed", widget)
        cls._listeners.notify("Text size")

    @classmethod
    def _set_roles(cls) -> None:
        for role, size in cls._BASE.items():
            setattr(cls, role, cls.px(size))

    @classmethod
    def add_listener(cls, callback) -> None:
        """Call back after every text size change (Listeners)."""
        cls._listeners.add(callback)

    @classmethod
    def _sized_value(cls, widget, prop: str, value):
        """A size from F is recorded and stored at the size in use (even one read before a change); any other is fixed."""
        if not isinstance(value, FontSize):
            sized = cls._sized.get(widget)
            if sized:
                sized.pop(prop, None)
            return value
        cls._sized.setdefault(widget, {})[prop] = (value.base, value.cap)
        return float(FontSize(value.base, value.cap))


F._set_roles()

# The text sizes on offer: (scale, name). The largest is the one every screen is checked at.
TEXT_SIZES: tuple[tuple[float, str], ...] = ((1.0, "Normal"), (1.25, "Large"), (1.5, "Larger"))


# ── Spacing ──────────────────────────────────────────────────────────

class S:
    """Spacing and sizing constants (dp)."""
    PAGE_PAD = dp(12)     # screen edge padding
    BTN_PAD = dp(12)        # a StyledButton's sides, when it is wide enough for its text on one line
    BTN_PAD_NARROW = dp(2)  # ... and the least they shrink to when it isn't (a narrow button at a larger text size)
    CARD_PAD = dp(10)     # inside card padding
    GAP = dp(8)           # default spacing between elements
    GAP_SM = dp(4)        # compact spacing
    GAP_LG = dp(16)       # section spacing

    ROW_H = dp(42)        # standard interactive row height
    ROW_SM = dp(32)       # compact row
    BTN_H = dp(44)        # button height
    NAV_H = dp(46)        # top nav bar height
    RADIUS = 8            # corner radius (raw px, used in RoundedRectangle)


# ── Themed widgets ───────────────────────────────────────────────────

_THEMED_PROPS = frozenset({
    "color", "disabled_color", "bg_color", "bg_pressed", "text_color", "background_color",
    "foreground_color", "cursor_color", "hint_text_color", "selection_color",
    "title_color", "separator_color", "overlay_color",
})


_FONT_PROPS = frozenset({"font_size", "title_size"})


class ThemedMixin:
    """Mixed in ahead of a Kivy widget: a colour property given a palette colour (C.X) follows theme switches, and a
    font given a size from F follows text size changes; any other colour or size stays fixed."""

    def __setattr__(self, name, value):
        if name in _THEMED_PROPS:
            value = C._themed_value(self, name, value)
        elif name in _FONT_PROPS:
            value = F._sized_value(self, name, value)
        super().__setattr__(name, value)

    def assigned_color(self, prop: str):
        """prop's colour as it was given: the palette colour it follows, or its fixed value. Restoring a saved copy
        restores the role too, where a list() of the property would freeze it."""
        role = C._roles.get(self, {}).get(prop)
        return getattr(C, role) if role else list(getattr(self, prop))


def text_width(text: str, font_size: float, bold: bool = False, font_name: str = "Roboto") -> float:
    """The width `text` takes on one line at this font."""
    core = CoreLabel(text=text, font_size=font_size, bold=bold, font_name=font_name)
    core.refresh()
    return core.texture.size[0]


def fit_height_to_text(label, extra: float = 0) -> None:
    """The label wraps at its width and is as tall as its text (plus `extra`): a fixed height cuts a larger text off."""
    label.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
               texture_size=lambda w, v: setattr(w, "height", v[1] + extra))


def fit_width_to_text(label, extra: float = 0) -> None:
    """The label is as wide as its one-line text (plus `extra`), following a text size change."""
    label.bind(texture_size=lambda w, ts: setattr(w, "width", ts[0] + extra))


def fit_row_to_text(row, label, min_height: float) -> None:
    """The row grows with its wrapping label (at least `min_height`), the label and fixed-height controls centred on it."""
    label.size_hint_y = None
    fit_height_to_text(label)
    label.bind(height=lambda _w, h: setattr(row, "height", max(min_height, h)))
    for child in row.children:
        if child is label or child.size_hint_y is None:
            child.pos_hint = {**child.pos_hint, "center_y": 0.5}


class ThemedLabel(ThemedMixin, Label):
    """The app's Label: its colours follow theme switches."""

    def __init__(self, **kwargs):
        kwargs.setdefault("font_size", F.px(15))  # Kivy's own default size, at the text size in use
        super().__init__(**kwargs)


class ThemedTextInput(ThemedMixin, TextInput):
    """The app's TextInput: the theme's input colours by default, following theme switches."""

    def __init__(self, **kwargs):
        kwargs.setdefault("foreground_color", C.TEXT)
        kwargs.setdefault("background_color", C.BG_INPUT)
        kwargs.setdefault("cursor_color", C.PRIMARY)
        kwargs.setdefault("font_size", F.px(15))  # Kivy's own default size, at the text size in use
        super().__init__(**kwargs)


class ThemedColor(Color):
    """Canvas Color drawn with a palette colour (C.X) that re-reads its role on every theme switch; alpha= pins
    the alpha (by default it is the palette's)."""

    def __init__(self, color: ThemeColor, alpha: float | None = None, **kwargs):
        super().__init__(*C._rgba(color.role, alpha), **kwargs)
        self.role = color.role
        self.pinned_alpha = alpha
        C._canvas_colors.add(self)


class CenteredTextInput(ThemedTextInput):
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


def dimmed_fg(bg) -> list[float]:
    """A disabled control's glyph on its greyed bg: 60 % of the readable one, legible (~4:1) without reading as live."""
    tgt = readable_fg(bg)
    return [tgt[i] * 0.6 + bg[i] * 0.4 for i in range(3)] + [1]


def with_contrast(rgb, bg, floor: float = 3.0) -> tuple[float, float, float]:
    """rgb, or as close to it as reaches floor:1 (WCAG) on bg: the same hue and saturation, lighter on a dark bg and
    darker on a light one."""
    if _contrast(rgb, bg) >= floor:
        return tuple(rgb[:3])
    hue, lightness, saturation = colorsys.rgb_to_hls(*rgb[:3])
    near, far = lightness, (1.0 if _contrast((1.0, 1.0, 1.0), bg) > _contrast((0.0, 0.0, 0.0), bg) else 0.0)
    for _ in range(24):  # luminance follows lightness, so halving the gap finds the nearest that reads
        mid = (near + far) / 2
        if _contrast(colorsys.hls_to_rgb(hue, mid, saturation), bg) >= floor:
            far = mid
        else:
            near = mid
    return colorsys.hls_to_rgb(hue, far, saturation)


def fill_background(widget, color: ThemeColor) -> None:
    """Paint widget's background with a palette colour that follows its size, position and theme switches."""
    with widget.canvas.before:
        ThemedColor(color)
        rect = Rectangle(size=widget.size, pos=widget.pos)
    widget.bind(size=lambda _w, v: setattr(rect, "size", v), pos=lambda _w, v: setattr(rect, "pos", v))


class Card(ThemedMixin, BoxLayout):
    """Rounded card container with subtle background."""

    bg_color = ListProperty(list(C.BG_CARD))

    def __init__(self, **kwargs):
        kwargs.setdefault("bg_color", C.BG_CARD)
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


class Divider(ThemedMixin, BoxLayout):
    """Thin horizontal line separator."""

    color = ListProperty(list(C.BORDER))

    def __init__(self, **kwargs):
        kwargs.setdefault("color", C.BORDER)
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(1))
        super().__init__(**kwargs)
        self.bind(size=self._redraw, pos=self._redraw, color=self._redraw)
        self._redraw()

    def _redraw(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*self.color)
            Rectangle(pos=self.pos, size=self.size)


