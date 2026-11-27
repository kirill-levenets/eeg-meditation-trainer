"""The Session screen: its graphs and controls, composing the parts around them (`session_sections/`)."""
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.screenmanager import Screen

from app.config import APP
from app.eeg.band_spec import BAND_KEYS, GROUP_KEYS, GROUP_NAMES, group_powers
from app.metrics.series_names import SERIES_NAMES
from app.session.live_mirror import MirrorView
from app.session.scoring import scored_steps, target_steps
from app.ui.graph_scroll import GraphAwareScrollView
from app.ui.hooks import Hook, wire
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.session_sections.connect_overlay import ConnectOverlay
from app.ui.session_sections.duration_picker import DurationPicker
from app.ui.session_sections.end_card import EndCard
from app.ui.session_sections.header import SessionHeader
from app.ui.session_sections.stats_strip import StatsStrip
from app.ui.theme import C, F, Icons, S, ThemedLabel, fill_background, text_fills_box
from app.ui.widgets.band_totals import BAND_COLORS, BAND_SCALES
from app.ui.widgets.choice_toggle import ChoiceToggle
from app.ui.widgets.legend import LegendBar
from app.ui.widgets.styled_button import StyledButton

_RAW_SIGNAL_COLORS = {"eeg": C.MEDITATION}
_RAW_SIGNAL_SCALES = {"eeg": 500.0}
_RAW_WAVEFORM_RATE = 512.0

METRICS_COLORS = {
    "shamatha_score": C.SHAMATHA,
    "meditation_score": C.MED_SCORE,
    "distraction": C.DISTRACTION,
    "sinking": C.SINKING,
    "subtle_distraction": C.SUBTLE,
    "native_attention": C.ATTENTION,
    "native_meditation": C.MEDITATION,
    "custom_formula": C.CUSTOM,
    "custom_formula_2": C.CUSTOM2,
    "custom_formula_3": C.CUSTOM3,
    # Live lines for a program's custom-formula segments (hidden until a program
    # with custom segments runs); one per distinct custom formula, labels track them.
    "program_formula": C.WARM,
    "program_formula_2": C.WARM2,
    "program_formula_3": C.WARM3,
}

METRICS_SCALES = {
    "shamatha_score": 100.0,
    "meditation_score": 100.0,
    "distraction": 100.0,
    "sinking": 100.0,
    "subtle_distraction": 100.0,
    "native_attention": 100.0,
    "native_meditation": 100.0,
    "custom_formula": 200.0,
    "custom_formula_2": 200.0,
    "custom_formula_3": 200.0,
    "program_formula": 200.0,
    "program_formula_2": 200.0,
    "program_formula_3": 200.0,
}


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


