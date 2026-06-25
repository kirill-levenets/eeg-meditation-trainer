"""Touch hit-testing helpers.

Kivy's automatic nested touch dispatch through ScrollViews / custom containers
is unreliable, so this app routes touches manually and hit-tests sub-regions
(History session rows, the graph expand glyph, ...).

Coordinate frame matters: a widget under `GraphAwareScrollView` receives touches
in a mid-chain frame that matches neither its canvas-drawn rect (`touch.x/y`)
nor a `to_widget`/`to_local` conversion. The robust approach there is to compare
in WINDOW coordinates — the touch's canonical window position
(`touch.sx*Window.width, touch.sy*Window.height`) against the target's rendered
window rect (`widget.to_window(...)`). See `ScrollableGraphWidget._touch_in_window_rect`.
`point_in_rect` is the shared rect test used on both sides.
"""


def point_in_rect(px: float, py: float, rect) -> bool:
    """True if (px, py) lies within rect (x, y, w, h). A None rect is never hit."""
    if rect is None:
        return False
    x, y, w, h = rect
    return x <= px <= x + w and y <= py <= y + h
