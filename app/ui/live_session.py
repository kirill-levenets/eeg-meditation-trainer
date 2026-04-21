
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from app.ui.raw_eeg_screen import (
    GraphAwareScrollView,
    RawEEGScreen,
    ScrollableGraphWidget,
)
from app.ui.theme import (
    ICONS_AVAILABLE,
    C,
    Card,
    F,
    Icons,
    S,
    StyledButton,
    format_duration,
)

_DURATION_PRESETS = [
    ("5 min", 5),
    ("10 min", 10),
    ("15 min", 15),
    ("20 min", 20),
    ("Free", None),
]

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


def _compute_graph_height(viewport_h: float, floor_dp: float) -> float:
    """Return the height the graph area should take: fill the viewport, floor at floor_dp."""
    return max(viewport_h, floor_dp)


def _compute_graph_height_adaptive(
    viewport_h: float,
    stats_h: float,
    bottom_h: float,
    spacing: float,
    min_fixed_graph: float,
    min_graph_floor: float,
) -> float:
    """Pick graph height: fixed (fills leftover) if tall enough, else scroll-mode (fills viewport)."""
    fixed_graph = viewport_h - stats_h - bottom_h - spacing
    if fixed_graph >= min_fixed_graph:
        return max(fixed_graph, min_graph_floor)
    return max(viewport_h, min_graph_floor)


def _format_stats_slots(
    mode: str, metrics: dict, stats: dict
) -> tuple[list[str], list[str]]:
    """Return (titles, values) for the 5 bottom-row slots."""
    if mode == "aggregate":
        titles = ["Avg Sham", "Avg Med", ">Thresh", "\u226590", "Streak"]
        values = [
            f"{stats.get('avg_shamatha', 0.0):.1f}",
            f"{stats.get('avg_meditation', 0.0):.1f}",
            format_duration(int(stats.get("time_above_threshold", 0))),
            format_duration(int(stats.get("time_shamatha_90", 0))),
            format_duration(int(stats.get("longest_streak", 0))),
        ]
        return titles, values
    # live mode (default)
    titles = ["Shamatha", "Distraction", "Sinking", "NS Attn", "NS Med"]
    keys = ["shamatha_score", "distraction", "sinking", "native_attention", "native_meditation"]
    values = [str(int(round(metrics.get(k, 0)))) for k in keys]
    return titles, values


# Duration picker responsive sizing — below narrow threshold the button
# collapses to an icon-only pill so the Start button can claim the width.
_DURATION_PICKER_NARROW_THRESHOLD = dp(480)
_DURATION_PICKER_NARROW_WIDTH = dp(20)
_DURATION_PICKER_WIDE_WIDTH = dp(56)


def _duration_picker_label(
    window_w: float,
    timer_enabled: bool,
    timer_minutes: int,
    narrow_threshold: float,
) -> str:
    """Return the duration-picker button text, empty on narrow screens."""
    if window_w < narrow_threshold:
        return ""
    if not timer_enabled:
        return "\u221e"
    if timer_minutes >= 60 and timer_minutes % 60 == 0:
        return f"{timer_minutes // 60}h"
    return f"{timer_minutes}m"


def _duration_picker_width(window_w: float, narrow_threshold: float) -> float:
    """Return duration-picker button width (narrow = chevron only)."""
    return (
        _DURATION_PICKER_NARROW_WIDTH
        if window_w < narrow_threshold
        else _DURATION_PICKER_WIDE_WIDTH
    )


