"""A graph's touch: pan with one finger, pinch to zoom, the mouse wheel's zoom, a tap (on the plot or a glyph) and the
vertical swipe a graph hands back to the page it is on."""
from kivy.metrics import dp

from app.ui.touch_utils import ROUTED_BY, point_in_rect

_GLYPH_DRIFT_DP = 20  # a glyph's press survives this much drift; more is a pan (a pan starts at 10)


class GraphGestures:
    """Mixed into ScrollableGraphWidget, which provides the viewport (_scroll_offset, set_scroll_offset, _zoom_base,
    _set_viewport, zoom_in/zoom_out, _plot_rect), the glyphs (their callbacks and rects) and _redraw."""

    def _init_gestures(self) -> None:
        self._touch_start_offset: int = 0  # scroll offset when the current gesture's pan started
        self._pinch_active: bool = False
        self._pinch_start_dist: float = 0.0
        self._pinch_start_viewport: int = 0
        # uid → {"start", "pos"} of each finger in this graph's parent frame (another touch's .pos may be in any frame)
        self._grabbed_touches: dict[int, dict[str, tuple[float, float]]] = {}
        self._tap_cancelled: bool = False  # the gesture moved (either axis) or pinched: no tap on release
        self._gesture_pinched: bool = False
        self._touch_moved: bool = False
        self._pressed_glyph = None  # the rect function of the glyph under a finger, drawn pressed

    def _on_window_mouse_down(self, window, x, y, button, modifiers):
        """Handle mouse scroll at Window level (bypasses ScrollView)."""
        if button not in ("scrollup", "scrolldown") or self.get_root_window() is None:
            return  # a graph off screen (a hidden screen or tab) keeps its last place under the pointer
        # Convert window coords to widget coords and check collision
        wx, wy = self.to_widget(x, y, relative=False)
        if not self.collide_point(wx, wy):
            return
        if button == "scrollup":
            self.zoom_in()
        elif button == "scrolldown":
            self.zoom_out()

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)

        # Skip scroll events — handled by _on_window_mouse_down
        if hasattr(touch, "button") and touch.button in ("scrollup", "scrolldown"):
            return True

        touch.grab(self)
        if self._grabbed_touches:  # a second finger: a pinch or a two-finger tap, never a tap
            self._tap_cancelled = True
        if not self._grabbed_touches:  # a new gesture
            self._touch_start_offset = self._scroll_offset
            self._touch_moved = False
            self._tap_cancelled = False
            self._gesture_pinched = False
        # A glyph over the data is a button: grabbed like any touch, it fires on a clean tap's release (on_touch_up).
        glyph = self._glyph_at(touch)
        self._grabbed_touches[touch.uid] = {"start": tuple(touch.pos), "pos": tuple(touch.pos), "glyph": glyph}
        if glyph is not None:
            self._press_glyph(glyph[1])
        return True

    def _glyph_at(self, touch):
        """(callback, rect function) of the glyph under `touch` (hit-tested in WINDOW coordinates), or None."""
        for callback, rect in ((self._series_callback, self._series_icon_rect),
                               (self._expand_callback, self._expand_icon_rect),
                               (self._fit_callback, self._fit_icon_rect)):
            if callback is not None and self._touch_in_window_rect(touch, rect()):
                return callback, rect
        return None

    def _press_glyph(self, rect) -> None:
        if rect is not self._pressed_glyph:
            self._pressed_glyph = rect
            self._redraw()

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_move(touch)

        finger = self._grabbed_touches.get(touch.uid)
        if finger is None:
            return True
        finger["pos"] = tuple(touch.pos)
        glyph = finger.get("glyph")
        if glyph is not None:
            sx0, sy0 = finger["start"]
            drift = max(abs(touch.x - sx0), abs(touch.y - sy0))
            if drift <= _GLYPH_DRIFT_DP * dp(1) and self._touch_in_window_rect(touch, glyph[1]()):
                return True  # a fingertip drifting on a glyph: still its press, as on a button
            finger["glyph"] = None  # dragged off it: an ordinary gesture from here
            self._tap_cancelled = True
            self._press_glyph(None)
        sx, sy = finger["start"]
        dx, dy = abs(touch.x - sx), abs(touch.y - sy)
        if dx > dp(10):
            self._touch_moved = True
        if dx > dp(10) or dy > dp(10):
            self._tap_cancelled = True

        # Pinch zoom detection (Android / multi-touch)
        active = [f["pos"] for f in self._grabbed_touches.values() if self.collide_point(*f["pos"])]
        if len(active) >= 2:
            self._gesture_pinched = self._tap_cancelled = True
            (x1, y1), (x2, y2) = active[0], active[1]
            dist = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
            if not self._pinch_active:
                self._pinch_active = True
                self._pinch_start_dist = max(dist, 1.0)
                self._pinch_start_viewport = self._zoom_base()
            else:
                scale = self._pinch_start_dist / max(dist, 1.0)
                new_vp = int(self._pinch_start_viewport * scale)
                self._set_viewport(new_vp)
            return True

        if self._hand_off_vertical_swipe(touch, dx, dy):
            return True

        # Single touch — scroll
        graph_w = self._plot_rect()[2]
        if graph_w > 0 and self._total_points > self._viewport_points:
            dx = touch.x - sx
            points_per_pixel = self._viewport_points / graph_w
            delta_points = int(-dx * points_per_pixel)
            new_offset = self._touch_start_offset + delta_points
            self.set_scroll_offset(new_offset)
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            was_tap = not self._tap_cancelled and not self._pinch_active
            lifted = self._grabbed_touches.pop(touch.uid, None) or {}
            touch.ungrab(self)
            self._pinch_active = False
            if len(self._grabbed_touches) == 1:  # a pinch ended: the remaining finger pans on from where it is
                remaining = next(iter(self._grabbed_touches.values()))
                remaining["start"] = remaining["pos"]
                self._touch_start_offset = self._scroll_offset
            glyph = lifted.get("glyph")
            if glyph is not None:
                self._press_glyph(None)
            if was_tap and len(self._grabbed_touches) == 0:
                if glyph is not None:
                    glyph[0](self)
                else:
                    self.on_tap()
            return True
        return super().on_touch_up(touch)

    def _hand_off_vertical_swipe(self, touch, dx: float, dy: float) -> bool:
        """A single finger moving mostly vertically, before any pan or pinch, scrolls the page that routed it here:
        the graph has no vertical gesture, and in landscape it fills the view the user scrolls to reach the controls."""
        if self._touch_moved or self._gesture_pinched or len(self._grabbed_touches) != 1:
            return False
        if dy < dp(20) or dy < 2 * dx:
            return False
        page = touch.ud.get(ROUTED_BY)  # no walk up the tree: Window.parent is the Window itself
        if page is None or not page.scroll_with(touch, self):
            return False
        self._grabbed_touches.pop(touch.uid, None)
        touch.ungrab(self)
        self.set_scroll_offset(self._touch_start_offset)
        return True

    def _touch_in_window_rect(self, touch, rect) -> bool:
        """True if `touch` falls in `rect`, compared in WINDOW coordinates.

        The touch's canonical window position (sx/sy) vs the rect's rendered
        window rect — the one frame that isn't ambiguous under the
        GraphAwareScrollView touch-forwarding transform.
        """
        if rect is None:
            return False
        wx0, wy0 = self.to_window(rect[0], rect[1])
        wx1, wy1 = self.to_window(rect[0] + rect[2], rect[1] + rect[3])
        tx, ty = self.to_window(*touch.pos)  # touch.pos is in this graph's parent frame; sx/sy ignore Rotate Screen
        win_rect = (min(wx0, wx1), min(wy0, wy1), abs(wx1 - wx0), abs(wy1 - wy0))
        return point_in_rect(tx, ty, win_rect)