class LiveSessionScreen(Screen):
    """Main session screen with graph, stats, and controls."""

    on_lines_shown = Hook()  # the metrics graph's shown lines changed: their keys

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "live_session"
        self._build_ui()
        # Scroll height tracking is persistent (the widget itself lives for the screen's lifetime)
        self._scroll.bind(height=self._reflow)

    def on_enter(self, *args) -> None:
        Window.bind(on_resize=self._reflow, on_rotate=self._reflow)
        self._reflow()

    def _build_ui(self) -> None:
        float_root = FloatLayout()

        # Screen background
        self._root = BoxLayout(orientation="vertical", padding=S.PAGE_PAD, spacing=S.GAP_SM,
                               size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        root = self._root
        fill_background(root, C.BG)

        self.header = SessionHeader()
        root.add_widget(self.header)

        # ── Alert banner ──
        self._alert_label = ThemedLabel(
            text="",
            size_hint_y=None,
            height=dp(0),
            font_size=F.SMALL,
            color=C.WARM,
            halign="center",
        )
        text_fills_box(self._alert_label)
        root.add_widget(self._alert_label)

        # ── View toggle: Metrics / Raw EEG ──
        self._view_toggle = ChoiceToggle([("metrics", "Metrics"), ("raw", "Raw EEG")], "metrics", self._set_view,
                                         button={"height": dp(28), "font_size": F.SMALL},
                                         size_hint_y=None, height=dp(28), spacing=S.GAP_SM)
        root.add_widget(self._view_toggle)

        # ── Metrics view (default) ──
        self._metrics_container = BoxLayout(orientation="vertical", spacing=S.GAP_SM)

        self._graph = ScrollableGraphWidget(
            colors=METRICS_COLORS,
            scales=METRICS_SCALES,
            viewport_seconds=60,
            size_hint_y=1,
            graph_id="live_metrics",
            names=SERIES_NAMES,
        )
        # Reference line at the per-metric maximum so level 100 is
        # visually marked even when custom_formula (scale 200) widens
        # max_scale and pushes 100 into the middle of the graph.
        self._graph.set_reference_line(100.0)
        # The on-graph series-picker glyph is wired centrally for every graph by
        # GraphSet.wire_glyphs. The legend tracks the graph's own
        # visible set: any change (picker toggle or restore) rebuilds it.
        wire(self._graph, on_series_change=self._metric_lines_changed)
        self._metrics_container.add_widget(self._graph)

        self._legend = LegendBar()
        self._metrics_container.add_widget(self._legend)
        # Series the program is currently training (bold + » in the legend); None
        # outside a program segment.
        self._training_key = None
        self._rebuild_metric_legend(self._graph.visible_keys())  # set_visible rebuilds it only on a change

        # ── Raw EEG view (hidden initially) ──
        self._raw_container = BoxLayout(orientation="vertical", spacing=S.GAP_SM)

        self._raw_graph = ScrollableGraphWidget(
            colors=_RAW_SIGNAL_COLORS,
            scales=_RAW_SIGNAL_SCALES,
            viewport_seconds=10,
            show_value_labels=True,
            show_timestamps=True,
            sample_rate=_RAW_WAVEFORM_RATE,
            max_points=APP.RAW_WAVEFORM_MAX,
            bipolar=True,
            size_hint_y=0.5,
            graph_id="live_raw",
        )
        self._raw_container.add_widget(self._raw_graph)

        self._band_graph = ScrollableGraphWidget(
            colors=BAND_COLORS,
            scales=BAND_SCALES,
            viewport_seconds=60,
            show_value_labels=True,
            show_timestamps=True,
            auto_scale=True,
            size_hint_y=0.5,
            graph_id="live_band",
            names=GROUP_NAMES,
        )
        self._raw_container.add_widget(self._band_graph)

        self._band_legend = LegendBar()
        wire(self._band_graph, on_series_change=self._rebuild_band_legend)
        self._rebuild_band_legend()
        self._raw_container.add_widget(self._band_legend)

        # Graph area holder — swaps between metrics and raw views
        self._graph_area = BoxLayout(size_hint_y=None, height=dp(400))
        self._graph_area.add_widget(self._metrics_container)
        self._active_view = "metrics"
        for g in self._view_graphs("raw"):
            g.set_drawing_enabled(False)

        self.stats = StatsStrip(self._graph)

        # Scrollable body: graph + stats
        self._scroll = GraphAwareScrollView(size_hint=(1, 1), do_scroll_x=False)
        self._body = BoxLayout(
            orientation="vertical",
            size_hint=(1, None),
            spacing=S.GAP_SM,
        )
        self._body.bind(minimum_height=self._body.setter("height"))
        self._body.add_widget(self._graph_area)
        self._body.add_widget(self.stats)
        self._scroll.add_widget(self._body)
        root.add_widget(self._scroll)

        # ── Controls ──
        self._bottom_bar = BoxLayout(
            size_hint_y=None, height=S.BTN_H + dp(4),
            spacing=S.GAP, padding=[S.GAP, 0],
        )

        # Start + duration-picker form a visual cluster with a tiny separator
        self._btn_start = StyledButton(
            text="Start", icon=Icons.PLAY, bg_color=C.ACCENT,
            bg_pressed=C.ACCENT_DIM,
            vertical=True,
        )
        self.duration = DurationPicker()
        start_cluster = BoxLayout(
            orientation="horizontal",
            spacing=dp(1),  # tiny separator
            size_hint_y=None, height=S.BTN_H,
        )
        start_cluster.add_widget(self._btn_start)
        start_cluster.add_widget(self.duration.button)

        self._btn_pause = StyledButton(
            text="Pause", icon=Icons.PAUSE, bg_color=C.WARM,
            bg_pressed=C.WARM_DIM, disabled=True,
            vertical=True,
        )
        self._btn_stop = StyledButton(
            text="Stop", icon=Icons.STOP, bg_color=C.DANGER,
            bg_pressed=C.DANGER_DIM, disabled=True,
            vertical=True,
        )
        self._btn_marker = StyledButton(
            text="Mark", icon=Icons.MARKER, bg_color=C.PURPLE,
            bg_pressed=C.PURPLE_DIM, disabled=True,
            vertical=True,
        )
        self._bottom_bar.add_widget(start_cluster)
        self._bottom_bar.add_widget(self._btn_pause)
        self._bottom_bar.add_widget(self._btn_stop)
        self._bottom_bar.add_widget(self._btn_marker)
        self._body.add_widget(self._bottom_bar)

        float_root.add_widget(root)

        self.end_card = EndCard(float_root)
        self.connect_overlay = ConnectOverlay()
        float_root.add_widget(self.connect_overlay)

        self.add_widget(float_root)

    def _reflow(self, *args) -> None:
        """Resize graph to fill viewport OR to leftover space if viewport is tall enough."""
        needed = ("_scroll", "_graph_area", "stats", "_bottom_bar")
        if not all(hasattr(self, a) for a in needed):
            return
        # spacing between body's 3 children (graph, stats_card, bottom_bar) = 2 gaps
        spacing = S.GAP_SM * 2
        self._graph_area.height = _compute_graph_height_adaptive(
            viewport_h=self._scroll.height,
            stats_h=self.stats.height,
            bottom_h=self._bottom_bar.height,
            spacing=spacing,
            min_fixed_graph=dp(400),
            min_graph_floor=dp(240),
        )
    def on_leave(self, *args) -> None:
        Window.unbind(on_resize=self._reflow, on_rotate=self._reflow)

    def _view_graphs(self, view: str) -> tuple:
        return (self._raw_graph, self._band_graph) if view == "raw" else (self._graph,)

    def _set_view(self, view: str) -> None:
        """Switch between 'metrics' and 'raw' graph views."""
        if view == self._active_view:
            return
        self._graph_area.clear_widgets()
        # A detached graph keeps its size, so it would keep drawing every tick unseen.
        for g in self._view_graphs(self._active_view):
            g.set_drawing_enabled(False)
        for g in self._view_graphs(view):
            g.set_drawing_enabled(True)
        self._graph_area.add_widget(self._raw_container if view == "raw" else self._metrics_container)
        self._view_toggle.show(view)
        self._active_view = view

    def _metric_lines_changed(self) -> None:
        shown = self._graph.visible_keys()
        self._rebuild_metric_legend(shown)
        self.on_lines_shown(shown)

    def _rebuild_metric_legend(self, enabled_keys: list) -> None:
        """Clear and re-populate the metrics legend with only the enabled metrics.

        The program's currently-training series (if it's a plotted metric) is
        bolded with a » marker via active_text.
        """
        self._legend.show_graph(self._graph, [m for m in METRICS_COLORS if m in enabled_keys],
                                active_key=self._training_key if self._training_key in METRICS_COLORS else None)

    def set_training_series(self, key) -> None:
        """Mark the series currently driving the program target (bold + »), or
        pass None/a non-plotted key to clear the marker. The line colours come with each point (add_point's `scored`),
        so a new mark recolours nothing already drawn."""
        self._training_key = key
        self._rebuild_metric_legend(self._graph.visible_keys())
        self.stats.set_scored(key)  # the strip's first title names it

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
            self._raw_graph.add_point({"eeg": sum(sample.get(k, 0.0) for k in BAND_KEYS)})
        self._band_graph.add_point(group_powers(lambda k: sample.get(k, 0.0)))

    def clear_readout(self) -> None:
        """Back to the readout a fresh screen shows: no session's numbers, timer, start time, state or alert."""
        self.stats.clear()
        self.header.clear()
        self._graph.set_start_wall_time(None)
        self.hide_alert()

    def set_start_time(self, epoch: float) -> None:
        """The session's start wall-clock time: the header's clock shows it, the graph's time axis counts from it."""
        self.header.set_start_time(epoch)
        self._graph.set_start_wall_time(epoch)

    def set_controls_running(self) -> None:
        self._btn_start.disabled = True
        self.duration.button.disabled = True
        self._btn_pause.text = "Pause"
        self._btn_pause.disabled = False
        self._btn_stop.disabled = False
        self._btn_marker.disabled = False

    def set_controls_paused(self) -> None:
        self._btn_start.disabled = True
        self.duration.button.disabled = True
        self._btn_pause.text = "Resume"
        self._btn_pause.disabled = False
        self._btn_stop.disabled = False
        self._btn_marker.disabled = True

    def set_controls_idle(self) -> None:
        self._btn_start.disabled = False
        self.duration.button.disabled = False
        self._btn_pause.disabled = True
        self._btn_pause.text = "Pause"
        self._btn_stop.disabled = True
        self._btn_marker.disabled = True

    def _rebuild_band_legend(self) -> None:
        """Repopulate the band legend with only the band graph's visible series."""
        self._band_legend.show_graph(self._band_graph)

    def show_alert(self, text: str) -> None:
        """Show a warning banner below the header."""
        self._alert_label.text = text
        lines = max(1, text.count("\n") + 1)
        self._alert_label.height = dp(18) * lines

    def load_mirror(self, view: MirrorView) -> None:
        """Batch-reload the 3 live graphs from a session's mirror (one load_static_data per graph), with their markers
        and the threshold steps."""
        if view.metrics:
            self.graph.load_static_data({key: [d.get(key, 0.0) for d in view.metrics] for key in METRICS_COLORS},
                                        new_session=False, markers=view.tick_marks)
            self.graph.set_threshold_steps(target_steps(d.get("score_target") for d in view.metrics))
            self.graph.set_gradient_steps(scored_steps(d.get("score_key") for d in view.metrics))
        if view.bands:
            self.band_graph.load_static_data({key: [d.get(key, 0.0) for d in view.bands] for key in GROUP_KEYS},
                                             new_session=False, markers=view.tick_marks)
        if view.waveform:
            self.raw_graph.load_static_data({"eeg": view.waveform}, new_session=False, markers=view.sample_marks)

    def hide_alert(self) -> None:
        self._alert_label.text = ""
        self._alert_label.height = dp(0)