class LiveSessionScreen(Screen):
    """Main session screen with graph, stats, and controls."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "live_session"
        self._last_metrics: dict = {}
        self._build_ui()
        C.add_listener(self._refresh_theme)
        # Scroll height tracking is persistent (the widget itself lives for the screen's lifetime)
        self._scroll.bind(height=self._reflow)

    def on_enter(self, *args) -> None:
        from kivy.core.window import Window
        Window.bind(on_resize=self._reflow, on_rotate=self._reflow)
        self._reflow()

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
        header = BoxLayout(size_hint_y=None, height=dp(10), spacing=S.GAP_SM)
        self._device_label = Label(
            text="[Mock EEG]",
            size_hint_x=1 / 3,
            color=C.DEVICE_IDLE,
            font_size=F.SMALL,
        )
        self._timer_label = Label(
            text="00:00",
            size_hint_x=1 / 3,
            font_size=F.BODY,
            bold=True,
            color=C.TEXT,
        )
        # Deprecated alias kept so _refresh_theme and reset_display can reference it
        # without branching; both point to the same single label now.
        self._start_time_label = self._timer_label
        self._start_time_str: str = ""  # wall-clock string cached for combined display
        self._state_label = Label(
            text="IDLE",
            size_hint_x=1 / 3,
            font_size=F.BODY,
            color=C.TEXT_SECONDARY,
        )
        header.add_widget(self._device_label)
        header.add_widget(self._timer_label)
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

        self._legend = BoxLayout(size_hint_y=None, height=dp(18), spacing=S.GAP_SM)
        self._metrics_container.add_widget(self._legend)
        # Legend is populated by _rebuild_metric_legend; start with Shamatha only
        self._rebuild_metric_legend(["shamatha_score"])

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
        self._graph_area = BoxLayout(size_hint_y=None, height=dp(400))
        self._graph_area.add_widget(self._metrics_container)
        self._active_view = "metrics"

        # ── Stats row ──
        stats_card = Card(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(56),
            bg_color=C.BG_CARD,
        )
        self._stats_card = stats_card
        self._stat_labels: dict[str, Label] = {}
        stat_items = [
            ("shamatha_score", "Shamatha"),
            ("distraction", "Distraction"),
            ("sinking", "Sinking"),
            ("native_attention", "NS Attn"),
            ("native_meditation", "NS Med"),
        ]
        self._stat_title_labels: dict = {}
        self._stat_keys_in_order = [k for k, _ in stat_items]
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
            self._stat_title_labels[key] = title_lbl
            self._stat_labels[key] = value_lbl
            stats_card.add_widget(box)

        self._stats_mode = "live"
        toggle_box = BoxLayout(orientation="vertical", size_hint_x=None, width=dp(56))
        toggle_box.add_widget(Widget())  # spacer, matches title_lbl size_hint_y=0.4
        self._btn_stats_toggle = StyledButton(
            text="LIVE",
            size_hint_y=0.6,
            font_size=F.SMALL,
            bg_color=C.BG_CARD,
        )
        toggle_box.add_widget(self._btn_stats_toggle)
        self._btn_stats_toggle.bind(on_release=self._toggle_stats_mode)
        stats_card.add_widget(toggle_box)
        self._apply_stats_mode_styling()

        # Scrollable body: graph + stats
        self._scroll = GraphAwareScrollView(size_hint=(1, 1), do_scroll_x=False)
        self._body = BoxLayout(
            orientation="vertical",
            size_hint=(1, None),
            spacing=S.GAP_SM,
        )
        self._body.bind(minimum_height=self._body.setter("height"))
        self._body.add_widget(self._graph_area)
        self._body.add_widget(stats_card)
        self._scroll.add_widget(self._body)
        root.add_widget(self._scroll)

        # Current timer state cached for popup highlighting
        self._current_timer_enabled = False
        self._current_timer_minutes = 0
        self._duration_popup = None

        # ── Controls ──
        self._bottom_bar = BoxLayout(
            size_hint_y=None, height=S.BTN_H + dp(4),
            spacing=S.GAP, padding=[S.GAP, 0],
        )

        # Start + duration-picker form a visual cluster with a tiny separator
        self._btn_start = StyledButton(
            text="Start", icon=Icons.PLAY, bg_color=C.ACCENT,
            bg_pressed=C.ACCENT_DIM,
        )
        duration_kwargs = (
            {"icon": Icons.MENU_DOWN} if ICONS_AVAILABLE else {}
        )
        self._btn_duration_expand = StyledButton(
            text="\u221e",  # updated by refresh_duration_preset
            bg_color=C.ACCENT, bg_pressed=C.ACCENT_DIM,
            size_hint_x=None, width=_DURATION_PICKER_NARROW_WIDTH, font_size=F.BODY,
            **duration_kwargs,
        )
        self._btn_duration_expand.bind(on_release=self._open_duration_popup)
        start_cluster = BoxLayout(
            orientation="horizontal",
            spacing=dp(1),  # tiny separator
            size_hint_y=None, height=S.BTN_H,
        )
        start_cluster.add_widget(self._btn_start)
        start_cluster.add_widget(self._btn_duration_expand)

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
        self._bottom_bar.add_widget(start_cluster)
        self._bottom_bar.add_widget(self._btn_pause)
        self._bottom_bar.add_widget(self._btn_stop)
        self._bottom_bar.add_widget(self._btn_marker)
        self._body.add_widget(self._bottom_bar)

        float_root.add_widget(root)

        # ── Session summary overlay ──
        self._summary = BoxLayout(
            orientation="vertical",
            size_hint=(1, 1),
            pos_hint={"x": 0, "y": 0},
            padding=dp(20),
            spacing=S.GAP,
        )
        with self._summary.canvas.before:
            Color(*C.BG_OVERLAY)
            self._summary_bg = Rectangle(size=self._summary.size, pos=self._summary.pos)
        self._summary.bind(
            size=lambda w, v: setattr(self._summary_bg, "size", v),
            pos=lambda w, v: setattr(self._summary_bg, "pos", v),
        )

        self._summary.add_widget(BoxLayout(size_hint_y=0.1))  # top spacer

        self._summary_title = Label(
            text="Session Complete",
            font_size=F.H1,
            bold=True,
            color=C.ACCENT,
            size_hint_y=None,
            height=dp(32),
        )
        self._summary.add_widget(self._summary_title)

        # Stats card
        self._summary_stats_card = Card(
            orientation="vertical",
            size_hint_y=None,
            height=dp(144),
            bg_color=C.BG_CARD,
            spacing=S.GAP_SM,
        )
        self._summary_stats = {}
        for key, label_text in [
            ("duration", "Duration"),
            ("avg_shamatha", "Avg Shamatha"),
            ("avg_meditation", "Avg Meditation"),
            ("time_above", "Time Above Threshold"),
            ("time_shamatha_90", "Time Shamatha \u2265 90"),
        ]:
            row = BoxLayout(size_hint_y=None, height=dp(24))
            lbl = Label(
                text=label_text, font_size=F.BODY, color=C.TEXT_SECONDARY,
                halign="left", size_hint_x=0.6,
            )
            lbl.bind(size=lbl.setter("text_size"))
            val = Label(
                text="-", font_size=F.BODY, bold=True, color=C.TEXT,
                halign="right", size_hint_x=0.4,
            )
            val.bind(size=val.setter("text_size"))
            row.add_widget(lbl)
            row.add_widget(val)
            self._summary_stats_card.add_widget(row)
            self._summary_stats[key] = val
        self._summary.add_widget(self._summary_stats_card)

        # Quick notes
        notes_lbl = Label(
            text="Quick notes:", font_size=F.BODY, color=C.TEXT_SECONDARY,
            size_hint_y=None, height=dp(22), halign="left",
        )
        notes_lbl.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        self._summary.add_widget(notes_lbl)

        self._summary_notes = TextInput(
            hint_text="How was the session?",
            multiline=True,
            size_hint_y=None,
            height=dp(70),
            font_size=F.BODY,
            foreground_color=C.TEXT,
            background_color=list(C.BG_INPUT),
            cursor_color=C.PRIMARY,
        )
        self._summary.add_widget(self._summary_notes)

        # Buttons
        summary_btns = BoxLayout(size_hint_y=None, height=S.BTN_H, spacing=S.GAP)
        self._summary_save_btn = StyledButton(
            text="Save", icon=Icons.CHECK,
            bg_color=C.ACCENT, bg_pressed=C.ACCENT_DIM,
        )
        self._summary_history_btn = StyledButton(
            text="View in History", icon=Icons.HISTORY,
            bg_color=C.PRIMARY, bg_pressed=C.PRIMARY_DIM,
        )
        self._summary_close_btn = StyledButton(
            text="Close",
            bg_color=C.BG_CARD, text_color=C.TEXT_SECONDARY,
        )
        summary_btns.add_widget(self._summary_save_btn)
        summary_btns.add_widget(self._summary_history_btn)
        summary_btns.add_widget(self._summary_close_btn)
        self._summary.add_widget(summary_btns)

        self._summary.add_widget(BoxLayout(size_hint_y=0.1))  # bottom spacer

        self._summary.opacity = 0
        self._summary.size_hint = (0, 0)
        self._summary.size = (0, 0)
        self._summary_session_id = None
        float_root.add_widget(self._summary)

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
            font_size=F.BODY,
            color=C.TEXT,
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(100),
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

    def _reflow(self, *args) -> None:
        """Resize graph to fill viewport OR to leftover space if viewport is tall enough."""
        needed = ("_scroll", "_graph_area", "_stats_card", "_bottom_bar")
        if not all(hasattr(self, a) for a in needed):
            return
        # spacing between body's 3 children (graph, stats_card, bottom_bar) = 2 gaps
        spacing = S.GAP_SM * 2
        self._graph_area.height = _compute_graph_height_adaptive(
            viewport_h=self._scroll.height,
            stats_h=self._stats_card.height,
            bottom_h=self._bottom_bar.height,
            spacing=spacing,
            min_fixed_graph=dp(400),
            min_graph_floor=dp(240),
        )
        # Also refresh the duration-picker label so narrow-screen text drops away
        if hasattr(self, "_btn_duration_expand") and hasattr(self, "_current_timer_enabled"):
            try:
                self._apply_duration_picker_label()
            except Exception:
                pass

    def on_leave(self, *args) -> None:
        from kivy.core.window import Window
        try:
            Window.unbind(on_resize=self._reflow, on_rotate=self._reflow)
        except Exception:
            pass

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

    def _rebuild_metric_legend(self, enabled_keys: list) -> None:
        """Clear and re-populate the metrics legend with only the enabled metrics."""
        self._legend.clear_widgets()
        for metric, color in METRICS_COLORS.items():
            if metric not in enabled_keys:
                continue
            short = metric.replace("_score", "").replace("_", " ").title()
            lbl = Label(text=short, font_size=F.TINY, color=color)
            self._legend.add_widget(lbl)

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

    def add_raw_sample(self, sample: dict[str, float]) -> None:
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
        if self._start_time_str:
            self._timer_label.text = f"{self._start_time_str} · {text}"
        else:
            self._timer_label.text = text

    def set_start_time(self, epoch: float) -> None:
        """Cache session start wall-clock time, update combined timer, and pass to graph."""
        import time
        lt = time.localtime(epoch)
        self._start_time_str = f"{lt.tm_hour:02d}:{lt.tm_min:02d}"
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

    def update_stats(self, metrics: dict[str, float]) -> None:
        self._last_metrics = metrics
        stats = {}
        try:
            from kivy.app import App
            stats = App.get_running_app()._session_manager.compute_statistics()
        except Exception:
            pass
        self._render_stats(metrics, stats)

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
        self._btn_duration_expand.disabled = True
        self._btn_pause.text = "Pause"
        self._btn_pause.disabled = False
        self._btn_stop.disabled = False
        self._btn_marker.disabled = False

    def set_controls_paused(self) -> None:
        self._btn_start.disabled = True
        self._btn_duration_expand.disabled = True
        self._btn_pause.text = "Resume"
        self._btn_pause.disabled = False
        self._btn_stop.disabled = False
        self._btn_marker.disabled = True

    def set_controls_idle(self) -> None:
        self._btn_start.disabled = False
        self._btn_duration_expand.disabled = False
        self._btn_pause.disabled = True
        self._btn_pause.text = "Pause"
        self._btn_stop.disabled = True
        self._btn_marker.disabled = True

    # ── Duration preset hooks ──
    on_duration_preset = None  # set by AppManager; called with value (int or None)

    def _open_duration_popup(self, *_args) -> None:
        """Open a modal Popup to pick a session duration preset."""
        body = BoxLayout(orientation="vertical", spacing=S.GAP_SM, padding=S.GAP)
        for label, value in _DURATION_PRESETS:
            is_active = (
                (value is None and not self._current_timer_enabled)
                or (
                    value is not None
                    and self._current_timer_enabled
                    and value == self._current_timer_minutes
                )
            )
            btn = StyledButton(
                text=label,
                bg_color=C.ACCENT if is_active else C.BG_CARD,
                text_color=C.TEXT if is_active else C.TEXT_SECONDARY,
                bold=is_active,
                height=dp(44),
            )
            btn.bind(on_release=lambda b, v=value: self._pick_from_popup(v))
            body.add_widget(btn)
        self._duration_popup = Popup(
            title="Session duration",
            content=body,
            size_hint=(0.7, None),
            height=dp(360),
            auto_dismiss=True,
        )
        self._duration_popup.open()

    def _pick_from_popup(self, value) -> None:
        if self.on_duration_preset is not None:
            self.on_duration_preset(value)
        if self._duration_popup is not None:
            self._duration_popup.dismiss()
            self._duration_popup = None

    def refresh_duration_preset(self, timer_enabled: bool, timer_minutes: int) -> None:
        """Cache timer state and update the duration-picker label."""
        self._current_timer_enabled = timer_enabled
        self._current_timer_minutes = timer_minutes
        self._apply_duration_picker_label()

    def _apply_duration_picker_label(self) -> None:
        """Compute current-window label + width for the duration picker and apply."""
        from kivy.core.window import Window
        self._btn_duration_expand.text = _duration_picker_label(
            window_w=Window.width,
            timer_enabled=self._current_timer_enabled,
            timer_minutes=self._current_timer_minutes,
            narrow_threshold=_DURATION_PICKER_NARROW_THRESHOLD,
        )
        self._btn_duration_expand.width = _duration_picker_width(
            window_w=Window.width,
            narrow_threshold=_DURATION_PICKER_NARROW_THRESHOLD,
        )

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
        lines = max(1, text.count("\n") + 1)
        self._alert_label.height = dp(18) * lines

    def hide_alert(self) -> None:
        self._alert_label.text = ""
        self._alert_label.height = dp(0)

    def reset_display(self) -> None:
        self._graph.clear_data()
        self._graph.set_start_wall_time(None)
        self._start_time_str = ""
        self._timer_label.text = "00:00"
        self._state_label.text = "IDLE"
        self._state_label.color = C.STATE_NEUTRAL
        self.hide_alert()
        self.hide_overlay()
        self.hide_summary()
        for label in self._stat_labels.values():
            label.text = "0"
        self.set_controls_idle()

    def show_summary(self, session_id: int, stats: dict) -> None:
        """Show post-session summary overlay with stats and notes field."""
        self._summary_session_id = session_id
        # Fill stats
        dur = stats.get("duration", 0)
        self._summary_stats["duration"].text = format_duration(dur)
        self._summary_stats["avg_shamatha"].text = f"{stats.get('avg_shamatha', 0):.0f}"
        self._summary_stats["avg_meditation"].text = f"{stats.get('avg_meditation', 0):.0f}"
        above = stats.get("time_above_threshold", 0)
        self._summary_stats["time_above"].text = format_duration(above)
        sham90 = stats.get("time_shamatha_90", 0)
        self._summary_stats["time_shamatha_90"].text = format_duration(sham90)
        self._summary_notes.text = ""
        # Show
        self._summary.opacity = 1
        self._summary.size_hint = (1, 1)

    def hide_summary(self) -> None:
        self._summary.opacity = 0
        self._summary.size_hint = (0, 0)
        self._summary.size = (0, 0)
        self._summary_session_id = None

    @property
    def summary_save_btn(self) -> StyledButton:
        return self._summary_save_btn

    @property
    def summary_history_btn(self) -> StyledButton:
        return self._summary_history_btn

    @property
    def summary_close_btn(self) -> StyledButton:
        return self._summary_close_btn

    @property
    def summary_notes(self) -> str:
        return self._summary_notes.text.strip()

    @property
    def summary_session_id(self):
        return self._summary_session_id

    def _toggle_stats_mode(self, *_args) -> None:
        self._stats_mode = "aggregate" if self._stats_mode == "live" else "live"
        self._apply_stats_mode_styling()
        # Force immediate refresh using last known values
        metrics = getattr(self, "_last_metrics", {}) or {}
        stats = {}
        try:
            from kivy.app import App
            stats = App.get_running_app()._session_manager.compute_statistics()
        except Exception:
            pass
        self._render_stats(metrics, stats)
        # Persist
        try:
            from kivy.app import App
            App.get_running_app()._save_user_settings()
        except Exception:
            pass

    def _apply_stats_mode_styling(self) -> None:
        active = self._stats_mode == "aggregate"
        try:
            self._btn_stats_toggle.bg_color = C.PRIMARY if active else C.BG_CARD
            self._btn_stats_toggle.text = "AVG" if active else "LIVE"
        except Exception:
            pass

    def _render_stats(self, metrics: dict, stats: dict) -> None:
        titles, values = _format_stats_slots(self._stats_mode, metrics=metrics, stats=stats)
        for i, key in enumerate(self._stat_keys_in_order):
            self._stat_labels[key].text = values[i]
            self._stat_title_labels[key].text = titles[i]

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
        self._timer_label.color = C.TEXT
        self._state_label.color = C.STATE_NEUTRAL
        self._alert_label.color = C.WARM
        self._overlay_status.color = C.TEXT
        self._overlay_dots.color = C.PRIMARY
        for lbl in self._stat_labels.values():
            lbl.color = C.TEXT
