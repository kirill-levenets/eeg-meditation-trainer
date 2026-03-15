from typing import Dict

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.slider import Slider

from app.config import APP
from app.ui.raw_eeg_screen import ScrollableGraphWidget


METRICS_COLORS = {
    "meditation_score": (0.2, 0.6, 1.0, 1.0),
    "shamatha_score": (0.0, 0.9, 0.4, 1.0),
    "distraction": (1.0, 0.3, 0.3, 1.0),
    "sinking": (0.8, 0.5, 0.0, 1.0),
    "subtle_distraction": (0.9, 0.9, 0.2, 1.0),
}

METRICS_SCALES = {
    "meditation_score": 200.0,
    "shamatha_score": 100.0,
    "distraction": 100.0,
    "sinking": 100.0,
    "subtle_distraction": 100.0,
}


class LiveSessionScreen(Screen):
    """Main session screen with graph, stats, and controls."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "live_session"
        self._build_ui()

    def _build_ui(self) -> None:
        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(4))

        header = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        self._device_label = Label(
            text="[Mock EEG]",
            size_hint_x=0.3,
            color=(0.5, 0.8, 1.0, 1.0),
            font_size=dp(13),
        )
        self._timer_label = Label(
            text="00:00",
            size_hint_x=0.2,
            font_size=dp(18),
            bold=True,
        )
        self._state_label = Label(
            text="IDLE",
            size_hint_x=0.5,
            font_size=dp(14),
            color=(0.8, 0.8, 0.8, 1.0),
        )
        header.add_widget(self._device_label)
        header.add_widget(self._timer_label)
        header.add_widget(self._state_label)
        root.add_widget(header)

        self._graph = ScrollableGraphWidget(
            colors=METRICS_COLORS,
            scales=METRICS_SCALES,
            viewport_seconds=60,
            size_hint_y=0.45,
        )
        root.add_widget(self._graph)

        legend = BoxLayout(size_hint_y=None, height=dp(24), spacing=dp(4))
        for metric, color in METRICS_COLORS.items():
            short = metric.replace("_score", "").replace("_", " ").title()
            lbl = Label(
                text=short,
                font_size=dp(10),
                color=color,
            )
            legend.add_widget(lbl)
        root.add_widget(legend)

        stats_grid = GridLayout(
            cols=4, size_hint_y=None, height=dp(60), spacing=dp(4), padding=dp(4)
        )
        self._stat_labels: Dict[str, Label] = {}
        stat_items = [
            ("meditation_score", "Meditation"),
            ("shamatha_score", "Shamatha"),
            ("distraction", "Distraction"),
            ("sinking", "Sinking"),
        ]
        for key, title in stat_items:
            box = BoxLayout(orientation="vertical")
            title_lbl = Label(
                text=title, font_size=dp(11), color=(0.7, 0.7, 0.7, 1.0),
                size_hint_y=0.4,
            )
            value_lbl = Label(
                text="0", font_size=dp(16), bold=True,
                size_hint_y=0.6,
            )
            box.add_widget(title_lbl)
            box.add_widget(value_lbl)
            self._stat_labels[key] = value_lbl
            stats_grid.add_widget(box)
        root.add_widget(stats_grid)

        controls = BoxLayout(
            size_hint_y=None, height=dp(50), spacing=dp(8), padding=[dp(16), 0]
        )
        self._btn_start = Button(
            text="Start",
            background_color=(0.2, 0.7, 0.3, 1.0),
            font_size=dp(15),
            bold=True,
        )
        self._btn_pause = Button(
            text="Pause",
            background_color=(0.8, 0.7, 0.2, 1.0),
            font_size=dp(15),
            bold=True,
            disabled=True,
        )
        self._btn_stop = Button(
            text="Stop",
            background_color=(0.8, 0.2, 0.2, 1.0),
            font_size=dp(15),
            bold=True,
            disabled=True,
        )
        controls.add_widget(self._btn_start)
        controls.add_widget(self._btn_pause)
        controls.add_widget(self._btn_stop)
        root.add_widget(controls)

        # --- Time scroll slider ---
        scroll_row = BoxLayout(size_hint_y=None, height=dp(32), spacing=dp(8))
        scroll_label = Label(text="Time:", font_size=dp(11), size_hint_x=0.15)
        self._scroll_slider = Slider(
            min=0, max=1, value=0, step=1, size_hint_x=0.65,
        )
        self._scroll_time_label = Label(
            text="Live", font_size=dp(11), size_hint_x=0.2,
        )
        self._scroll_slider.bind(value=self._on_scroll)
        scroll_row.add_widget(scroll_label)
        scroll_row.add_widget(self._scroll_slider)
        scroll_row.add_widget(self._scroll_time_label)
        root.add_widget(scroll_row)

        self.add_widget(root)

    @property
    def graph(self) -> ScrollableGraphWidget:
        return self._graph

    def update_scroll_range(self) -> None:
        max_scroll = self._graph.max_scroll
        self._scroll_slider.max = max(1, max_scroll)
        if self._scroll_slider.value == 0:
            self._scroll_time_label.text = "Live"

    def _on_scroll(self, instance, value) -> None:
        offset = int(self._scroll_slider.max - value)
        self._graph.set_scroll_offset(offset)
        if offset == 0:
            self._scroll_time_label.text = "Live"
        else:
            secs_back = offset * APP.UPDATE_FREQUENCY
            mins = int(secs_back) // 60
            secs = int(secs_back) % 60
            self._scroll_time_label.text = f"-{mins}:{secs:02d}"

    @property
    def btn_start(self) -> Button:
        return self._btn_start

    @property
    def btn_pause(self) -> Button:
        return self._btn_pause

    @property
    def btn_stop(self) -> Button:
        return self._btn_stop

    def update_timer(self, text: str) -> None:
        self._timer_label.text = text

    def update_state(self, state: str) -> None:
        self._state_label.text = state
        color_map = {
            "Stable Focus": (0.2, 0.9, 0.4, 1.0),
            "Subtle Distraction": (0.9, 0.9, 0.2, 1.0),
            "Gross Distraction": (1.0, 0.3, 0.3, 1.0),
            "Sinking": (0.8, 0.5, 0.0, 1.0),
            "Neutral": (0.7, 0.7, 0.7, 1.0),
        }
        self._state_label.color = color_map.get(state, (0.7, 0.7, 0.7, 1.0))

    def update_stats(self, metrics: Dict[str, float]) -> None:
        for key, label in self._stat_labels.items():
            val = metrics.get(key, 0.0)
            label.text = f"{val:.0f}"

    def update_device_status(self, connected: bool, device_name: str = "") -> None:
        if connected:
            label = f"[{device_name}] ●" if device_name else "[Mock EEG] ●"
            self._device_label.text = label
            self._device_label.color = (0.2, 0.9, 0.4, 1.0)
        else:
            self._device_label.text = "[Disconnected]"
            self._device_label.color = (0.8, 0.3, 0.3, 1.0)

    def set_controls_running(self) -> None:
        self._btn_start.disabled = True
        self._btn_pause.disabled = False
        self._btn_stop.disabled = False

    def set_controls_paused(self) -> None:
        self._btn_start.disabled = True
        self._btn_pause.text = "Resume"
        self._btn_pause.disabled = False
        self._btn_stop.disabled = False

    def set_controls_idle(self) -> None:
        self._btn_start.disabled = False
        self._btn_pause.disabled = True
        self._btn_pause.text = "Pause"
        self._btn_stop.disabled = True

    def reset_display(self) -> None:
        self._graph.clear_data()
        self._timer_label.text = "00:00"
        self._state_label.text = "IDLE"
        self._state_label.color = (0.7, 0.7, 0.7, 1.0)
        self._scroll_slider.value = 0
        self._scroll_time_label.text = "Live"
        for label in self._stat_labels.values():
            label.text = "0"
        self.set_controls_idle()
