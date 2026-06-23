import colorsys
import math
import time as _time
from collections import deque
from typing import Optional

from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import Color, InstructionGroup, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from app.config import APP
from app.ui.theme import C as TC
from app.ui.touch_utils import point_in_rect


class ScrollableGraphWidget(Widget):
    """Scrollable real-time graph with a 5-minute data buffer.

    Features: Y-axis scale numbers, horizontal grid lines, realtime value
    labels at line endpoints, X-axis timestamps. Text rendered via CoreLabel
    textures on canvas.
    """

    def __init__(self, colors: dict[str, tuple], scales: dict[str, float],
                 viewport_seconds: int = 60, show_value_labels: bool = True,
                 show_timestamps: bool = True, sample_rate: float = 0.0,
                 max_points: int = 0, bipolar: bool = False,
                 auto_scale: bool = False, grid_step: float = 20.0,
                 **kwargs) -> None:
        super().__init__(**kwargs)
        self._colors: dict[str, tuple] = colors
        self._scales: dict[str, float] = scales
        self._bipolar: bool = bipolar
        self._auto_scale: bool = auto_scale
        self._grid_step: float = grid_step
        self._markers: list[int] = []
        self._line_width: float = 1.2
        self._sample_rate: float = sample_rate if sample_rate > 0 else (1.0 / APP.UPDATE_FREQUENCY)
        effective_max = max_points if max_points > 0 else APP.GRAPH_POINTS_MAX
        self._viewport_points: int = int(viewport_seconds * self._sample_rate)
        self._data: dict[str, deque] = {
            key: deque(maxlen=effective_max) for key in colors
        }
        self._visible: dict[str, bool] = dict.fromkeys(colors, True)
        # Series in this set are rendered with per-segment heatmap coloring
        # (blue at 0 → red at 100+) instead of the per-key fixed color.
        self._heatmap_keys: set[str] = set()
        self._scroll_offset: int = 0
        self._total_points: int = 0
        self._show_value_labels: bool = show_value_labels
        self._show_timestamps: bool = show_timestamps
        self._touch_start_x: float = 0.0
        self._touch_start_offset: int = 0
        self._default_viewport: int = self._viewport_points
        self._min_viewport: int = max(4, int(self._sample_rate * 2))  # min 2 seconds
        self._max_viewport: int = effective_max  # max = full buffer
        self._zoom_factor: float = 1.3  # each step zooms by 30%
        # Pinch zoom state
        self._pinch_active: bool = False
        self._pinch_start_dist: float = 0.0
        self._pinch_start_viewport: int = 0
        self._grabbed_touches: dict[int, object] = {}
        # Sync group: linked graphs zoom together
        self._sync_group: list["ScrollableGraphWidget"] = []
        self._threshold_value: Optional[float] = None
        self._threshold_scale_key: Optional[str] = None
        # Reference line: solid horizontal line at a fixed value, drawn
        # distinctly from the (dashed) threshold line. Used on the metrics
        # graph to mark level 100 — the per-metric maximum.
        self._reference_value: Optional[float] = None
        self._start_wall_time: Optional[float] = None
        self._scroll_change_callback = None
        self._tap_callback = None
        self._expand_callback = None
        self._touch_moved: bool = False
        self._gfx: InstructionGroup = InstructionGroup()
        self.canvas.add(self._gfx)
        self.bind(size=self._redraw, pos=self._redraw)
        # Bind Window scroll for zoom (bypasses ScrollView interception)
        Window.bind(on_mouse_down=self._on_window_mouse_down)

    def set_threshold(self, value: Optional[float], scale_key: Optional[str] = None) -> None:
        """Set a horizontal threshold line. scale_key picks which series scale to use."""
        self._threshold_value = value
        self._threshold_scale_key = scale_key
        self._redraw()

    def set_reference_line(self, value: Optional[float]) -> None:
        """Set a solid horizontal reference line at `value` (graph units).

        Drawn distinctly from the dashed threshold line. Pass None to clear.
        """
        self._reference_value = value
        self._redraw()

    def set_heatmap_color(self, key: str, enabled: bool = True) -> None:
        """Render `key` series with per-segment heatmap coloring.

        Color gradient: dark blue at value=0, through cyan/green/yellow,
        to red at value=100+ (clamped). Useful for the shamatha score
        line so the visual color tracks meditation depth even when the
        line crosses 100.
        """
        if enabled:
            self._heatmap_keys.add(key)
        else:
            self._heatmap_keys.discard(key)
        self._redraw()

    @staticmethod
    def _heatmap_color(value: float) -> tuple:
        """Blue→red gradient via HSV.

        0 → blue (hue 240°), 100+ → red (hue 0°).  Clamps below 0 and
        above 100. Uses high saturation/value for vivid line color.
        """
        t = max(0.0, min(value / 100.0, 1.0))
        hue = (1.0 - t) * (240.0 / 360.0)
        r, g, b = colorsys.hsv_to_rgb(hue, 0.9, 0.95)
        return (r, g, b, 1.0)

    @property
    def total_points(self) -> int:
        return self._total_points

    @property
    def viewport_points(self) -> int:
        return self._viewport_points

    @property
    def max_scroll(self) -> int:
        return max(0, self._total_points - self._viewport_points)

    def set_line_width(self, width: float) -> None:
        self._line_width = max(0.5, min(width, 5.0))
        self._redraw()

    def set_visible(self, metric: str, visible: bool) -> None:
        if metric in self._visible:
            self._visible[metric] = visible
            self._redraw()

    def set_scroll_offset(self, offset: int) -> None:
        self._scroll_offset = max(0, min(offset, self.max_scroll))
        self._redraw()
        if self._scroll_change_callback:
            self._scroll_change_callback(self._scroll_offset)

    def set_scroll_change_callback(self, callback) -> None:
        self._scroll_change_callback = callback

    def set_start_wall_time(self, epoch: Optional[float]) -> None:
        """Set the session start wall-clock time (epoch seconds) for real-time labels."""
        self._start_wall_time = epoch
        self._redraw()

    def add_point(self, values: dict[str, float]) -> None:
        for key in self._data:
            val = values.get(key, 0.0)
            self._data[key].append(val)
        first_key = next(iter(self._data))
        self._total_points = len(self._data[first_key])
        self._redraw()

    def add_points_batch(self, key: str, values: list[float]) -> None:
        """Add multiple points for a single series without per-point redraw."""
        if key not in self._data:
            return
        for val in values:
            self._data[key].append(val)
        first_key = next(iter(self._data))
        self._total_points = len(self._data[first_key])
        self._redraw()

    def load_static_data(self, series: dict[str, list[float]]) -> None:
        """Load pre-recorded data for static display (e.g. diary preview)."""
        for key in self._data:
            d = self._data[key]
            d.clear()
            # extend() is a C-level bulk copy; a Python `for v: append(v)` loop
            # over 30k raw-EEG samples used to take ~1.5 s on Android and
            # contributed to a post-resume ANR after a screen-lock session.
            d.extend(series.get(key, []))
        first_key = next(iter(self._data))
        self._total_points = len(self._data[first_key])
        self._scroll_offset = 0
        self._markers = []
        self._redraw()

    def _make_text_texture(self, text: str, font_size: int = 10,
                           color: tuple = (1, 1, 1, 1)):
        """Render text string to a texture for canvas drawing."""
        cl = CoreLabel(text=text, font_size=dp(font_size), color=color)
        cl.refresh()
        return cl.texture

    def _redraw(self, *args) -> None:
        self._gfx.clear()
        if self.width < 10 or self.height < 10:
            return

        pad_left = dp(48) if self._show_value_labels else dp(10)
        has_wall_time = self._show_timestamps and self._start_wall_time is not None
        pad_bottom = dp(40) if has_wall_time else (dp(28) if self._show_timestamps else dp(10))
        pad_top = dp(10)
        pad_right = dp(60) if self._show_value_labels else dp(10)

        graph_x = self.x + pad_left
        graph_y = self.y + pad_bottom
        graph_w = self.width - pad_left - pad_right
        graph_h = self.height - pad_bottom - pad_top

        if graph_w < 10 or graph_h < 10:
            return

        # Background
        self._gfx.add(Color(*TC.GRAPH_BG))
        self._gfx.add(Rectangle(pos=(self.x, self.y), size=(self.width, self.height)))

        # Compute visible slice
        end_idx = self._total_points - self._scroll_offset
        start_idx = max(0, end_idx - self._viewport_points)

        # Y-axis scale
        if self._auto_scale:
            max_scale = 0.0
            for key in self._data:
                if not self._visible.get(key, True):
                    continue
                data_list = list(self._data[key])
                slice_vals = data_list[start_idx:end_idx]
                if slice_vals:
                    if self._bipolar:
                        peak = max(abs(v) for v in slice_vals)
                    else:
                        peak = max(slice_vals)
                    max_scale = max(max_scale, peak)
            if max_scale < 1.0:
                max_scale = 100.0
            max_scale *= 1.1
        else:
            max_scale = 100.0
            for key in self._data:
                max_scale = max(max_scale, self._scales.get(key, 100.0))

        # Grid lines + Y-axis labels
        if self._bipolar:
            num_grid_lines = 4
            for i in range(num_grid_lines + 1):
                frac = i / num_grid_lines
                y_pos = graph_y + graph_h * frac
                self._gfx.add(Color(*TC.GRAPH_GRID))
                self._gfx.add(Line(points=[graph_x, y_pos, graph_x + graph_w, y_pos], width=0.5))
                if self._show_value_labels:
                    val = max_scale * (frac * 2.0 - 1.0)
                    tex = self._make_text_texture(f"{val:.0f}", font_size=8,
                                                  color=(0.5, 0.5, 0.5, 1))
                    self._gfx.add(Color(*TC.TEXT))
                    self._gfx.add(Rectangle(
                        texture=tex,
                        pos=(graph_x - tex.width - dp(4), y_pos - tex.height / 2),
                        size=tex.size,
                    ))
        else:
            step = self._compute_nice_step(max_scale) if self._auto_scale else self._grid_step
            val = 0.0
            while val <= max_scale:
                frac = val / max_scale if max_scale > 0 else 0
                y_pos = graph_y + graph_h * frac
                self._gfx.add(Color(*TC.GRAPH_GRID))
                self._gfx.add(Line(points=[graph_x, y_pos, graph_x + graph_w, y_pos], width=0.5))
                if self._show_value_labels:
                    tex = self._make_text_texture(f"{val:.0f}", font_size=8,
                                                  color=(0.5, 0.5, 0.5, 1))
                    self._gfx.add(Color(*TC.TEXT))
                    self._gfx.add(Rectangle(
                        texture=tex,
                        pos=(graph_x - tex.width - dp(4), y_pos - tex.height / 2),
                        size=tex.size,
                    ))
                val += step

        # Border
        self._gfx.add(Color(*TC.GRAPH_BORDER))
        self._gfx.add(Line(rectangle=(graph_x, graph_y, graph_w, graph_h), width=1))

        # Threshold line
        if self._threshold_value is not None and not self._bipolar:
            frac_t = min(self._threshold_value / max_scale, 1.0) if max_scale > 0 else 0.0
            y_thresh = graph_y + frac_t * graph_h
            self._gfx.add(Color(*TC.THRESHOLD_LINE))
            dash_w = dp(6)
            gap_w = dp(4)
            x_cur = graph_x
            while x_cur < graph_x + graph_w:
                x_end = min(x_cur + dash_w, graph_x + graph_w)
                self._gfx.add(Line(points=[x_cur, y_thresh, x_end, y_thresh], width=1))
                x_cur = x_end + gap_w
            if self._show_value_labels:
                tex = self._make_text_texture(
                    f"{self._threshold_value:.0f}", font_size=8,
                    color=(1.0, 0.4, 0.2, 1),
                )
                self._gfx.add(Color(*TC.TEXT))
                self._gfx.add(Rectangle(
                    texture=tex,
                    pos=(graph_x + graph_w + dp(3), y_thresh - tex.height / 2),
                    size=tex.size,
                ))

        # Reference line (solid, drawn after threshold so it's on top).
        # Used to mark level 100 on the metrics graph.
        if self._reference_value is not None and not self._bipolar:
            frac_r = min(self._reference_value / max_scale, 1.0) if max_scale > 0 else 0.0
            y_ref = graph_y + frac_r * graph_h
            self._gfx.add(Color(0.6, 0.6, 0.6, 0.7))
            self._gfx.add(Line(
                points=[graph_x, y_ref, graph_x + graph_w, y_ref], width=1,
            ))

        if end_idx <= start_idx:
            self._draw_expand_icon()
            return

        # X-axis timestamps + vertical grid lines at 10-second intervals
        if self._show_timestamps:
            n_visible = end_idx - start_idx
            vp = max(self._viewport_points, n_visible)
            x_off = vp - n_visible

            t_start = start_idx / self._sample_rate
            t_end = end_idx / self._sample_rate
            grid_sec = 10.0
            # First grid line at nearest 10s boundary >= t_start
            first_mark = math.ceil(t_start / grid_sec) * grid_sec
            if first_mark == 0.0:
                first_mark = grid_sec
            t_mark = first_mark
            while t_mark <= t_end:
                idx_in_data = t_mark * self._sample_rate - start_idx
                frac = (x_off + idx_in_data) / max(vp - 1, 1)
                if 0.0 <= frac <= 1.0:
                    x_pos = graph_x + frac * graph_w
                    # Vertical grid line
                    self._gfx.add(Color(*TC.GRAPH_GRID))
                    self._gfx.add(Line(points=[x_pos, graph_y, x_pos, graph_y + graph_h], width=0.5))
                    # Relative timestamp label
                    mins = int(t_mark) // 60
                    secs = int(t_mark) % 60
                    time_str = f"{mins}:{secs:02d}"
                    tex = self._make_text_texture(time_str, font_size=8,
                                                  color=(0.5, 0.5, 0.5, 1))
                    self._gfx.add(Color(*TC.TEXT))
                    self._gfx.add(Rectangle(
                        texture=tex,
                        pos=(x_pos - tex.width / 2, graph_y - tex.height - dp(2)),
                        size=tex.size,
                    ))
                    # Real wall-clock time label
                    if self._start_wall_time is not None:
                        wall = self._start_wall_time + t_mark
                        lt = _time.localtime(wall)
                        wall_str = f"{lt.tm_hour:02d}:{lt.tm_min:02d}:{lt.tm_sec:02d}"
                        tex2 = self._make_text_texture(wall_str, font_size=7,
                                                       color=(0.4, 0.6, 0.4, 1))
                        self._gfx.add(Color(*TC.TEXT))
                        self._gfx.add(Rectangle(
                            texture=tex2,
                            pos=(x_pos - tex2.width / 2,
                                 graph_y - tex.height - tex2.height - dp(3)),
                            size=tex2.size,
                        ))
                t_mark += grid_sec

        # Data lines + endpoint value labels
        label_y_positions: list[float] = []
        for key, data in self._data.items():
            if not self._visible.get(key, True):
                continue
            data_list = list(data)
            slice_data = data_list[start_idx:end_idx]
            if len(slice_data) < 2:
                continue

            color = self._colors[key]
            scale = self._scales.get(key, 100.0)
            draw_scale = max_scale if not self._bipolar else scale
            heatmap = key in self._heatmap_keys

            n = len(slice_data)
            vp = max(self._viewport_points, n)
            x_offset = vp - n

            # Compute (x, y) for each point once.
            xy: list[tuple[float, float]] = []
            for i, val in enumerate(slice_data):
                x = graph_x + ((x_offset + i) / max(vp - 1, 1)) * graph_w
                if self._bipolar:
                    norm = (val / draw_scale + 1.0) * 0.5
                    y = graph_y + max(0.0, min(norm, 1.0)) * graph_h
                else:
                    y = graph_y + min(max(val, 0.0) / draw_scale, 1.0) * graph_h
                xy.append((x, y))

            if heatmap and not self._bipolar:
                # Per-segment heatmap coloring (color follows the value).
                # One Line per segment; the segment color is derived from
                # the average of its two endpoint values.
                lw = dp(self._line_width)
                for i in range(len(xy) - 1):
                    v_avg = (slice_data[i] + slice_data[i + 1]) * 0.5
                    self._gfx.add(Color(*self._heatmap_color(v_avg)))
                    self._gfx.add(Line(
                        points=[xy[i][0], xy[i][1], xy[i + 1][0], xy[i + 1][1]],
                        width=lw,
                    ))
            else:
                # Single-color line (original behaviour).
                self._gfx.add(Color(*color))
                points = [coord for x, y in xy for coord in (x, y)]
                if len(points) >= 4:
                    max_coords = 1024  # 512 points × 2 coords each
                    if len(points) <= max_coords:
                        self._gfx.add(Line(points=points, width=dp(self._line_width)))
                    else:
                        for chunk_start in range(0, len(points) - 2, max_coords - 2):
                            chunk = points[chunk_start:chunk_start + max_coords]
                            if len(chunk) >= 4:
                                self._gfx.add(Line(points=chunk, width=dp(self._line_width)))

            # Realtime value label at right edge of line
            if self._show_value_labels and slice_data:
                last_val = slice_data[-1]
                if self._bipolar:
                    norm = (last_val / draw_scale + 1.0) * 0.5
                    last_y = graph_y + max(0.0, min(norm, 1.0)) * graph_h
                else:
                    last_y = graph_y + min(max(last_val, 0.0) / draw_scale, 1.0) * graph_h
                # Avoid label overlap by nudging
                for existing_y in label_y_positions:
                    if abs(last_y - existing_y) < dp(12):
                        last_y = existing_y + dp(12)
                label_y_positions.append(last_y)
                short_name = key.replace("_score", "").replace("_", " ")
                tex = self._make_text_texture(
                    f"{last_val:.0f}", font_size=9, color=color,
                )
                self._gfx.add(Color(*TC.TEXT))
                self._gfx.add(Rectangle(
                    texture=tex,
                    pos=(graph_x + graph_w + dp(3), last_y - tex.height / 2),
                    size=tex.size,
                ))

        # Marker vertical lines
        if self._markers:
            n_visible = end_idx - start_idx
            vp = max(self._viewport_points, n_visible)
            x_off = vp - n_visible
            for marker_idx in self._markers:
                if start_idx <= marker_idx < end_idx:
                    idx_in_slice = marker_idx - start_idx
                    frac_m = (x_off + idx_in_slice) / max(vp - 1, 1)
                    if 0.0 <= frac_m <= 1.0:
                        x_pos = graph_x + frac_m * graph_w
                        self._gfx.add(Color(*TC.THRESHOLD_LINE))
                        self._gfx.add(Line(points=[x_pos, graph_y, x_pos, graph_y + graph_h], width=1.5))

        self._draw_expand_icon()

    @staticmethod
    def _compute_nice_step(max_val: float) -> float:
        """Compute a visually pleasing grid step for auto-scaled graphs."""
        if max_val <= 0:
            return 20.0
        raw_step = max_val / 5
        magnitude = 10 ** int(math.log10(max(raw_step, 1e-10)))
        normalized = raw_step / magnitude
        if normalized <= 1.5:
            nice = 1
        elif normalized <= 3.5:
            nice = 2
        elif normalized <= 7.5:
            nice = 5
        else:
            nice = 10
        return nice * magnitude

    @staticmethod
    def link_zoom(*graphs: "ScrollableGraphWidget") -> None:
        """Link graphs so zooming one zooms all. Each graph keeps its own
        sample rate but they share the same time-window duration."""
        group = list(graphs)
        for g in group:
            g._sync_group = [other for other in group if other is not g]

    def _set_viewport(self, points: int, _from_sync: bool = False) -> None:
        """Set viewport size (horizontal zoom), clamped to min/max."""
        self._viewport_points = max(self._min_viewport, min(points, self._max_viewport))
        # Clamp scroll offset to new max
        self._scroll_offset = max(0, min(self._scroll_offset, self.max_scroll))
        self._redraw()
        # Propagate to linked graphs (convert via time duration)
        if not _from_sync and self._sync_group:
            duration = self._viewport_points / self._sample_rate
            for other in self._sync_group:
                other_points = int(duration * other._sample_rate)
                other._set_viewport(other_points, _from_sync=True)

    def zoom_in(self) -> None:
        """Zoom in (show fewer points = more detail)."""
        self._set_viewport(int(self._viewport_points / self._zoom_factor))

    def zoom_out(self) -> None:
        """Zoom out (show more points = wider view)."""
        self._set_viewport(int(self._viewport_points * self._zoom_factor))

    def zoom_reset(self) -> None:
        """Reset to default viewport."""
        self._set_viewport(self._default_viewport)

    def _on_window_mouse_down(self, window, x, y, button, modifiers):
        """Handle mouse scroll at Window level (bypasses ScrollView)."""
        if button not in ("scrollup", "scrolldown"):
            return
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

        # Expand-to-fullscreen icon: intercept before grab so a tap opens
        # fullscreen instead of scrolling. Hit-test in WINDOW coordinates —
        # the only unambiguous frame (GraphAwareScrollView forwards touches in
        # a mid-chain frame matching neither the canvas rect nor to_widget).
        if self._expand_callback is not None and self._touch_on_expand_icon(touch):
            self._expand_callback(self)
            return True

        touch.grab(self)
        self._grabbed_touches[touch.uid] = touch
        self._touch_start_x = touch.x
        self._touch_start_offset = self._scroll_offset
        self._touch_moved = False
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_move(touch)

        dx = abs(touch.x - self._touch_start_x)
        if dx > dp(10):
            self._touch_moved = True

        # Pinch zoom detection (Android / multi-touch)
        active = [t for t in self._grabbed_touches.values()
                  if self.collide_point(*t.pos)]
        if len(active) >= 2:
            t1, t2 = active[0], active[1]
            dist = ((t1.x - t2.x) ** 2 + (t1.y - t2.y) ** 2) ** 0.5
            if not self._pinch_active:
                self._pinch_active = True
                self._pinch_start_dist = max(dist, 1.0)
                self._pinch_start_viewport = self._viewport_points
            else:
                scale = self._pinch_start_dist / max(dist, 1.0)
                new_vp = int(self._pinch_start_viewport * scale)
                self._set_viewport(new_vp)
            return True

        # Single touch — scroll
        graph_w = self.width - dp(58) - dp(60)
        if graph_w > 0 and self._total_points > self._viewport_points:
            dx = touch.x - self._touch_start_x
            points_per_pixel = self._viewport_points / graph_w
            delta_points = int(-dx * points_per_pixel)
            new_offset = self._touch_start_offset + delta_points
            self.set_scroll_offset(new_offset)
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            was_tap = not self._touch_moved and not self._pinch_active
            self._grabbed_touches.pop(touch.uid, None)
            touch.ungrab(self)
            self._pinch_active = False
            if was_tap and self._tap_callback and len(self._grabbed_touches) == 0:
                self._tap_callback()
            return True
        return super().on_touch_up(touch)

    def set_tap_callback(self, callback) -> None:
        """Set callback for single tap on the graph (used for marker on Android)."""
        self._tap_callback = callback

    def set_expand_callback(self, callback) -> None:
        """Set callback invoked with `self` when the fullscreen-expand icon is tapped.

        Setting a callback also reveals the icon; pass None to hide it again.
        """
        self._expand_callback = callback
        self._redraw()

    def _expand_icon_rect(self):
        """Rect (x, y, w, h) for the expand icon, or None when hidden.

        The drawn glyph and the touch hit area use this same rect, so the
        visible box is exactly the tap target.
        """
        if self._expand_callback is None:
            return None
        if self.width < dp(60) or self.height < dp(60):
            return None
        size = dp(44)
        margin = dp(6)
        x = self.x + self.width - size - margin
        y = self.y + self.height - size - margin
        return (x, y, size, size)

    def _touch_on_expand_icon(self, touch) -> bool:
        """True if `touch` falls on the expand glyph, compared in window coords.

        The touch's canonical window position (sx/sy) is compared against the
        glyph's rendered window rect — the one frame that isn't ambiguous under
        the GraphAwareScrollView touch-forwarding transform.
        """
        r = self._expand_icon_rect()
        if r is None:
            return False
        wx0, wy0 = self.to_window(r[0], r[1])
        wx1, wy1 = self.to_window(r[0] + r[2], r[1] + r[3])
        tx, ty = touch.sx * Window.width, touch.sy * Window.height
        win_rect = (min(wx0, wx1), min(wy0, wy1), abs(wx1 - wx0), abs(wy1 - wy0))
        return point_in_rect(tx, ty, win_rect)

    def _draw_expand_icon(self) -> None:
        """Draw the top-right fullscreen-expand glyph (four outward corner brackets)."""
        rect = self._expand_icon_rect()
        if rect is None:
            return
        ix, iy, iw, ih = rect
        # Semi-opaque backing so the glyph reads over any line color / theme.
        self._gfx.add(Color(0, 0, 0, 0.40))
        self._gfx.add(Rectangle(pos=(ix, iy), size=(iw, ih)))
        self._gfx.add(Color(0.92, 0.92, 0.96, 0.95))
        pad = dp(11)
        arm = dp(9)
        left = ix + pad
        right = ix + iw - pad
        bottom = iy + pad
        top = iy + ih - pad
        lw = 1.6
        self._gfx.add(Line(points=[left, bottom + arm, left, bottom, left + arm, bottom], width=lw))
        self._gfx.add(Line(points=[right - arm, bottom, right, bottom, right, bottom + arm], width=lw))
        self._gfx.add(Line(points=[left, top - arm, left, top, left + arm, top], width=lw))
        self._gfx.add(Line(points=[right - arm, top, right, top, right, top - arm], width=lw))

    def add_marker(self, index: Optional[int] = None) -> None:
        """Add a marker at the given data point index (default: current end)."""
        idx = index if index is not None else max(0, self._total_points - 1)
        self._markers.append(idx)
        self._redraw()

    def set_markers(self, markers: list[int]) -> None:
        """Set all markers (for loading from DB)."""
        self._markers = list(markers)
        self._redraw()

    def clear_data(self) -> None:
        for key in self._data:
            self._data[key].clear()
        self._total_points = 0
        self._scroll_offset = 0
        self._markers = []
        self._redraw()


