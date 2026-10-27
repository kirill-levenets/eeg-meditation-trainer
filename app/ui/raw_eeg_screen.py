import math
import time as _time
from collections import OrderedDict, deque
from typing import Optional

from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import (
    Color,
    InstructionGroup,
    Line,
    Mesh,
    Rectangle,
)
from kivy.metrics import dp
from kivy.uix.widget import Widget

from app.config import APP
from app.session.manager import elapsed_clock
from app.session.scoring import extend_steps
from app.ui import render_stats
from app.ui.graph_gestures import GraphGestures
from app.ui.graph_glyphs import GraphGlyphs
from app.ui.graph_runs import RunExtremes, run_indices
from app.ui.hooks import Hook
from app.ui.line_colours import GRADIENT_TOP, LINE_COLOURS, MONO, gradient_texture
from app.ui.theme import C as TC
from app.ui.theme import F

# Labels by (text, font_size, color); the CoreLabel is kept since it re-renders its texture after a GL context loss.
_LABEL_CACHE: "OrderedDict[tuple, CoreLabel]" = OrderedDict()
_LABEL_CACHE_MAX = 512

# X grid steps (s); the smallest that keeps time labels _MIN_X_LABEL_GAP_DP apart is used.
_X_GRID_STEPS_S = (10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200)
_MAX_Y_GRID_LINES = 20  # a fixed grid step far below the scale gives way to a nice one (each line has a label)
_MIN_X_LABEL_GAP_DP = 70
# New data waits its last redraw's cost / _REDRAW_BUDGET once a redraw takes _SLOW_REDRAW_S (graphs.md, item 6).
_REDRAW_BUDGET = 0.1
_SLOW_REDRAW_S = 0.025


def _free_label_y(y: float, taken: list[float], low: float, high: float) -> float:
    """The nearest place to `y` for a line-end label, upward first, clear of `taken` and within [low, high]."""
    step = dp(12)
    for k in range(0, 64):
        for cand in ((y,) if k == 0 else (y + k * step, y - k * step)):
            if low <= cand <= high and all(abs(cand - t) >= step for t in taken):
                return cand
    return min(max(y, low), high)


def _x_grid_step(graph_w: float, visible_seconds: float) -> float:
    px_per_s = graph_w / max(visible_seconds, 1e-9)
    return next((s for s in _X_GRID_STEPS_S if s * px_per_s >= dp(_MIN_X_LABEL_GAP_DP)), _X_GRID_STEPS_S[-1])


# Kivy caps a Mesh at 65535 indices (GLES2, enforced on Android): 6 per quad, so 10922 quads (43688 vertices).
_MESH_MAX_QUADS = 65535 // 6


