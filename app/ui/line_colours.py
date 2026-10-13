"""The scored line's colours (#94): the series' own colour, or a gradient by value that reads on the graph's background.

The gradients are sampled from matplotlib's viridis, plasma and turbo and ColorBrewer's RdYlGn (colour stops from low to
high, joined in straight lines); blue › red is the app's own, HSV hue 240° › 0°."""

import colorsys
from functools import lru_cache

from kivy.graphics import Color, Rectangle
from kivy.graphics.texture import Texture
from kivy.metrics import dp

from app.ui.theme import C, Listeners, with_contrast

GRADIENT_TOP = 200.0  # the value at the gradient's top: the metrics graph's axis
MONO = "mono"
DEFAULT = "blue_red"
OPTIONS: tuple[tuple[str, str], ...] = ((MONO, "Mono"), ("blue_red", "Blue › Red"), ("viridis", "Viridis"),
                                        ("plasma", "Plasma"), ("turbo", "Turbo"), ("red_green", "Red › Green"))
_STOPS: dict[str, tuple[str, ...]] = {
    "viridis": ("440154", "3B528B", "21908C", "5DC863", "FDE725"),
    "plasma": ("0D0887", "7E03A8", "CC4678", "F89441", "F0F921"),
    "turbo": ("30123B", "28BBEC", "A2FC3C", "FB8022", "7A0403"),
    "red_green": ("A50026", "D73027", "F46D43", "FDAE61", "FEE08B", "FFFFBF", "D9EF8B", "A6D96A", "66BD63", "1A9850",
                  "006837"),
}
_TEXELS = 64
_SIDEWAYS = (0.5, 0.0, 0.5, 1.0, 0.5, 1.0, 0.5, 0.0)  # a gradient texture's height, laid left to right


def _rgb(hex6: str) -> tuple[float, float, float]:
    return tuple(int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4))


def gradient_rgb(name: str, t: float) -> tuple[float, float, float]:
    """The colour at t (0 at the bottom, 1 at the top) of a gradient as published."""
    t = max(0.0, min(t, 1.0))
    if name == "blue_red":
        return colorsys.hsv_to_rgb((1.0 - t) * (240.0 / 360.0), 0.9, 0.95)
    stops = _STOPS[name]
    x = t * (len(stops) - 1)
    i = min(int(x), len(stops) - 2)
    low, high = _rgb(stops[i]), _rgb(stops[i + 1])
    return tuple(a + (b - a) * (x - i) for a, b in zip(low, high))


def gradient_colour(name: str, t: float, bg) -> tuple[float, float, float]:
    """The colour drawn at t on bg: as published where it reads 3:1, else the nearest lightness that does."""
    return with_contrast(gradient_rgb(name, t), bg)


class _LineColours:
    """The profile's choice, applied at once to every graph, as a theme is (add_listener: redraw)."""

    def __init__(self) -> None:
        self.name = DEFAULT
        self._listeners = Listeners()

    def set(self, name: str) -> None:
        if name == self.name:
            return
        self.name = name
        self._listeners.notify("Line colours")

    def add_listener(self, callback) -> None:
        self._listeners.add(callback)


LINE_COLOURS = _LineColours()


@lru_cache(maxsize=None)
def gradient_texture(name: str, bg: tuple) -> Texture:
    """1×64 `name` on `bg`, bottom to top, clamped past either end; refilled after a GL context loss (Android pause)."""
    def fill(texture) -> None:
        texture.wrap = "clamp_to_edge"
        rgba = [(*gradient_colour(name, i / (_TEXELS - 1), bg), 1.0) for i in range(_TEXELS)]
        texture.blit_buffer(bytes(round(c * 255) for px in rgba for c in px), colorfmt="rgba", bufferfmt="ubyte")

    texture = Texture.create(size=(1, _TEXELS), colorfmt="rgba")
    fill(texture)
    texture.add_reload_observer(fill)
    return texture


class GradientStrip:
    """`name`'s gradient as the graphs draw it on this theme, low to high, along the bottom of `widget`: on a strip of
    the graphs' background, the surface its contrast is for, not the widget's own fill."""

    def __init__(self, widget, name: str) -> None:
        self._widget, self._name = widget, name
        with widget.canvas.after:
            self._ground_colour = Color(1, 1, 1, 1)
            self._ground = Rectangle()
            Color(1, 1, 1, 1)
            self._rect = Rectangle()
        widget.bind(pos=self._place, size=self._place)
        widget._gradient_strip = self  # C holds its listener weakly
        C.add_listener(self._paint)
        self._paint()
        self._place()

    def _place(self, *_args) -> None:
        w = self._widget
        self._ground.pos = (w.x + dp(6), w.y + dp(2))
        self._ground.size = (max(w.width - dp(12), 0), dp(5))
        self._rect.pos = (w.x + dp(7), w.y + dp(3))
        self._rect.size = (max(w.width - dp(14), 0), dp(3))

    def _paint(self) -> None:
        self._ground_colour.rgba = C.GRAPH_BG
        self._rect.texture = gradient_texture(self._name, tuple(C.GRAPH_BG))
        self._rect.tex_coords = _SIDEWAYS  # after the texture, which resets them to its own