class GraphAwareScrollView(ScrollView):
    """ScrollView that yields touches to ScrollableGraphWidget children inside it.

    Without this, a ScrollView wrapping the graph intercepts press-and-drag
    (treats it as outer scroll) and multi-touch gestures (pinch), preventing
    the graph's own on_touch_down/move handlers from receiving them. This
    subclass first checks whether the touch is over a graph; if so, it
    dispatches directly to the graph and skips ScrollView's own grab logic.
    """

    def _graph_under_touch(self, touch):
        for child in self._walk_children():
            if isinstance(child, ScrollableGraphWidget) and child.collide_point(*touch.pos):
                return child
        return None

    def _walk_children(self):
        stack = list(self.children)
        while stack:
            child = stack.pop()
            yield child
            if hasattr(child, "children"):
                stack.extend(child.children)

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
            if graph is not None:
                return graph.dispatch("on_touch_down", touch)
        return super().on_touch_down(touch)


class RawEEGScreen(Screen):
    """Screen displaying raw EEG signal and frequency band plots."""

    EEG_SIGNAL_COLORS = {
        "eeg": (0.3, 0.8, 1.0, 1.0),
    }

    EEG_SIGNAL_SCALES = {
        "eeg": 500.0,
    }

    EEG_WAVEFORM_RATE: float = 512.0
    EEG_WAVEFORM_MAX: int = 512 * 60  # 60s at 512Hz

    BAND_COLORS = {
        "alpha": (0.1, 0.8, 0.4, 1.0),
        "beta": (0.9, 0.7, 0.1, 1.0),
        "gamma": (1.0, 0.3, 0.3, 1.0),
        "theta": (0.2, 0.5, 0.9, 1.0),
        "delta": (0.4, 0.2, 0.8, 1.0),
    }

    BAND_SCALES = {
        "alpha": 200000.0,
        "beta": 100000.0,
        "gamma": 50000.0,
        "theta": 200000.0,
        "delta": 1500000.0,
    }

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "raw_eeg"
        self._build_ui()

    def _build_ui(self) -> None:
        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(4))

        title = Label(
            text="Raw EEG Data",
            font_size=dp(18),
            bold=True,
            size_hint_y=None,
            height=dp(32),
        )
        root.add_widget(title)

        # --- Raw EEG signal graph (composite waveform) ---
        raw_label = Label(
            text="Raw EEG Signal",
            font_size=dp(12),
            size_hint_y=None,
            height=dp(20),
            color=(0.3, 0.8, 1.0, 1.0),
        )
        root.add_widget(raw_label)

        self._raw_graph = ScrollableGraphWidget(
            colors=self.EEG_SIGNAL_COLORS,
            scales=self.EEG_SIGNAL_SCALES,
            viewport_seconds=10,
            show_value_labels=True,
            show_timestamps=True,
            sample_rate=self.EEG_WAVEFORM_RATE,
            max_points=self.EEG_WAVEFORM_MAX,
            bipolar=True,
            size_hint_y=0.35,
        )
        self._raw_graph.set_scroll_change_callback(self._on_raw_graph_touch_scroll)
        self._syncing_scroll = False
        root.add_widget(self._raw_graph)

        # --- Frequency bands graph ---
        band_label = Label(
            text="Frequency Bands",
            font_size=dp(12),
            size_hint_y=None,
            height=dp(20),
            color=(0.6, 0.6, 0.6, 1.0),
        )
        root.add_widget(band_label)

        self._band_graph = ScrollableGraphWidget(
            colors=self.BAND_COLORS,
            scales=self.BAND_SCALES,
            viewport_seconds=60,
            show_value_labels=True,
            show_timestamps=True,
            auto_scale=True,
            size_hint_y=0.35,
        )
        self._band_graph.set_scroll_change_callback(self._on_band_graph_touch_scroll)
        root.add_widget(self._band_graph)

        # Band legend
        band_legend = BoxLayout(size_hint_y=None, height=dp(20), spacing=dp(2))
        for band, color in self.BAND_COLORS.items():
            lbl = Label(text=band, font_size=dp(9), color=color)
            band_legend.add_widget(lbl)
        root.add_widget(band_legend)

        self.add_widget(root)

    @property
    def raw_graph(self) -> ScrollableGraphWidget:
        return self._raw_graph

    @property
    def band_graph(self) -> ScrollableGraphWidget:
        return self._band_graph

    def add_raw_sample(self, sample: dict[str, float]) -> None:
        """Add raw EEG sample: waveform signal + frequency bands."""
        # Oscillating EEG waveform from sub-sampled burst
        waveform = sample.get("raw_eeg_waveform", [])
        if waveform:
            self._raw_graph.add_points_batch("eeg", waveform)
        else:
            # Fallback: sum of band powers (for v1 mock or real device)
            eeg_sum = sum(
                sample.get(k, 0.0)
                for k in ("delta", "theta", "alpha1", "alpha2",
                          "beta1", "beta2", "gamma1", "gamma2")
            )
            self._raw_graph.add_point({"eeg": eeg_sum})

        # Aggregated frequency bands
        alpha = sample.get("alpha1", 0.0) + sample.get("alpha2", 0.0)
        beta = sample.get("beta1", 0.0) + sample.get("beta2", 0.0)
        gamma = sample.get("gamma1", 0.0) + sample.get("gamma2", 0.0)
        bands = {
            "alpha": alpha,
            "beta": beta,
            "gamma": gamma,
            "theta": sample.get("theta", 0.0),
            "delta": sample.get("delta", 0.0),
        }
        self._band_graph.add_point(bands)

    def _on_raw_graph_touch_scroll(self, offset: int) -> None:
        """Sync band graph when raw graph is touch-scrolled."""
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        band_offset = int(offset / self.EEG_WAVEFORM_RATE * (1.0 / APP.UPDATE_FREQUENCY))
        self._band_graph.set_scroll_offset(band_offset)
        self._syncing_scroll = False

    def _on_band_graph_touch_scroll(self, band_offset: int) -> None:
        """Sync raw graph when band graph is touch-scrolled."""
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        raw_offset = int(band_offset * self.EEG_WAVEFORM_RATE * APP.UPDATE_FREQUENCY)
        self._raw_graph.set_scroll_offset(raw_offset)
        self._syncing_scroll = False


if __name__ == "__main__":
    pass
