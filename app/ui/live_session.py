from typing import Dict

from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen

from app.ui.raw_eeg_screen import ScrollableGraphWidget


METRICS_COLORS = {
    "shamatha_score": (0.0, 0.9, 0.4, 1.0),
    "distraction": (1.0, 0.3, 0.3, 1.0),
    "sinking": (0.8, 0.5, 0.0, 1.0),
    "subtle_distraction": (0.9, 0.9, 0.2, 1.0),
    "native_attention": (0.6, 0.3, 0.9, 1.0),
    "native_meditation": (0.3, 0.9, 0.9, 1.0),
    "custom_formula": (1.0, 0.4, 0.8, 1.0),
}

METRICS_SCALES = {
    "shamatha_score": 100.0,
    "distraction": 100.0,
    "sinking": 100.0,
    "subtle_distraction": 100.0,
    "native_attention": 100.0,
    "native_meditation": 100.0,
    "custom_formula": 200.0,
}


class LiveSessionScreen(Screen):
    """Main session screen with graph, stats, and controls."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "live_session"
        self._build_ui()

    def _build_ui(self) -> None:
        float_root = FloatLayout()
        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(4),
                         size_hint=(1, 1), pos_hint={"x": 0, "y": 0})

        header = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        self._device_label = Label(
            text="[Mock EEG]",
            size_hint_x=0.25,
            color=(0.5, 0.8, 1.0, 1.0),
            font_size=dp(13),
        )
        timer_box = BoxLayout(orientation="vertical", size_hint_x=0.25)
        self._start_time_label = Label(
            text="",
            font_size=dp(10),
            color=(0.5, 0.7, 0.5, 1.0),
            size_hint_y=0.4,
        )
        self._timer_label = Label(
            text="00:00",
            font_size=dp(18),
            bold=True,
            size_hint_y=0.6,
        )
        timer_box.add_widget(self._start_time_label)
        timer_box.add_widget(self._timer_label)
        self._state_label = Label(
            text="IDLE",
            size_hint_x=0.5,
            font_size=dp(14),
            color=(0.8, 0.8, 0.8, 1.0),
        )
        header.add_widget(self._device_label)
        header.add_widget(timer_box)
        header.add_widget(self._state_label)
        root.add_widget(header)

        self._alert_label = Label(
            text="",
            size_hint_y=None,
            height=dp(0),
            font_size=dp(12),
            color=(1.0, 0.4, 0.2, 1.0),
            halign="center",
        )
        self._alert_label.bind(size=self._alert_label.setter("text_size"))
        root.add_widget(self._alert_label)

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
            cols=5, size_hint_y=None, height=dp(60), spacing=dp(4), padding=dp(4)
        )
        self._stat_labels: Dict[str, Label] = {}
        stat_items = [
            ("shamatha_score", "Shamatha"),
            ("distraction", "Distraction"),
            ("sinking", "Sinking"),
            ("native_attention", "NS Attn"),
            ("native_meditation", "NS Med"),
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
        self._btn_marker = Button(
            text="Mark",
            background_color=(0.8, 0.2, 0.8, 1.0),
            font_size=dp(15),
            bold=True,
            disabled=True,
        )
        controls.add_widget(self._btn_start)
        controls.add_widget(self._btn_pause)
        controls.add_widget(self._btn_stop)
        controls.add_widget(self._btn_marker)
        root.add_widget(controls)

        float_root.add_widget(root)

        # --- Connection overlay ---
        self._overlay = BoxLayout(
            orientation="vertical",
            size_hint=(1, 1),
            pos_hint={"x": 0, "y": 0},
            padding=dp(40),
            spacing=dp(16),
        )
        with self._overlay.canvas.before:
            Color(0, 0, 0, 0.75)
            self._overlay_bg = Rectangle(size=self._overlay.size, pos=self._overlay.pos)
        self._overlay.bind(
            size=lambda w, v: setattr(self._overlay_bg, "size", v),
            pos=lambda w, v: setattr(self._overlay_bg, "pos", v),
        )

        # Spacer to push content to center
        self._overlay.add_widget(BoxLayout(size_hint_y=1))

        self._overlay_status = Label(
            text="",
            font_size=dp(18),
            color=(0.9, 0.9, 0.9, 1.0),
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(60),
        )
        self._overlay_status.bind(size=self._overlay_status.setter("text_size"))
        self._overlay.add_widget(self._overlay_status)

        self._overlay_dots = Label(
            text="",
            font_size=dp(24),
            color=(0.5, 0.8, 1.0, 1.0),
            size_hint_y=None,
            height=dp(30),
        )
        self._overlay.add_widget(self._overlay_dots)

        self._overlay_cancel_btn = Button(
            text="Cancel",
            size_hint=(0.4, None),
            height=dp(44),
            pos_hint={"center_x": 0.5},
            background_color=(0.6, 0.2, 0.2, 1.0),
            font_size=dp(14),
        )
        self._overlay.add_widget(self._overlay_cancel_btn)

        self._overlay_retry_btn = Button(
            text="Retry",
            size_hint=(0.4, None),
            height=dp(44),
            pos_hint={"center_x": 0.5},
            background_color=(0.2, 0.5, 0.7, 1.0),
            font_size=dp(14),
            opacity=0,
            disabled=True,
        )
        self._overlay.add_widget(self._overlay_retry_btn)

        # Bottom spacer
        self._overlay.add_widget(BoxLayout(size_hint_y=1))

        self._overlay.opacity = 0
        self._overlay.size_hint = (0, 0)
        self._overlay.size = (0, 0)
        self._dot_event = None
        self._dot_count = 0
        float_root.add_widget(self._overlay)

        self.add_widget(float_root)

    @property
    def graph(self) -> ScrollableGraphWidget:
        return self._graph

    @property
    def btn_start(self) -> Button:
        return self._btn_start

    @property
    def btn_pause(self) -> Button:
        return self._btn_pause

    @property
    def btn_stop(self) -> Button:
        return self._btn_stop

    @property
    def btn_marker(self) -> Button:
        return self._btn_marker

    def update_timer(self, text: str) -> None:
        self._timer_label.text = text

    def set_start_time(self, epoch: float) -> None:
        """Display session start wall-clock time and pass it to the graph."""
        import time
        lt = time.localtime(epoch)
        self._start_time_label.text = f"started {lt.tm_hour:02d}:{lt.tm_min:02d}:{lt.tm_sec:02d}"
        self._graph.set_start_wall_time(epoch)

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

    def update_device_status(
        self, connected: bool, device_name: str = "", connecting: bool = False
    ) -> None:
        if connecting:
            name = device_name or "Device"
            self._device_label.text = f"[{name}] Connecting..."
            self._device_label.color = (0.9, 0.8, 0.2, 1.0)
        elif connected:
            label = f"[{device_name}] *" if device_name else "[Mock EEG] *"
            self._device_label.text = label
            self._device_label.color = (0.2, 0.9, 0.4, 1.0)
        elif device_name:
            # Idle state with known device
            self._device_label.text = f"[{device_name}]"
            self._device_label.color = (0.5, 0.8, 1.0, 1.0)
        else:
            self._device_label.text = "[Disconnected]"
            self._device_label.color = (0.8, 0.3, 0.3, 1.0)

    def set_controls_running(self) -> None:
        self._btn_start.disabled = True
        self._btn_pause.text = "Pause"
        self._btn_pause.disabled = False
        self._btn_stop.disabled = False
        self._btn_marker.disabled = False

    def set_controls_paused(self) -> None:
        self._btn_start.disabled = True
        self._btn_pause.text = "Resume"
        self._btn_pause.disabled = False
        self._btn_stop.disabled = False
        self._btn_marker.disabled = True

    def set_controls_idle(self) -> None:
        self._btn_start.disabled = False
        self._btn_pause.disabled = True
        self._btn_pause.text = "Pause"
        self._btn_stop.disabled = True
        self._btn_marker.disabled = True

    def show_alert(self, text: str) -> None:
        """Show a warning banner below the header."""
        self._alert_label.text = text
        self._alert_label.height = dp(28)

    def hide_alert(self) -> None:
        self._alert_label.text = ""
        self._alert_label.height = dp(0)

    def show_overlay(self, text: str = "Connecting...") -> None:
        """Show semi-transparent connection overlay with animated dots."""
        self._overlay_status.text = text
        self._overlay.opacity = 1
        self._overlay.size_hint = (1, 1)
        self._overlay_retry_btn.opacity = 0
        self._overlay_retry_btn.disabled = True
        self._overlay_cancel_btn.text = "Cancel"
        self._dot_count = 0
        if self._dot_event:
            self._dot_event.cancel()
        self._dot_event = Clock.schedule_interval(self._animate_dots, 0.5)

    def update_overlay(self, text: str) -> None:
        """Update the overlay status text."""
        if self._overlay.opacity > 0:
            self._overlay_status.text = text

    def hide_overlay(self) -> None:
        """Hide the connection overlay and remove from touch chain."""
        self._overlay.opacity = 0
        self._overlay.size_hint = (0, 0)
        self._overlay.size = (0, 0)
        if self._dot_event:
            self._dot_event.cancel()
            self._dot_event = None
        self._overlay_dots.text = ""

    def show_overlay_retry(self, text: str) -> None:
        """Show failure state with Retry button."""
        self._overlay_status.text = text
        self._overlay_retry_btn.opacity = 1
        self._overlay_retry_btn.disabled = False
        self._overlay_cancel_btn.text = "Close"
        if self._dot_event:
            self._dot_event.cancel()
            self._dot_event = None
        self._overlay_dots.text = ""

    def _animate_dots(self, dt: float) -> None:
        self._dot_count = (self._dot_count + 1) % 4
        self._overlay_dots.text = ".  " * self._dot_count

    @property
    def overlay_cancel_btn(self) -> Button:
        return self._overlay_cancel_btn

    @property
    def overlay_retry_btn(self) -> Button:
        return self._overlay_retry_btn

    def reset_display(self) -> None:
        self._graph.clear_data()
        self._graph.set_start_wall_time(None)
        self._timer_label.text = "00:00"
        self._start_time_label.text = ""
        self._state_label.text = "IDLE"
        self._state_label.color = (0.7, 0.7, 0.7, 1.0)
        self.hide_alert()
        self.hide_overlay()
        for label in self._stat_labels.values():
            label.text = "0"
        self.set_controls_idle()