class ScrollableGraphWidget(GraphGestures, GraphGlyphs, Widget):
    """Scrollable real-time graph with a 5-minute data buffer.

    Features: Y-axis scale numbers, horizontal grid lines, realtime value
    labels at line endpoints, X-axis timestamps. Text rendered via CoreLabel
    textures on canvas.
    """

    on_series_change = Hook()  # a series shown, hidden or renamed: the owner's legend follows
    on_tap = Hook()  # a tap on the plot, not on a glyph (the marker on Android)

    def __init__(self, colors: dict[str, tuple], scales: dict[str, float],
                 viewport_seconds: int = 60, show_value_labels: bool = True,
                 show_timestamps: bool = True, sample_rate: float = 0.0,
                 max_points: int = 0, bipolar: bool = False,
                 auto_scale: bool = False, grid_step: float = 20.0,
                 graph_id: str = "", names: dict[str, str] | None = None,
                 **kwargs) -> None:
        super().__init__(**kwargs)
        self._colors: dict[str, tuple] = colors
        self._scales: dict[str, float] = scales
        # Stable identity for per-graph persistence (graph_series_<graph_id>)
        # and friendly labels for the series picker / legends.
        self._graph_id: str = graph_id
        self._names: dict[str, str] = dict(names or {})  # its own: a rename never reaches another graph
        self._bipolar: bool = bipolar
        self._auto_scale: bool = auto_scale
        self._grid_step: float = grid_step
        self._markers: list[int] = []
        self._drawing_enabled: bool = True
        self._line_width: float = 1.2
        self._sample_rate: float = sample_rate if sample_rate > 0 else (1.0 / APP.UPDATE_FREQUENCY)
        effective_max = max_points if max_points > 0 else APP.GRAPH_POINTS_MAX
        self._viewport_points: int = int(viewport_seconds * self._sample_rate)
        self._data: dict[str, deque] = {
            key: deque(maxlen=effective_max) for key in colors
        }
        self._visible: dict[str, bool] = dict.fromkeys(colors, True)
        self._appended: dict[str, int] = dict.fromkeys(colors, 0)  # samples ever added: a run's absolute position
        self._run_extremes: dict[str, RunExtremes] = {}
        self._gradient_steps: list[tuple[int, str]] = []  # (first point, series): drawn from there in LINE_COLOURS
        self._scroll_offset: int = 0
        self._total_points: int = 0
        self._show_value_labels: bool = show_value_labels
        self._show_timestamps: bool = show_timestamps
        self._default_viewport: int = self._viewport_points
        self._min_viewport: int = max(4, int(self._sample_rate * 2))  # min 2 seconds
        self._max_viewport: int = effective_max  # max = full buffer
        self._zoom_factor: float = 1.3  # each step zooms by 30%
        self._init_gestures()
        # Sync group: linked graphs zoom together
        self._sync_group: list["ScrollableGraphWidget"] = []
        self._threshold_value: Optional[float] = None
        self._threshold_steps: Optional[list[tuple[int, float]]] = None
        # Reference line: solid horizontal line at a fixed value, drawn
        # distinctly from the (dashed) threshold line. Used on the metrics
        # graph to mark level 100 — the per-metric maximum.
        self._reference_value: Optional[float] = None
        self._start_wall_time: Optional[float] = None
        self._init_glyphs()
        self._pads: tuple[float, float, float, float] = (dp(30), dp(30), dp(20), dp(6))  # left, right, bottom, top
        self._pads_floor: tuple[float, float, float, float] | None = None  # the widest since the data was (re)loaded
        self._fit_restore: tuple[int, int] | None = None  # while the whole data is shown: (width, scroll) to go back to
        self._redraw_cost: float = 0.0  # the last redraw's duration and end (perf_counter): the data redraw budget
        self._redraw_end: float = 0.0
        self._deferred_redraw = None  # the one pending Clock event of a data redraw waiting for its budget
        self._gfx: InstructionGroup = InstructionGroup()
        self.canvas.add(self._gfx)
        self.bind(size=self._redraw, pos=self._redraw)
        TC.add_listener(self._redraw)
        F.add_listener(self._redraw)  # its labels, and the margins they take
        LINE_COLOURS.add_listener(self._on_line_colours)
        # Bind Window scroll for zoom (bypasses ScrollView interception)
        Window.bind(on_mouse_down=self._on_window_mouse_down)

    def set_threshold(self, value: Optional[float]) -> None:
        """Set a horizontal threshold line."""
        self._threshold_value = value
        self._redraw()

    def set_threshold_steps(self, steps) -> None:
        """Piecewise threshold [(start_tick, value), ...] (sorted by tick).

        Pass None to clear and fall back to the single-value threshold.
        """
        self._threshold_steps = list(steps) if steps else None
        self._redraw()

    @property
    def threshold_steps(self) -> list[tuple[int, float]] | None:
        """The threshold line's steps, or None when it is one value."""
        return list(self._threshold_steps) if self._threshold_steps else None

    def set_reference_line(self, value: Optional[float]) -> None:
        """Set a solid horizontal reference line at `value` (graph units).

        Drawn distinctly from the dashed threshold line. Pass None to clear.
        """
        self._reference_value = value
        self._redraw()

    def _on_line_colours(self) -> None:
        if self._gradient_steps:
            self._redraw()

    def set_gradient_series(self, key: str | None) -> None:
        """Draw `key` coloured by its value in the profile's line colours (LINE_COLOURS) over the whole graph; a key that
        is no series of this graph (None, a program session's "program") colours none."""
        self.set_gradient_steps([(0, key)] if key in self._data else None)

    def set_gradient_steps(self, steps) -> None:
        """[(first point, series), ...]: each series in the gradient from its point to the next step's, the series each
        point was scored on (a program's segment by segment), so a later step recolours none drawn before it."""
        steps = [(start, key) for start, key in steps] if steps else []
        if steps != self._gradient_steps:
            self._gradient_steps = steps
            self._redraw()

    @property
    def gradient_steps(self) -> list[tuple[int, str]]:
        return list(self._gradient_steps)


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
        if metric in self._visible and self._visible[metric] != visible:  # each change redraws the graph and legend
            self._visible[metric] = visible
            self._redraw()
            self.on_series_change()

    def is_visible(self, metric: str) -> bool:
        return self._visible.get(metric, False)

    def visible_keys(self) -> list[str]:
        return [k for k, v in self._visible.items() if v]

    def series_keys(self) -> list[str]:
        """All series this graph can plot (the catalog set at construction)."""
        return list(self._data.keys())

    @property
    def graph_id(self) -> str:
        return self._graph_id

    def series_name(self, key: str) -> str:
        """Friendly label for a series — explicit `names` map, else prettified key."""
        return self._names.get(key) or key.replace("_score", "").replace("_", " ").title()

    def set_series_name(self, key: str, name: str) -> None:
        """Override a series' friendly label at runtime (custom-formula renames)."""
        if self.series_name(key) == name:  # as set_visible: only a change redraws the graph and its legend
            return
        self._names[key] = name
        self._redraw()
        self.on_series_change()

    def series_color(self, key: str) -> tuple:
        return TC.resolve(self._colors.get(key, (1, 1, 1, 1)))

    def set_scroll_offset(self, offset: int) -> None:
        self._scroll_offset = max(0, min(offset, self.max_scroll))
        self._redraw()

    def set_start_wall_time(self, epoch: Optional[float]) -> None:
        """Set the session start wall-clock time (epoch seconds) for real-time labels."""
        self._start_wall_time = epoch
        self._redraw()

    def add_point(self, values: dict[str, float], threshold: float | None = None, scored: str | None = None) -> None:
        """Append one point; `threshold` is the one in force at it, and a change steps the threshold line there; `scored`
        is the series it was scored on, drawn in the gradient from there."""
        for key in self._data:
            val = values.get(key, 0.0)
            self._data[key].append(val)
            self._appended[key] += 1
        first_key = next(iter(self._data))
        self._total_points = len(self._data[first_key])
        if threshold is not None:
            steps = self._threshold_steps or []
            extend_steps(steps, self._total_points - 1, threshold)
            self._threshold_steps = steps
        if scored is not None:
            extend_steps(self._gradient_steps, self._total_points - 1, scored)
        self._follow_fit()
        self._redraw_for_data()

    def add_points_batch(self, key: str, values: list[float]) -> None:
        """Add multiple points for a single series without per-point redraw."""
        if key not in self._data:
            return
        for val in values:
            self._data[key].append(val)
        self._appended[key] += len(values)
        first_key = next(iter(self._data))
        self._total_points = len(self._data[first_key])
        self._follow_fit()
        self._redraw_for_data()

    def load_static_data(self, series: dict[str, list[float]], new_session: bool = True) -> None:
        """Load pre-recorded data for static display (e.g. diary preview); a live session's reload is the same one."""
        for key in self._data:
            d = self._data[key]
            d.clear()
            # extend() is a C-level bulk copy; a Python `for v: append(v)` loop
            # over 30k raw-EEG samples used to take ~1.5 s on Android and
            # contributed to a post-resume ANR after a screen-lock session.
            d.extend(series.get(key, []))
            self._appended[key] = len(series.get(key, []))
        self._run_extremes.clear()
        first_key = next(iter(self._data))
        self._total_points = len(self._data[first_key])
        self._scroll_offset = 0
        self._markers = []
        if new_session:
            self._new_data()
        else:
            self._follow_fit()
        self._redraw()

    def _make_text_texture(self, text: str, size: float = 10, color: tuple = (1, 1, 1, 1)):
        """Render text to a texture for canvas drawing; `size` in dp at the normal text size."""
        font_size = F.px(size)
        key = (text, font_size, tuple(color))
        cl = _LABEL_CACHE.get(key)
        if cl is None:
            cl = CoreLabel(text=text, font_size=font_size, color=color)
            cl.refresh()
            _LABEL_CACHE[key] = cl
            if len(_LABEL_CACHE) > _LABEL_CACHE_MAX:
                _LABEL_CACHE.popitem(last=False)
        else:
            _LABEL_CACHE.move_to_end(key)
        return cl.texture

    def set_drawing_enabled(self, enabled: bool) -> None:
        """Owners that detach a graph pause its drawing; data still accrues and is drawn once it is shown again."""
        self._drawing_enabled = enabled
        if enabled:
            self._redraw()

    def _redraw_for_data(self) -> None:
        """New points: redraw now, or once the last redraw's cost fits the budget (one deferred redraw at most)."""
        if self._redraw_cost < _SLOW_REDRAW_S:
            self._redraw()
            return
        wait = self._redraw_end + self._redraw_cost / _REDRAW_BUDGET - _time.perf_counter()
        if wait <= 0:
            self._redraw()
        elif self._deferred_redraw is None:
            self._deferred_redraw = Clock.schedule_once(self._redraw, wait)

    def _redraw(self, *args) -> None:
        if self._deferred_redraw is not None:  # this redraw shows the data the deferred one waited to draw
            self._deferred_redraw.cancel()
            self._deferred_redraw = None
        if not self._drawing_enabled:
            return
        t0 = _time.perf_counter()
        try:
            self._draw()
        finally:
            self._redraw_end = _time.perf_counter()
            self._redraw_cost = self._redraw_end - t0
            render_stats.STATS.record_redraw(self._graph_id, self._redraw_cost)

    def _draw(self) -> None:
        self._gfx.clear()
        if self.width < 10 or self.height < 10:
            return
        start_idx, end_idx, slices = self._visible_slices()
        max_scale = self._y_scale(slices)
        pads = self._label_pads(max_scale, slices)
        if self._pads_floor is not None:  # margins only grow: a label gaining a digit must not shift the plot back
            pads = tuple(max(a, b) for a, b in zip(pads, self._pads_floor))
        self._pads = self._pads_floor = pads
        rect = self._plot_rect()
        if rect[2] < 10 or rect[3] < 10:
            return
        # Background
        self._gfx.add(Color(*TC.GRAPH_BG))
        self._gfx.add(Rectangle(pos=(self.x, self.y), size=(self.width, self.height)))
        self._draw_y_axis(rect, max_scale)
        # Border
        self._gfx.add(Color(*TC.GRAPH_BORDER))
        self._gfx.add(Line(rectangle=rect, width=1))
        self._draw_threshold(rect, max_scale, start_idx, end_idx)
        if end_idx > start_idx:
            self._draw_x_axis(rect, start_idx, end_idx)
            self._draw_lines(rect, max_scale, start_idx, slices)
            self._draw_markers(rect, start_idx, end_idx)
        self._draw_glyphs()

    def _visible_slices(self) -> tuple[int, int, dict[str, list[float]]]:
        """The visible window's start and end sample and each shown series' samples in it."""
        end_idx = self._total_points - self._scroll_offset
        start_idx = max(0, end_idx - self._viewport_points)
        slices = {key: list(data)[start_idx:end_idx] for key, data in self._data.items()
                  if self._visible.get(key, True)}
        return start_idx, end_idx, slices

    def _y_scale(self, slices: dict[str, list[float]]) -> float:
        """The value at the top of the plot: the visible data's peak with headroom, or the series' fixed scales."""
        if self._auto_scale:
            max_scale = 0.0
            for slice_vals in slices.values():
                if slice_vals:
                    peak = max(max(slice_vals), -min(slice_vals)) if self._bipolar else max(slice_vals)
                    max_scale = max(max_scale, peak)
            if max_scale < 1.0:
                max_scale = 100.0
            max_scale *= 1.1
        else:
            max_scale = 100.0
            for key in self._data:
                max_scale = max(max_scale, self._scales.get(key, 100.0))
        return max_scale

    def _draw_y_axis(self, rect: tuple[float, float, float, float], max_scale: float) -> None:
        """The horizontal grid lines and their value labels."""
        graph_x, graph_y, graph_w, graph_h = rect
        if self._bipolar:
            num_grid_lines = 4
            for i in range(num_grid_lines + 1):
                frac = i / num_grid_lines
                y_pos = graph_y + graph_h * frac
                self._gfx.add(Color(*TC.GRAPH_GRID))
                self._gfx.add(Line(points=[graph_x, y_pos, graph_x + graph_w, y_pos], width=0.5))
                if self._show_value_labels:
                    val = max_scale * (frac * 2.0 - 1.0)
                    tex = self._make_text_texture(f"{val:.0f}", size=8,
                                                  color=(0.5, 0.5, 0.5, 1))
                    self._gfx.add(Color(*TC.TEXT))
                    self._gfx.add(Rectangle(
                        texture=tex,
                        pos=(graph_x - tex.width - dp(4), y_pos - tex.height / 2),
                        size=tex.size,
                    ))
        else:
            fixed = not self._auto_scale and max_scale / self._grid_step <= _MAX_Y_GRID_LINES
            step = self._grid_step if fixed else self._compute_nice_step(max_scale)
            val = 0.0
            while val <= max_scale:
                frac = val / max_scale if max_scale > 0 else 0
                y_pos = graph_y + graph_h * frac
                self._gfx.add(Color(*TC.GRAPH_GRID))
                self._gfx.add(Line(points=[graph_x, y_pos, graph_x + graph_w, y_pos], width=0.5))
                if self._show_value_labels:
                    tex = self._make_text_texture(f"{val:.0f}", size=8,
                                                  color=(0.5, 0.5, 0.5, 1))
                    self._gfx.add(Color(*TC.TEXT))
                    self._gfx.add(Rectangle(
                        texture=tex,
                        pos=(graph_x - tex.width - dp(4), y_pos - tex.height / 2),
                        size=tex.size,
                    ))
                val += step

    def _draw_threshold(self, rect: tuple[float, float, float, float], max_scale: float, start_idx: int,
                        end_idx: int) -> None:
        """The threshold (its steps, or one dashed value and its label) and the reference line over it."""
        graph_x, graph_y, graph_w, graph_h = rect
        # Threshold line (piecewise steps take precedence over a single value)
        if self._threshold_steps and not self._bipolar:
            self._draw_threshold_steps(rect, max_scale, start_idx, end_idx)
        elif self._threshold_value is not None and not self._bipolar:
            frac_t = min(max(self._threshold_value, 0.0) / max_scale, 1.0) if max_scale > 0 else 0.0
            y_thresh = graph_y + frac_t * graph_h
            self._gfx.add(Color(*TC.THRESHOLD_LINE))
            self._add_dashed_hline(graph_x, graph_x + graph_w, y_thresh)
            if self._show_value_labels:
                tex = self._make_text_texture(
                    f"{self._threshold_value:.0f}", size=8,
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

    def _draw_x_axis(self, rect: tuple[float, float, float, float], start_idx: int, end_idx: int) -> None:
        """The vertical grid lines with their elapsed and wall-clock time labels."""
        graph_x, graph_y, graph_w, graph_h = rect
        if self._show_timestamps:
            n_visible = end_idx - start_idx
            vp = max(self._viewport_points, n_visible)
            x_off = vp - n_visible

            t_start = start_idx / self._sample_rate
            t_end = end_idx / self._sample_rate
            grid_sec = _x_grid_step(graph_w, vp / self._sample_rate)
            # First grid line at nearest grid boundary >= t_start
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
                    tex = self._make_text_texture(elapsed_clock(t_mark), size=8,
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
                        tex2 = self._make_text_texture(wall_str, size=7,
                                                       color=(0.4, 0.6, 0.4, 1))
                        self._gfx.add(Color(*TC.TEXT))
                        self._gfx.add(Rectangle(
                            texture=tex2,
                            pos=(x_pos - tex2.width / 2,
                                 graph_y - tex.height - tex2.height - dp(3)),
                            size=tex2.size,
                        ))
                t_mark += grid_sec

    def _draw_lines(self, rect: tuple[float, float, float, float], max_scale: float, start_idx: int,
                    slices: dict[str, list[float]]) -> None:
        """Each series' line and its end value label; the scored parts last, so no series hides them."""
        graph_x, graph_y, graph_w, graph_h = rect
        label_y_positions: list[float] = []
        scored_parts: list[tuple[list[float], tuple, float]] = []
        colour_by_value = not self._bipolar and LINE_COLOURS.name != MONO
        for key, slice_data in slices.items():
            if len(slice_data) < 2:
                continue

            color = self.series_color(key)
            scale = self._scales.get(key, 100.0)
            draw_scale = max_scale if not self._bipolar else scale

            n = len(slice_data)
            vp = max(self._viewport_points, n)
            x_offset = vp - n
            span = max(vp - 1, 1)

            # (x, y) once per drawn point: a run's min and max once runs span part of the stroke, whatever the zoom.
            drawn = self._drawn_indices(key, slice_data, start_idx, span / graph_w)
            xy: list[tuple[float, float]] = []
            for i in drawn:  # _y_of inline: a call per drawn point costs a slow phone's redraw budget
                val = slice_data[i]
                x = graph_x + ((x_offset + i) / span) * graph_w
                if self._bipolar:
                    norm = (val / draw_scale + 1.0) * 0.5
                    y = graph_y + max(0.0, min(norm, 1.0)) * graph_h
                else:
                    y = graph_y + min(max(val, 0.0) / draw_scale, 1.0) * graph_h
                xy.append((x, y))

            for scored, part in _split_at_spans(drawn, xy, self._gradient_spans(key, start_idx, start_idx + n)):
                points = [coord for x, y in part for coord in (x, y)]
                if scored:
                    scored_parts.append((points, color, draw_scale))
                else:
                    self._add_polyline(points, color)

            if self._show_value_labels and slice_data:
                self._draw_end_label(rect, slice_data[-1], draw_scale, color, label_y_positions)
        for points, color, draw_scale in scored_parts:
            if colour_by_value:
                self._add_gradient_line(points, graph_y, graph_h, draw_scale)
            else:
                self._add_polyline(points, color)

    def _y_of(self, val: float, draw_scale: float, graph_y: float, graph_h: float) -> float:
        """Where a value sits on the plot: around the middle for a bipolar graph, from the floor otherwise; clamped."""
        if self._bipolar:
            norm = (val / draw_scale + 1.0) * 0.5
            return graph_y + max(0.0, min(norm, 1.0)) * graph_h
        return graph_y + min(max(val, 0.0) / draw_scale, 1.0) * graph_h

    def _draw_end_label(self, rect: tuple[float, float, float, float], last_val: float, draw_scale: float,
                        color: tuple, taken: list[float]) -> None:
        """A line's latest value at the plot's right edge, in the nearest slot no other end label has taken."""
        graph_x, graph_y, graph_w, graph_h = rect
        last_y = _free_label_y(self._y_of(last_val, draw_scale, graph_y, graph_h), taken, graph_y, self.top - dp(6))
        taken.append(last_y)
        tex = self._make_text_texture(f"{last_val:.0f}", size=9, color=color)
        self._gfx.add(Color(*TC.TEXT))
        self._gfx.add(Rectangle(texture=tex, pos=(graph_x + graph_w + dp(3), last_y - tex.height / 2), size=tex.size))

    def _draw_markers(self, rect: tuple[float, float, float, float], start_idx: int, end_idx: int) -> None:
        """The session markers' vertical lines."""
        graph_x, graph_y, graph_w, graph_h = rect
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

    def _drawn_indices(self, key: str, values: list[float], start_idx: int, per_px: float) -> range | list[int]:
        """Indices into values to draw: every one, or each run's min and max and the series' two ends."""
        stroke = 2 * dp(self._line_width)  # Kivy Line width is the half-thickness
        return run_indices(values, per_px, stroke,
                           lambda: self._appended[key] - len(self._data[key]) + start_idx,  # values[0]'s index
                           lambda size: self._kept_runs(key, size))

    def _kept_runs(self, key: str, size: int) -> RunExtremes:
        kept = self._run_extremes.get(key)
        if kept is None or kept.size != size:  # one run size per series: a new zoom drops the last one's
            kept = self._run_extremes[key] = RunExtremes(size)
        return kept

    def _gradient_spans(self, key: str, first: int, end: int) -> list[tuple[int, int]]:
        """The [a, b) runs, counted from `first`, of the points first..end that `key` is drawn in the gradient."""
        steps = self._gradient_steps
        spans = []
        for j, (start, k) in enumerate(steps):
            stop = steps[j + 1][0] if j + 1 < len(steps) else end
            a, b = max(start, first), min(stop, end)
            if k == key and a < b:
                spans.append((a - first, b - first))
        return spans

    def _add_polyline(self, points: list[float], color) -> None:
        if color is None or len(points) < 4:
            return
        self._gfx.add(Color(*color))
        width = dp(self._line_width)
        max_coords = 1024  # 512 points × 2 coords each
        for start in range(0, max(len(points) - 2, 1), max_coords - 2):
            chunk = points[start:start + max_coords]
            if len(chunk) >= 4:
                self._gfx.add(Line(points=chunk, width=width))

    def _add_gradient_line(self, points: list[float], graph_y: float, graph_h: float, draw_scale: float) -> None:
        """Color by value in one Mesh (one draw call per frame): each vertex samples the gradient at its height."""
        hw = dp(self._line_width)  # Kivy Line width is the half-thickness of the stroke
        v_scale = (draw_scale / GRADIENT_TOP) / graph_h  # texture v (0 at value 0, 1 at GRADIENT_TOP) per pixel
        v_off = -graph_y * v_scale
        verts: list[float] = []
        ext = verts.extend
        n = len(points) // 2
        for i in range(n):
            x, y = points[2 * i], points[2 * i + 1]
            lo, hi = (y - hw) * v_scale + v_off, (y + hw) * v_scale + v_off
            # Square patch at the vertex: fills the notch two segment quads leave at a turn.
            ext((x - hw, y - hw, 0.5, lo, x + hw, y - hw, 0.5, lo, x + hw, y + hw, 0.5, hi, x - hw, y + hw, 0.5, hi))
            if i + 1 < n:
                x2, y2 = points[2 * i + 2], points[2 * i + 3]
                k = hw / (math.hypot(x2 - x, y2 - y) or 1.0)
                nx, ny = (y - y2) * k, (x2 - x) * k
                ext((x + nx, y + ny, 0.5, (y + ny) * v_scale + v_off, x2 + nx, y2 + ny, 0.5, (y2 + ny) * v_scale + v_off,
                     x2 - nx, y2 - ny, 0.5, (y2 - ny) * v_scale + v_off, x - nx, y - ny, 0.5, (y - ny) * v_scale + v_off))
        self._gfx.add(Color(1, 1, 1, 1))
        quads = len(verts) // 16
        for first in range(0, quads, _MESH_MAX_QUADS):
            count = min(_MESH_MAX_QUADS, quads - first)
            self._gfx.add(Mesh(
                vertices=verts[first * 16:(first + count) * 16],
                indices=[b + o for b in range(0, 4 * count, 4) for o in (0, 1, 2, 2, 3, 0)],
                mode="triangles",
                texture=gradient_texture(LINE_COLOURS.name, tuple(TC.GRAPH_BG)),
            ))

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

    def _draw_threshold_steps(self, rect: tuple[float, float, float, float], max_scale: float, start_idx: int,
                              end_idx: int) -> None:
        """Draw one dashed horizontal run per step over its visible tick range."""
        graph_x, graph_y, graph_w, graph_h = rect
        steps = self._threshold_steps
        if not steps or max_scale <= 0:
            return
        n = max(end_idx - start_idx, 0)
        vp = max(self._viewport_points, n)
        x_offset = vp - n

        def tick_to_x(tick: float) -> float:
            i = tick - start_idx
            x = graph_x + ((x_offset + i) / max(vp - 1, 1)) * graph_w
            return min(max(x, graph_x), graph_x + graph_w)

        for k, (step_tick, value) in enumerate(steps):
            next_tick = steps[k + 1][0] if k + 1 < len(steps) else float("inf")
            seg_start = max(step_tick, start_idx)
            seg_end = min(next_tick, end_idx)
            if seg_end <= seg_start:
                continue
            x_left = tick_to_x(seg_start)
            x_right = tick_to_x(seg_end)
            if x_right <= x_left:
                continue
            frac = min(max(value, 0.0) / max_scale, 1.0)  # on the graph's floor and ceiling, as its values are
            y = graph_y + frac * graph_h
            self._gfx.add(Color(*TC.THRESHOLD_LINE))
            self._add_dashed_hline(x_left, x_right, y)
            if self._show_value_labels:
                tex = self._make_text_texture(
                    f"{value:.0f}", size=8, color=(1.0, 0.4, 0.2, 1),
                )
                self._gfx.add(Color(*TC.TEXT))
                self._gfx.add(Rectangle(
                    texture=tex,
                    pos=(x_right - tex.width, y + dp(2) if y + dp(2) + tex.height <= self.top else y - dp(2) - tex.height),
                    size=tex.size,
                ))

    def _add_dashed_hline(self, x0: float, x1: float, y: float) -> None:
        """A dashed horizontal line from x0 to x1 at y, in the colour already set."""
        dash_w, gap_w = dp(6), dp(4)
        x_cur = x0
        while x_cur < x1:
            x_end = min(x_cur + dash_w, x1)
            self._gfx.add(Line(points=[x_cur, y, x_end, y], width=1))
            x_cur = x_end + gap_w

    @staticmethod
    def link_zoom(*graphs: "ScrollableGraphWidget") -> None:
        """Link graphs so zooming one zooms all. Each graph keeps its own
        sample rate but they share the same time-window duration."""
        group = list(graphs)
        for g in group:
            g._sync_group = [other for other in group if other is not g]
        if group:  # one window from the start: each graph's own default would differ until a zoom
            group[0]._set_viewport(group[0]._viewport_points)

    def _apply_viewport(self, points: int) -> None:
        self._viewport_points = max(self._min_viewport, min(points, self._max_viewport))
        self._scroll_offset = max(0, min(self._scroll_offset, self.max_scroll))

    def _set_viewport(self, points: int, _from_sync: bool = False) -> None:
        """Set viewport size (horizontal zoom), clamped to min/max; a zoom ends a fit."""
        self._fit_restore = None
        self._apply_viewport(points)
        self._redraw()
        # Propagate the requested window (each graph clamps it to its own limits: raw EEG holds a minute)
        if not _from_sync and self._sync_group:
            duration = points / self._sample_rate
            for other in self._sync_group:
                other_points = int(duration * other._sample_rate)
                other._set_viewport(other_points, _from_sync=True)

    @property
    def fitted(self) -> bool:
        return self._fit_restore is not None

    @property
    def zoom_points(self) -> int:
        """The zoom window, fitted or not: the one to save."""
        return self._fit_restore[0] if self._fit_restore is not None else self._viewport_points

    def toggle_fit(self) -> None:
        """Fit this graph and the ones linked with it, which keep one time scale, or send them all back to their windows."""
        group = [self, *self._sync_group]
        fitted = not any(g.fitted for g in group)
        for g in group:
            g.set_fitted(fitted)

    @property
    def zoom_seconds(self) -> float:
        return self.zoom_points / self._sample_rate

    def set_zoom_seconds(self, seconds: float) -> None:
        self._set_viewport(int(seconds * self._sample_rate))

    def _new_data(self) -> None:
        """Another session's data: the fit (if on) shows it whole and the margins start from its labels."""
        self._follow_fit(new_session=True)
        self._pads_floor = None

    def _follow_fit(self, new_session: bool = False) -> None:
        """While fitted, the window is all the data, at least the default window; back after another session lands at its end."""
        if self._fit_restore is None:
            return
        if new_session:
            self._fit_restore = (self._fit_restore[0], 0)
        self._apply_viewport(max(self._total_points, self._default_viewport))
        self._scroll_offset = 0

    def set_fitted(self, fitted: bool) -> None:
        """Show the whole of the data, or the window shown before it; the linked graphs keep their own."""
        if fitted:
            if self._fit_restore is None:
                self._fit_restore = (self._viewport_points, self._scroll_offset)
            self._follow_fit()
        elif self._fit_restore is not None:
            (width, offset), self._fit_restore = self._fit_restore, None
            self._apply_viewport(width)
            self._scroll_offset = max(0, min(offset, self.max_scroll))
        self._redraw()

    def _zoom_base(self) -> float:
        """The window a zoom starts from: while fitted, the group's widest fitted span, not this graph's own capped one."""
        fitted = [g for g in (self, *self._sync_group) if g.fitted]
        if not fitted:
            return self._viewport_points
        return max(g._viewport_points / g._sample_rate for g in fitted) * self._sample_rate

    def zoom_in(self) -> None:
        """Zoom in (show fewer points = more detail)."""
        self._set_viewport(int(self._zoom_base() / self._zoom_factor))

    def zoom_out(self) -> None:
        """Zoom out (show more points = wider view)."""
        self._set_viewport(int(self._zoom_base() * self._zoom_factor))

    def _plot_rect(self) -> tuple[float, float, float, float]:
        """The plot area (x, y, w, h): the widget less the margins its labels took at the last draw."""
        left, right, bottom, top = self._pads
        return self.x + left, self.y + bottom, self.width - left - right, self.height - bottom - top

    def _label_pads(self, max_scale: float, slices: dict[str, list[float]]) -> tuple[float, float, float, float]:
        """(left, right, bottom, top): what the labels need — the axis, the line ends and threshold, the time rows."""
        gap = dp(4)
        if self._show_value_labels:
            axis = f"{-max_scale:.0f}" if self._bipolar else f"{max_scale:.0f}"
            axis_w = self._make_text_texture(axis, size=8, color=(0.5, 0.5, 0.5, 1)).width
            left = axis_w + gap + dp(2)
            ends = [self._make_text_texture(f"{v[-1]:.0f}", size=9, color=self.series_color(k)).width
                    for k, v in slices.items() if v]
            if self._threshold_value is not None and not self._threshold_steps and not self._bipolar:
                ends.append(self._make_text_texture(f"{self._threshold_value:.0f}", size=8,
                                                    color=(1.0, 0.4, 0.2, 1)).width)
            right = max([axis_w, *ends]) + gap + dp(3)
            top = self._make_text_texture("0", size=8, color=(0.5, 0.5, 0.5, 1)).height / 2 + dp(2)
        else:
            left = right = top = gap
        bottom = gap
        if self._show_timestamps:  # a time mark at either edge centres its label on it: half of one past the plot
            half = self._make_text_texture("0:00:00", size=8, color=(0.5, 0.5, 0.5, 1)).width / 2
            left, right = max(left, half), max(right, half)
            bottom += self._make_text_texture("0:00", size=8, color=(0.5, 0.5, 0.5, 1)).height + dp(2)
            if self._start_wall_time is not None:
                bottom += self._make_text_texture("00:00:00", size=7, color=(0.4, 0.6, 0.4, 1)).height + dp(1)
        return left, right, bottom, top

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
            self._appended[key] = 0
        self._run_extremes.clear()
        self._total_points = 0
        self._scroll_offset = 0
        self._markers = []
        self._gradient_steps = []
        self._new_data()
        self._redraw()


def _split_at_spans(indices, xy: list[tuple[float, float]], spans: list[tuple[int, int]]) -> list[tuple[bool, list]]:
    """(in a span, points) runs of the drawn points; each run also takes the next one's first point, so the line is
    unbroken where its colouring changes."""
    if not spans:
        return [(False, xy)]
    runs: list[tuple[bool, list]] = []
    for i, point in zip(indices, xy):
        inside = any(a <= i < b for a, b in spans)
        if runs and runs[-1][0] == inside:
            runs[-1][1].append(point)
            continue
        if runs:
            runs[-1][1].append(point)
        runs.append((inside, [point]))
    return runs
