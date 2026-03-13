from collections import deque
from typing import Dict

from kivy.graphics import Color, Line
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.slider import Slider
from kivy.uix.widget import Widget

from app.config import APP


class ScrollableGraphWidget(Widget):
    """Scrollable real-time graph with a 5-minute data buffer.

    Displays data within a visible time window that can be scrolled
    via an external slider. The full buffer holds GRAPH_POINTS_MAX points
    (5 min at 2 Hz = 600). The viewport shows `viewport_points` at a time.
    """

    def __init__(self, colors: Dict[str, tuple], scales: Dict[str, float],
                 viewport_seconds: int = 60, **kwargs) -> None:
        super().__init__(**kwargs)
        self._colors: Dict[str, tuple] = colors
        self._scales: Dict[str, float] = scales
        self._viewport_points: int = int(viewport_seconds / APP.UPDATE_FREQUENCY)
        self._data: Dict[str, deque] = {
            key: deque(maxlen=APP.GRAPH_POINTS_MAX) for key in colors
        }
        self._visible: Dict[str, bool] = {key: True for key in colors}
        self._scroll_offset: int = 0  # 0 = latest data visible (right edge)
        self._total_points: int = 0
        self.bind(size=self._redraw, pos=self._redraw)

    @property
    def total_points(self) -> int:
        return self._total_points

    @property
    def viewport_points(self) -> int:
        return self._viewport_points

    @property
    def max_scroll(self) -> int:
        return max(0, self._total_points - self._viewport_points)

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

    def _redraw(self, *args) -> None:
        self.canvas.after.clear()
        if self.width < 10 or self.height < 10:
            return

        pad_left = dp(40)
        pad_bottom = dp(20)
        pad_top = dp(10)
        pad_right = dp(10)

        graph_x = self.x + pad_left
        graph_y = self.y + pad_bottom
        graph_w = self.width - pad_left - pad_right
        graph_h = self.height - pad_bottom - pad_top

        # Compute visible slice
        end_idx = self._total_points - self._scroll_offset
        start_idx = max(0, end_idx - self._viewport_points)
        if end_idx <= start_idx:
            return

        with self.canvas.after:
            # Grid
            Color(0.3, 0.3, 0.3, 1.0)
            Line(rectangle=(graph_x, graph_y, graph_w, graph_h), width=1)
            for i in range(5):
                y_pos = graph_y + graph_h * i / 4
                Line(points=[graph_x, y_pos, graph_x + graph_w, y_pos], width=0.5)

            # Data lines
            for key, data in self._data.items():
                if not self._visible.get(key, True):
                    continue
                data_list = list(data)
                slice_data = data_list[start_idx:end_idx]
                if len(slice_data) < 2:
                    continue

                color = self._colors[key]
                scale = self._scales.get(key, 100.0)
                Color(*color)

                points = []
                n = len(slice_data)
                for i, val in enumerate(slice_data):
                    x = graph_x + (i / max(n - 1, 1)) * graph_w
                    y = graph_y + min(max(val, 0.0) / scale, 1.0) * graph_h
                    points.extend([x, y])

                if len(points) >= 4:
                    Line(points=points, width=dp(1.2))

            # Time labels
            Color(0.5, 0.5, 0.5, 1.0)
            start_sec = start_idx * APP.UPDATE_FREQUENCY
            end_sec = end_idx * APP.UPDATE_FREQUENCY

    def clear_data(self) -> None:
        for key in self._data:
            self._data[key].clear()
        self._total_points = 0
        self._scroll_offset = 0
        self._redraw()


class RawEEGScreen(Screen):
    """Screen displaying raw EEG data and frequency band plots."""

    RAW_COLORS = {
        "delta": (0.4, 0.2, 0.8, 1.0),
        "theta": (0.2, 0.5, 0.9, 1.0),
        "alpha1": (0.1, 0.8, 0.4, 1.0),
        "alpha2": (0.2, 0.9, 0.5, 1.0),
        "beta1": (0.9, 0.7, 0.1, 1.0),
        "beta2": (0.9, 0.8, 0.2, 1.0),
        "gamma1": (1.0, 0.3, 0.3, 1.0),
        "gamma2": (1.0, 0.4, 0.4, 1.0),
    }

    RAW_SCALES = {
        "delta": 800.0,
        "theta": 600.0,
        "alpha1": 800.0,
        "alpha2": 800.0,
        "beta1": 400.0,
        "beta2": 400.0,
        "gamma1": 200.0,
        "gamma2": 200.0,
    }

    BAND_COLORS = {
        "alpha": (0.1, 0.8, 0.4, 1.0),
        "beta": (0.9, 0.7, 0.1, 1.0),
        "gamma": (1.0, 0.3, 0.3, 1.0),
        "theta": (0.2, 0.5, 0.9, 1.0),
        "delta": (0.4, 0.2, 0.8, 1.0),
    }

    BAND_SCALES = {
        "alpha": 1600.0,
        "beta": 800.0,
        "gamma": 400.0,
        "theta": 600.0,
        "delta": 800.0,
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

        # --- Raw sub-bands graph ---
        raw_label = Label(
            text="Sub-bands (raw amplitudes)",
            font_size=dp(12),
            size_hint_y=None,
            height=dp(20),
            color=(0.6, 0.6, 0.6, 1.0),
        )
        root.add_widget(raw_label)

        self._raw_graph = ScrollableGraphWidget(
            colors=self.RAW_COLORS,
            scales=self.RAW_SCALES,
            viewport_seconds=60,
            size_hint_y=0.35,
        )
        root.add_widget(self._raw_graph)

        # Raw legend
        raw_legend = BoxLayout(size_hint_y=None, height=dp(20), spacing=dp(2))
        for band, color in self.RAW_COLORS.items():
            lbl = Label(text=band, font_size=dp(9), color=color)
            raw_legend.add_widget(lbl)
        root.add_widget(raw_legend)

        # --- Aggregated bands graph ---
        band_label = Label(
            text="Frequency Bands (aggregated)",
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
        """Add raw EEG sub-band data point."""
        self._raw_graph.add_point(sample)
        # Also compute aggregated bands
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
        self._band_graph.set_scroll_offset(offset)
        if offset == 0:
            self._scroll_time_label.text = "Live"
        else:
            secs_back = offset * APP.UPDATE_FREQUENCY
            mins = int(secs_back) // 60
            secs = int(secs_back) % 60
            self._scroll_time_label.text = f"-{mins}:{secs:02d}"


if __name__ == "__main__":
    print("RawEEGScreen module loaded OK")
