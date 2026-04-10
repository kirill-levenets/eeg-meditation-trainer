from typing import Dict

from kivy.clock import Clock
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen

from app.ui.raw_eeg_screen import RawEEGScreen, ScrollableGraphWidget
from app.ui.theme import C, F, S, Card, Icons, StyledButton


# Band colors/scales for inline raw EEG view
_BAND_COLORS = {
    "alpha": (0.15, 0.75, 0.45, 1.0),
    "beta": (0.85, 0.70, 0.15, 1.0),
    "gamma": (0.90, 0.35, 0.35, 1.0),
    "theta": (0.25, 0.55, 0.85, 1.0),
    "delta": (0.45, 0.25, 0.75, 1.0),
}

_RAW_SIGNAL_COLORS = {"eeg": C.MEDITATION}
_RAW_SIGNAL_SCALES = {"eeg": 500.0}
_RAW_WAVEFORM_RATE = 512.0
_RAW_WAVEFORM_MAX = 512 * 60

METRICS_COLORS = {
    "shamatha_score": C.SHAMATHA,
    "distraction": C.DISTRACTION,
    "sinking": C.SINKING,
    "subtle_distraction": C.SUBTLE,
    "native_attention": C.ATTENTION,
    "native_meditation": C.MEDITATION,
    "custom_formula": C.CUSTOM,
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
        C.add_listener(self._refresh_theme)

    def _build_ui(self) -> None:
        float_root = FloatLayout()

        # Screen background
        self._root = BoxLayout(orientation="vertical", padding=S.PAGE_PAD, spacing=S.GAP_SM,
                               size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        root = self._root
        with root.canvas.before:
            Color(*C.BG)
            self._root_bg = Rectangle(size=root.size, pos=root.pos)
        root.bind(
            size=lambda w, v: setattr(self._root_bg, "size", v),
            pos=lambda w, v: setattr(self._root_bg, "pos", v),
        )

        # ── Header ──
        header = BoxLayout(size_hint_y=None, height=S.NAV_H, spacing=S.GAP)
        self._device_label = Label(
            text="[Mock EEG]",
            size_hint_x=0.25,
            color=C.DEVICE_IDLE,
            font_size=F.BODY,
        )
        timer_box = BoxLayout(orientation="vertical", size_hint_x=0.25)
        self._start_time_label = Label(
            text="",
            font_size=F.TINY,
            color=C.TEXT_MUTED,
            size_hint_y=0.4,
        )
        self._timer_label = Label(
            text="00:00",
            font_size=dp(18),
            bold=True,
            color=C.TEXT,
            size_hint_y=0.6,
        )
        timer_box.add_widget(self._start_time_label)
        timer_box.add_widget(self._timer_label)
        self._state_label = Label(
            text="IDLE",
            size_hint_x=0.5,
            font_size=F.H3,
            color=C.TEXT_SECONDARY,
        )
        header.add_widget(self._device_label)
        header.add_widget(timer_box)
        header.add_widget(self._state_label)
        root.add_widget(header)

        # ── Alert banner ──
        self._alert_label = Label(
            text="",
            size_hint_y=None,
            height=dp(0),
            font_size=F.SMALL,
            color=C.WARM,
            halign="center",
        )
        self._alert_label.bind(size=self._alert_label.setter("text_size"))
        root.add_widget(self._alert_label)

        # ── View toggle: Metrics / Raw EEG ──
        view_toggle = BoxLayout(size_hint_y=None, height=dp(28), spacing=S.GAP_SM)
        self._btn_view_metrics = StyledButton(
            text="Metrics", bg_color=C.PRIMARY, height=dp(28),
            font_size=F.SMALL,
        )
        self._btn_view_raw = StyledButton(
            text="Raw EEG", bg_color=C.BG_CARD, height=dp(28),
            font_size=F.SMALL, text_color=C.TEXT_SECONDARY,
        )
        self._btn_view_metrics.bind(on_release=lambda *a: self._set_view("metrics"))
        self._btn_view_raw.bind(on_release=lambda *a: self._set_view("raw"))
        view_toggle.add_widget(self._btn_view_metrics)
        view_toggle.add_widget(self._btn_view_raw)
        root.add_widget(view_toggle)

        # ── Metrics view (default) ──
        self._metrics_container = BoxLayout(orientation="vertical", spacing=S.GAP_SM)

        self._graph = ScrollableGraphWidget(
            colors=METRICS_COLORS,
            scales=METRICS_SCALES,
            viewport_seconds=60,
            size_hint_y=1,
        )
        self._metrics_container.add_widget(self._graph)

        legend = BoxLayout(size_hint_y=None, height=dp(18), spacing=S.GAP_SM)
        for metric, color in METRICS_COLORS.items():
            short = metric.replace("_score", "").replace("_", " ").title()
            lbl = Label(text=short, font_size=F.TINY, color=color)
            legend.add_widget(lbl)
        self._metrics_container.add_widget(legend)

        # ── Raw EEG view (hidden initially) ──
        self._raw_container = BoxLayout(orientation="vertical", spacing=S.GAP_SM)

        self._raw_graph = ScrollableGraphWidget(
            colors=_RAW_SIGNAL_COLORS,
            scales=_RAW_SIGNAL_SCALES,
            viewport_seconds=10,
            show_value_labels=True,
            show_timestamps=True,
            sample_rate=_RAW_WAVEFORM_RATE,
            max_points=_RAW_WAVEFORM_MAX,
            bipolar=True,
            size_hint_y=0.5,
        )
        self._raw_container.add_widget(self._raw_graph)

        self._band_graph = ScrollableGraphWidget(
            colors=_BAND_COLORS,
            scales=RawEEGScreen.BAND_SCALES,
            viewport_seconds=60,
            show_value_labels=True,
            show_timestamps=True,
            auto_scale=True,
            size_hint_y=0.5,
        )
        self._raw_container.add_widget(self._band_graph)

        band_legend = BoxLayout(size_hint_y=None, height=dp(18), spacing=S.GAP_SM)
        for band, color in _BAND_COLORS.items():
            band_legend.add_widget(Label(text=band, font_size=F.TINY, color=color))
        self._raw_container.add_widget(band_legend)

        # Graph area holder — swaps between metrics and raw views
        self._graph_area = BoxLayout(size_hint_y=0.45)
        self._graph_area.add_widget(self._metrics_container)
        self._active_view = "metrics"
        root.add_widget(self._graph_area)

        # ── Stats row ──
        stats_card = Card(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(56),
            bg_color=C.BG_CARD,
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
                text=title, font_size=F.TINY, color=C.TEXT_MUTED,
                size_hint_y=0.4,
            )
            value_lbl = Label(
                text="0", font_size=F.H2, bold=True,
                color=C.TEXT,
                size_hint_y=0.6,
            )
            box.add_widget(title_lbl)
            box.add_widget(value_lbl)
            self._stat_labels[key] = value_lbl
            stats_card.add_widget(box)
        root.add_widget(stats_card)

        # ── Controls ──
        controls = BoxLayout(
            size_hint_y=None, height=S.BTN_H + dp(4),
            spacing=S.GAP, padding=[S.GAP, 0],
        )
        self._btn_start = StyledButton(
            text="Start", icon=Icons.PLAY, bg_color=C.ACCENT,
            bg_pressed=C.ACCENT_DIM,
        )
        self._btn_pause = StyledButton(
            text="Pause", icon=Icons.PAUSE, bg_color=C.WARM,
            bg_pressed=C.WARM_DIM, disabled=True,
        )
        self._btn_stop = StyledButton(
            text="Stop", icon=Icons.STOP, bg_color=C.DANGER,
            bg_pressed=C.DANGER_DIM, disabled=True,
        )
        self._btn_marker = StyledButton(
            text="Mark", icon=Icons.MARKER, bg_color=C.PURPLE,
            bg_pressed=C.PURPLE_DIM, disabled=True,
        )
        controls.add_widget(self._btn_start)
        controls.add_widget(self._btn_pause)
        controls.add_widget(self._btn_stop)
        controls.add_widget(self._btn_marker)
        root.add_widget(controls)

        float_root.add_widget(root)

        # ── Connection overlay ──
        self._overlay = BoxLayout(
            orientation="vertical",
            size_hint=(1, 1),
            pos_hint={"x": 0, "y": 0},
            padding=dp(40),
            spacing=S.GAP_LG,
        )
        with self._overlay.canvas.before:
            Color(*C.BG_OVERLAY)
            self._overlay_bg = Rectangle(size=self._overlay.size, pos=self._overlay.pos)
        self._overlay.bind(
            size=lambda w, v: setattr(self._overlay_bg, "size", v),
            pos=lambda w, v: setattr(self._overlay_bg, "pos", v),
        )

        self._overlay.add_widget(BoxLayout(size_hint_y=1))

        self._overlay_status = Label(
            text="",
            font_size=F.H1,
            color=C.TEXT,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(80),
        )
        self._overlay_status.bind(size=self._overlay_status.setter("text_size"))
        self._overlay.add_widget(self._overlay_status)

        self._overlay_dots = Label(
            text="",
            font_size=dp(24),
            color=C.PRIMARY,
            size_hint_y=None,
            height=dp(30),
        )
        self._overlay.add_widget(self._overlay_dots)

        self._overlay_cancel_btn = StyledButton(
            text="Cancel",
            size_hint=(0.4, None),
            height=S.BTN_H,
            pos_hint={"center_x": 0.5},
            bg_color=C.DANGER,
            bg_pressed=C.DANGER_DIM,
        )
        self._overlay.add_widget(self._overlay_cancel_btn)

        self._overlay_retry_btn = StyledButton(
            text="Retry",
            size_hint=(0.4, None),
            height=S.BTN_H,
            pos_hint={"center_x": 0.5},
            bg_color=C.PRIMARY,
            bg_pressed=C.PRIMARY_DIM,
            opacity=0,
            disabled=True,
        )
        self._overlay.add_widget(self._overlay_retry_btn)

        self._overlay.add_widget(BoxLayout(size_hint_y=1))

        self._overlay.opacity = 0
        self._overlay.size_hint = (0, 0)
        self._overlay.size = (0, 0)
        self._dot_event = None
        self._dot_count = 0
        float_root.add_widget(self._overlay)

        self.add_widget(float_root)

    def _set_view(self, view: str) -> None:
        """Switch between 'metrics' and 'raw' graph views."""
        if view == self._active_view:
            return
        self._graph_area.clear_widgets()
        if view == "raw":
            self._graph_area.add_widget(self._raw_container)
            self._btn_view_raw.bg_color = C.PRIMARY
            self._btn_view_raw.text_color = C.TEXT
            self._btn_view_metrics.bg_color = C.BG_CARD
            self._btn_view_metrics.text_color = C.TEXT_SECONDARY
        else:
            self._graph_area.add_widget(self._metrics_container)
            self._btn_view_metrics.bg_color = C.PRIMARY
            self._btn_view_metrics.text_color = C.TEXT
            self._btn_view_raw.bg_color = C.BG_CARD
            self._btn_view_raw.text_color = C.TEXT_SECONDARY
        self._active_view = view

    @property
    def graph(self) -> ScrollableGraphWidget:
        return self._graph

    @property
    def raw_graph(self) -> ScrollableGraphWidget:
        return self._raw_graph

    @property
    def band_graph(self) -> ScrollableGraphWidget:
        return self._band_graph

    @property
    def btn_start(self) -> StyledButton:
        return self._btn_start

    @property
    def btn_pause(self) -> StyledButton:
        return self._btn_pause

    @property
    def btn_stop(self) -> StyledButton:
        return self._btn_stop

    @property
    def btn_marker(self) -> StyledButton:
        return self._btn_marker

    def add_raw_sample(self, sample: Dict[str, float]) -> None:
        """Feed raw EEG data to the embedded raw/band graphs."""
        waveform = sample.get("raw_eeg_waveform", [])
        if waveform:
            self._raw_graph.add_points_batch("eeg", waveform)
        else:
            eeg_sum = sum(
                sample.get(k, 0.0)
                for k in ("delta", "theta", "alpha1", "alpha2",
                          "beta1", "beta2", "gamma1", "gamma2")
            )
            self._raw_graph.add_point({"eeg": eeg_sum})

        alpha = sample.get("alpha1", 0.0) + sample.get("alpha2", 0.0)
        beta = sample.get("beta1", 0.0) + sample.get("beta2", 0.0)
        gamma = sample.get("gamma1", 0.0) + sample.get("gamma2", 0.0)
        self._band_graph.add_point({
            "alpha": alpha,
            "beta": beta,
            "gamma": gamma,
            "theta": sample.get("theta", 0.0),
            "delta": sample.get("delta", 0.0),
        })

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
            "Stable Focus": C.STATE_FOCUS,
            "Subtle Distraction": C.STATE_SUBTLE,
            "Gross Distraction": C.STATE_DISTRACTED,
            "Sinking": C.STATE_SINKING,
            "Neutral": C.STATE_NEUTRAL,
        }
        self._state_label.color = color_map.get(state, C.STATE_NEUTRAL)

    def update_stats(self, metrics: Dict[str, float]) -> None:
        for key, label in self._stat_labels.items():
            val = metrics.get(key, 0.0)
            label.text = f"{val:.0f}"

    def update_device_status(
        self, connected: bool, device_name: str = "", connecting: bool = False
    ) -> None:
        if connecting:
            name = device_name or "Device"
            self._device_label.text = f"[{name}] ..."
            self._device_label.color = C.CONNECTING
        elif connected:
            label = f"[{device_name}] *" if device_name else "[Mock EEG] *"
            self._device_label.text = label
            self._device_label.color = C.CONNECTED
        elif device_name:
            self._device_label.text = f"[{device_name}]"
            self._device_label.color = C.DEVICE_IDLE
        else:
            self._device_label.text = "[Disconnected]"
            self._device_label.color = C.DISCONNECTED

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
    def overlay_cancel_btn(self) -> StyledButton:
        return self._overlay_cancel_btn

    @property
    def overlay_retry_btn(self) -> StyledButton:
        return self._overlay_retry_btn

    def show_alert(self, text: str) -> None:
        """Show a warning banner below the header."""
        self._alert_label.text = text
        self._alert_label.height = dp(28)

    def hide_alert(self) -> None:
        self._alert_label.text = ""
        self._alert_label.height = dp(0)

    def reset_display(self) -> None:
        self._graph.clear_data()
        self._graph.set_start_wall_time(None)
        self._timer_label.text = "00:00"
        self._start_time_label.text = ""
        self._state_label.text = "IDLE"
        self._state_label.color = C.STATE_NEUTRAL
        self.hide_alert()
        self.hide_overlay()
        for label in self._stat_labels.values():
            label.text = "0"
        self.set_controls_idle()

    def _refresh_theme(self):
        """Update background and label colors when theme changes."""
        self._root.canvas.before.clear()
        with self._root.canvas.before:
            Color(*C.BG)
            self._root_bg = Rectangle(size=self._root.size, pos=self._root.pos)
        self._overlay.canvas.before.clear()
        with self._overlay.canvas.before:
            Color(*C.BG_OVERLAY)
            self._overlay_bg = Rectangle(size=self._overlay.size, pos=self._overlay.pos)
        # Update label colors
        self._device_label.color = C.DEVICE_IDLE
        self._start_time_label.color = C.TEXT_MUTED
        self._timer_label.color = C.TEXT
        self._state_label.color = C.STATE_NEUTRAL
        self._alert_label.color = C.WARM
        self._overlay_status.color = C.TEXT
        self._overlay_dots.color = C.PRIMARY
        for lbl in self._stat_labels.values():
            lbl.color = C.TEXT