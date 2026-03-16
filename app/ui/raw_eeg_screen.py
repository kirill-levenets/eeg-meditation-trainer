from collections import deque
from typing import Dict, List, Optional

from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, InstructionGroup, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.slider import Slider
from kivy.uix.widget import Widget

from app.config import APP


class ScrollableGraphWidget(Widget):
    """Scrollable real-time graph with a 5-minute data buffer.

    Features: Y-axis scale numbers, horizontal grid lines, realtime value
    labels at line endpoints, X-axis timestamps. Text rendered via CoreLabel
    textures on canvas.
    """

    def __init__(self, colors: Dict[str, tuple], scales: Dict[str, float],
                 viewport_seconds: int = 60, show_value_labels: bool = True,
                 show_timestamps: bool = True, sample_rate: float = 0.0,
                 max_points: int = 0, bipolar: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self._colors: Dict[str, tuple] = colors
        self._scales: Dict[str, float] = scales
        self._bipolar: bool = bipolar
        self._line_width: float = 1.2
        self._sample_rate: float = sample_rate if sample_rate > 0 else (1.0 / APP.UPDATE_FREQUENCY)
        effective_max = max_points if max_points > 0 else APP.GRAPH_POINTS_MAX
        self._viewport_points: int = int(viewport_seconds * self._sample_rate)
        self._data: Dict[str, deque] = {
            key: deque(maxlen=effective_max) for key in colors
        }
        self._visible: Dict[str, bool] = {key: True for key in colors}
        self._scroll_offset: int = 0
        self._total_points: int = 0
        self._show_value_labels: bool = show_value_labels
        self._show_timestamps: bool = show_timestamps
        self._touch_start_x: float = 0.0
        self._touch_start_offset: int = 0
        self._threshold_value: Optional[float] = None
        self._threshold_scale_key: Optional[str] = None
        self._gfx: InstructionGroup = InstructionGroup()
        self.canvas.add(self._gfx)
        self.bind(size=self._redraw, pos=self._redraw)

    def set_threshold(self, value: Optional[float], scale_key: Optional[str] = None) -> None:
        """Set a horizontal threshold line. scale_key picks which series scale to use."""
        self._threshold_value = value
        self._threshold_scale_key = scale_key
        self._redraw()

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

    def add_point(self, values: Dict[str, float]) -> None:
        for key in self._data:
            val = values.get(key, 0.0)
            self._data[key].append(val)
        first_key = next(iter(self._data))
        self._total_points = len(self._data[first_key])
        self._redraw()

    def add_points_batch(self, key: str, values: List[float]) -> None:
        """Add multiple points for a single series without per-point redraw."""
        if key not in self._data:
            return
        for val in values:
            self._data[key].append(val)
        first_key = next(iter(self._data))
        self._total_points = len(self._data[first_key])
        self._redraw()

    def load_static_data(self, series: Dict[str, List[float]]) -> None:
        """Load pre-recorded data for static display (e.g. diary preview)."""
        for key in self._data:
            self._data[key].clear()
            for val in series.get(key, []):
                self._data[key].append(val)
        first_key = next(iter(self._data))
        self._total_points = len(self._data[first_key])
        self._scroll_offset = 0
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
        pad_bottom = dp(28) if self._show_timestamps else dp(10)
        pad_top = dp(10)
        pad_right = dp(60) if self._show_value_labels else dp(10)

        graph_x = self.x + pad_left
        graph_y = self.y + pad_bottom
        graph_w = self.width - pad_left - pad_right
        graph_h = self.height - pad_bottom - pad_top

        if graph_w < 10 or graph_h < 10:
            return

        # Background
        self._gfx.add(Color(0.08, 0.08, 0.12, 1.0))
        self._gfx.add(Rectangle(pos=(self.x, self.y), size=(self.width, self.height)))

        # Compute visible slice
        end_idx = self._total_points - self._scroll_offset
        start_idx = max(0, end_idx - self._viewport_points)

        # Y-axis scale (use max scale across visible metrics)
        max_scale = 100.0
        for key in self._data:
            if self._visible.get(key, True):
                max_scale = max(max_scale, self._scales.get(key, 100.0))

        # Grid lines + Y-axis labels
        num_grid_lines = 4
        self._gfx.add(Color(0.25, 0.25, 0.3, 1.0))
        for i in range(num_grid_lines + 1):
            frac = i / num_grid_lines
            y_pos = graph_y + graph_h * frac
            self._gfx.add(Line(points=[graph_x, y_pos, graph_x + graph_w, y_pos], width=0.5))
            if self._show_value_labels:
                if self._bipolar:
                    val = max_scale * (frac * 2.0 - 1.0)
                else:
                    val = max_scale * frac
                tex = self._make_text_texture(f"{val:.0f}", font_size=8,
                                              color=(0.5, 0.5, 0.5, 1))
                self._gfx.add(Color(1, 1, 1, 1))
                self._gfx.add(Rectangle(
                    texture=tex,
                    pos=(graph_x - tex.width - dp(4), y_pos - tex.height / 2),
                    size=tex.size,
                ))

        # Border
        self._gfx.add(Color(0.35, 0.35, 0.4, 1.0))
        self._gfx.add(Line(rectangle=(graph_x, graph_y, graph_w, graph_h), width=1))

        # Threshold line
        if self._threshold_value is not None and not self._bipolar:
            t_scale = max_scale
            if self._threshold_scale_key and self._threshold_scale_key in self._scales:
                t_scale = self._scales[self._threshold_scale_key]
            frac_t = min(self._threshold_value / t_scale, 1.0)
            y_thresh = graph_y + frac_t * graph_h
            self._gfx.add(Color(1.0, 0.4, 0.2, 0.8))
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
                self._gfx.add(Color(1, 1, 1, 1))
                self._gfx.add(Rectangle(
                    texture=tex,
                    pos=(graph_x + graph_w + dp(3), y_thresh - tex.height / 2),
                    size=tex.size,
                ))

        if end_idx <= start_idx:
            return

        # X-axis timestamps
        if self._show_timestamps:
            num_time_labels = min(5, end_idx - start_idx)
            if num_time_labels > 1:
                for i in range(num_time_labels):
                    frac = i / (num_time_labels - 1)
                    idx = start_idx + int(frac * (end_idx - start_idx - 1))
                    t_sec = idx / self._sample_rate
                    mins = int(t_sec) // 60
                    secs = int(t_sec) % 60
                    time_str = f"{mins}:{secs:02d}"
                    tex = self._make_text_texture(time_str, font_size=8,
                                                  color=(0.5, 0.5, 0.5, 1))
                    x_pos = graph_x + frac * graph_w
                    self._gfx.add(Color(1, 1, 1, 1))
                    self._gfx.add(Rectangle(
                        texture=tex,
                        pos=(x_pos - tex.width / 2, graph_y - tex.height - dp(2)),
                        size=tex.size,
                    ))

        # Data lines + endpoint value labels
        label_y_positions: List[float] = []
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
            self._gfx.add(Color(*color))

            points = []
            n = len(slice_data)
            vp = max(self._viewport_points, n)
            x_offset = vp - n
            for i, val in enumerate(slice_data):
                x = graph_x + ((x_offset + i) / max(vp - 1, 1)) * graph_w
                if self._bipolar:
                    norm = (val / draw_scale + 1.0) * 0.5
                    y = graph_y + max(0.0, min(norm, 1.0)) * graph_h
                else:
                    y = graph_y + min(max(val, 0.0) / draw_scale, 1.0) * graph_h
                points.extend([x, y])

            if len(points) >= 4:
                self._gfx.add(Line(points=points, width=dp(self._line_width)))

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
                self._gfx.add(Color(1, 1, 1, 1))
                self._gfx.add(Rectangle(
                    texture=tex,
                    pos=(graph_x + graph_w + dp(3), last_y - tex.height / 2),
                    size=tex.size,
                ))

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            touch.grab(self)
            self._touch_start_x = touch.x
            self._touch_start_offset = self._scroll_offset
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            graph_w = self.width - dp(58) - dp(60)
            if graph_w > 0 and self._total_points > self._viewport_points:
                dx = touch.x - self._touch_start_x
                points_per_pixel = self._viewport_points / graph_w
                delta_points = int(-dx * points_per_pixel)
                new_offset = self._touch_start_offset + delta_points
                self.set_scroll_offset(new_offset)
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            return True
        return super().on_touch_up(touch)

    def clear_data(self) -> None:
        for key in self._data:
            self._data[key].clear()
        self._total_points = 0
        self._scroll_offset = 0
        self._redraw()


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
            size_hint_y=0.35,
        )
        root.add_widget(self._band_graph)

        # Band legend
        band_legend = BoxLayout(size_hint_y=None, height=dp(20), spacing=dp(2))
        for band, color in self.BAND_COLORS.items():
            lbl = Label(text=band, font_size=dp(9), color=color)
            band_legend.add_widget(lbl)
        root.add_widget(band_legend)

        # --- Time scroll slider ---
        scroll_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        scroll_label = Label(text="Time Scroll:", font_size=dp(12), size_hint_x=0.2)
        self._scroll_slider = Slider(
            min=0, max=1, value=0, step=1, size_hint_x=0.6,
        )
        self._scroll_time_label = Label(text="Live", font_size=dp(12), size_hint_x=0.2)
        self._scroll_slider.bind(value=self._on_scroll)
        scroll_row.add_widget(scroll_label)
        scroll_row.add_widget(self._scroll_slider)
        scroll_row.add_widget(self._scroll_time_label)
        root.add_widget(scroll_row)

        self.add_widget(root)

    @property
    def raw_graph(self) -> ScrollableGraphWidget:
        return self._raw_graph

    @property
    def band_graph(self) -> ScrollableGraphWidget:
        return self._band_graph

    def add_raw_sample(self, sample: Dict[str, float]) -> None:
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
        self._update_scroll_range()

    def _update_scroll_range(self) -> None:
        max_scroll = self._raw_graph.max_scroll
        self._scroll_slider.max = max(1, max_scroll)
        if self._scroll_slider.value == 0:
            self._scroll_time_label.text = "Live"

    def _on_scroll(self, instance, value) -> None:
        offset = int(self._scroll_slider.max - value)
        self._raw_graph.set_scroll_offset(offset)
        # Scale offset for band graph (different sample rate)
        band_offset = int(offset / self.EEG_WAVEFORM_RATE * (1.0 / APP.UPDATE_FREQUENCY))
        self._band_graph.set_scroll_offset(band_offset)
        if offset == 0:
            self._scroll_time_label.text = "Live"
        else:
            secs_back = offset / self.EEG_WAVEFORM_RATE
            mins = int(secs_back) // 60
            secs = int(secs_back) % 60
            self._scroll_time_label.text = f"-{mins}:{secs:02d}"


if __name__ == "__main__":
    print("RawEEGScreen module loaded OK")
