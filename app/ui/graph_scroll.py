"""The scroll view a page of graphs scrolls in: it hands a touch on a graph straight to the graph, which hands a
vertical swipe back as a page scroll."""
from kivy.uix.scrollview import ScrollView

from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.touch_utils import ROUTED_BY, point_in_rect, window_rect


class GraphAwareScrollView(ScrollView):
    """ScrollView that hands touches on a graph straight to the graph (pan, pinch, tap, glyphs) instead of holding them
    to decide on a scroll — except a vertical swipe, which the graph hands back as a page scroll (`scroll_with`)."""

    def _graph_under_touch(self, touch):
        """The graph drawn under the touch (in this view's parent frame), compared in window coordinates.

        A child's x/y are content coordinates (the ScrollView translates the canvas), so testing them against the touch
        let a graph scrolled out of view claim taps on whatever now sits there (#66).
        """
        tx, ty = self.to_window(*touch.pos)
        if not point_in_rect(tx, ty, window_rect(self)):
            return None
        for child in self._walk_children():
            if isinstance(child, ScrollableGraphWidget) and point_in_rect(tx, ty, window_rect(child)):
                return child
        return None

    def _walk_children(self):
        stack = list(self.children)
        while stack:
            child = stack.pop()
            yield child
            if hasattr(child, "children"):
                stack.extend(child.children)

    def _dispatch_to_graph(self, graph, touch) -> bool:
        """Deliver the touch in the graph's parent frame — the one its collide_point and drag maths use."""
        touch.ud[ROUTED_BY] = self
        touch.push()
        try:
            touch.apply_transform_2d(self.to_window)
            touch.apply_transform_2d(graph.parent.to_widget)
            return bool(graph.dispatch("on_touch_down", touch))
        finally:
            touch.pop()

    def scroll_with(self, touch, graph) -> bool:
        """Take over a graph's vertical swipe as a scroll of this page; False (the graph keeps it) when this page can't
        scroll, already scrolls under another finger, or the finger has left the viewport."""
        vp = self._viewport
        if self._touch or not self.do_scroll_y or vp is None or vp.height <= self.height:
            return False
        touch.push()
        try:
            touch.apply_transform_2d(graph.to_window)  # from the graph's parent frame
            touch.apply_transform_2d(self.parent.to_widget)
            if not self.collide_point(*touch.pos):
                return False
            taken = ScrollView.on_touch_down(self, touch)
        finally:
            touch.pop()
        ud = touch.ud.get(self._get_uid())
        if not taken or ud is None:
            return False
        ud["mode"] = "scroll"  # it already moved past the threshold; also stops scroll_timeout handing it back
        return True

    def on_scroll_start(self, touch, check_children=True):
        if (
            self.collide_point(*touch.pos)
            and hasattr(touch, "button")
            and touch.button in ("scrollup", "scrolldown")
            and self._graph_under_touch(touch) is not None
        ):
            return False
        return super().on_scroll_start(touch, check_children)

    def on_touch_down(self, touch):
        # Only intercept touches actually inside the viewport. A graph's logical
        # bounds can extend above/below the visible scroll area (overflowing
        # body), and without this guard those bounds would steal touches from
        # widgets sitting outside the ScrollView (e.g. the Metrics/Raw toggle).
        if self.collide_point(*touch.pos):
            graph = self._graph_under_touch(touch)
            if graph is not None and self._dispatch_to_graph(graph, touch):
                return True
        return super().on_touch_down(touch)
