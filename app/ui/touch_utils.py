"""Touch hit-testing helpers.

Kivy's automatic nested touch dispatch through ScrollViews / custom containers
is unreliable, so this app routes touches manually and hit-tests sub-regions
(History session rows, the graph expand glyph, ...).

Coordinate frame matters: a ScrollView translates its canvas, so its children's
x/y are content coordinates. Compare in WINDOW coordinates — the touch's window
position (`widget.to_window(*touch.pos)` with `touch.pos` in that widget's parent
frame; `touch.sx/sy` ignore the app's screen rotation) against the target's
rendered window rect (`widget.to_window(...)`). See
`ScrollableGraphWidget._touch_in_window_rect` and `GraphAwareScrollView._graph_under_touch`.
`point_in_rect` is the shared rect test used on both sides, `window_rect` a widget's rendered rect.
"""


def point_in_rect(px: float, py: float, rect) -> bool:
    """True if (px, py) lies within rect (x, y, w, h). A None rect is never hit."""
    if rect is None:
        return False
    x, y, w, h = rect
    return x <= px <= x + w and y <= py <= y + h


# touch.ud key: the GraphAwareScrollView that handed this touch to a graph, which hands a vertical swipe back to it.
ROUTED_BY = "graph_aware_scroll_view"


def window_rect(widget) -> tuple[float, float, float, float]:
    """The widget's rendered rectangle in window coordinates (x, y, w, h)."""
    x0, y0 = widget.to_window(widget.x, widget.y)
    x1, y1 = widget.to_window(widget.right, widget.top)
    return min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)
