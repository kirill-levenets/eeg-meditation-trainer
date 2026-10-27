"""A graph's glyphs, the small buttons drawn over its corners: the series picker, the fit and the fullscreen toggle
(or close). The same rect places each one's drawing and its tap target."""
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.metrics import dp

from app.ui.theme import C as TC


class GraphGlyphs:
    """Mixed into ScrollableGraphWidget, which provides _gfx, the plot rect and pads, and _pressed_glyph (the gesture
    state of the glyph under a finger); a glyph shows only once its callback is set."""

    def _init_glyphs(self) -> None:
        self._expand_callback = None
        self._expand_closes = False  # in fullscreen the corner glyph is the close cross
        self._series_callback = None
        self._fit_callback = None

    def _draw_glyphs(self) -> None:
        pressed = self._pressed_glyph() if self._pressed_glyph is not None else None
        if pressed is not None:  # a light disc under the glyph a finger is on
            self._gfx.add(Color(*TC.TEXT[:3], 0.18))
            self._gfx.add(RoundedRectangle(pos=pressed[:2], size=pressed[2:], radius=[dp(10)]))
        self._draw_series_icon()
        self._draw_fit_icon()
        self._draw_expand_icon()

    def set_expand_callback(self, callback, closes: bool = False) -> None:
        """The top-right glyph's tap: fullscreen-expand, or with `closes` the close cross; None hides it."""
        self._expand_callback = callback
        self._expand_closes = closes
        self._redraw()

    def set_series_picker_callback(self, callback) -> None:
        """Set callback invoked with `self` when the series-picker glyph is tapped.

        Setting a callback reveals the glyph (top-left); pass None to hide it.
        """
        self._series_callback = callback
        self._redraw()

    def set_fit_callback(self, callback) -> None:
        """Set callback invoked with `self` when the fit-whole-session glyph is tapped; None hides the glyph."""
        self._fit_callback = callback
        self._redraw()

    def _icon_too_small(self) -> bool:
        return self.width < dp(60) or self.height < dp(60)

    def _corner_rect(self, right: bool, top: bool):
        """A glyph's rect (x, y, w, h) in a corner of the plot area."""
        size, margin = dp(44), dp(2)
        px, py, pw, ph = self._plot_rect()
        return (px + pw - size - margin if right else px + margin, py + ph - size - margin if top else py + margin,
                size, size)

    def _expand_icon_rect(self):
        """Rect (x, y, w, h) for the expand glyph (the plot's top-right corner), or None when hidden."""
        if self._expand_callback is None or self._icon_too_small():
            return None
        return self._corner_rect(right=True, top=True)

    def _fit_icon_rect(self):
        """Rect (x, y, w, h) for the fit glyph (the plot's bottom-right), or None: hidden where it would meet expand."""
        if self._fit_callback is None or self._icon_too_small():
            return None
        rect, expand = self._corner_rect(right=True, top=False), self._expand_icon_rect()
        if expand is not None and rect[1] + rect[3] > expand[1]:
            return None
        return rect

    def _series_icon_rect(self):
        """Rect (x, y, w, h) for the series-picker glyph (the plot's top-left corner), or None."""
        if self._series_callback is None or self._icon_too_small():
            return None
        return self._corner_rect(right=False, top=True)

    def _draw_icon_backing(self, rect) -> None:
        # Transparent background — the glyph sits directly on the graph. Set the
        # glyph color (TEXT) here for the Line instructions that follow; TEXT
        # contrasts with GRAPH_BG on every palette.
        self._gfx.add(Color(*TC.TEXT))

    def _draw_expand_icon(self) -> None:
        """Top-right fullscreen-expand glyph (four outward corner brackets), or in fullscreen a close cross."""
        rect = self._expand_icon_rect()
        if rect is None:
            return
        self._draw_icon_backing(rect)
        ix, iy, iw, ih = rect
        pad, arm, lw = dp(11), dp(9), 1.6
        left, right = ix + pad, ix + iw - pad
        bottom, top = iy + pad, iy + ih - pad
        if self._expand_closes:
            self._gfx.add(Line(points=[left + dp(2), bottom + dp(2), right - dp(2), top - dp(2)], width=lw))
            self._gfx.add(Line(points=[left + dp(2), top - dp(2), right - dp(2), bottom + dp(2)], width=lw))
            return
        self._gfx.add(Line(points=[left, bottom + arm, left, bottom, left + arm, bottom], width=lw))
        self._gfx.add(Line(points=[right - arm, bottom, right, bottom, right, bottom + arm], width=lw))
        self._gfx.add(Line(points=[left, top - arm, left, top, left + arm, top], width=lw))
        self._gfx.add(Line(points=[right - arm, top, right, top, right, top - arm], width=lw))

    def _draw_fit_icon(self) -> None:
        """|<->| shows the whole session, ->|<- goes back to the window."""
        rect = self._fit_icon_rect()
        if rect is None:
            return
        self._draw_icon_backing(rect)
        ix, iy, iw, ih = rect
        pad, head, lw = dp(11), dp(4), 1.6
        left, right, mid = ix + pad, ix + iw - pad, iy + ih / 2
        bar = dp(7)
        if self.fitted:  # two arrows pointing in at a centre bar
            cx, reach = ix + iw / 2, dp(15)
            self._gfx.add(Line(points=[cx, mid - bar, cx, mid + bar], width=lw))
            for tip, tail in ((cx - dp(4), cx - reach), (cx + dp(4), cx + reach)):
                back = dp(3) if tip > tail else -dp(3)
                self._gfx.add(Line(points=[tail, mid, tip, mid], width=lw))
                self._gfx.add(Line(points=[tip - back, mid + dp(3), tip, mid, tip - back, mid - dp(3)], width=lw))
        else:  # a double arrow between two bars
            self._gfx.add(Line(points=[left, mid - bar, left, mid + bar], width=lw))
            self._gfx.add(Line(points=[right, mid - bar, right, mid + bar], width=lw))
            self._gfx.add(Line(points=[left + dp(2), mid, right - dp(2), mid], width=lw))
            for tip, back in ((left + dp(2), head), (right - dp(2), -head)):
                self._gfx.add(Line(points=[tip + back, mid + head, tip, mid, tip + back, mid - head], width=lw))

    def _draw_series_icon(self) -> None:
        """Top-left series-picker glyph: three stacked lines (a list) + a chevron."""
        rect = self._series_icon_rect()
        if rect is None:
            return
        self._draw_icon_backing(rect)
        ix, iy, iw, ih = rect
        pad, lw = dp(12), 1.6
        left, right = ix + pad, ix + iw - pad
        for i in range(3):  # three horizontal "list" lines, top to bottom
            ly = iy + ih - pad - i * dp(6)
            self._gfx.add(Line(points=[left, ly, right, ly], width=lw))
