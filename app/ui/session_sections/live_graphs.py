"""The Session screen's graphs: Metrics (the metrics graph and its legend) or Raw EEG (the waveform, the band power and
its legend), one view shown at a time behind its switch."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app.config import APP
from app.eeg.band_spec import BAND_KEYS, GROUP_KEYS, group_powers
from app.session.live_mirror import MirrorView
from app.session.scoring import scored_steps, target_steps
from app.ui.graph_kinds import BAND_POWER, METRICS, METRICS_COLORS, RAW_EEG
from app.ui.hooks import Hook, wire
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.theme import F, S
from app.ui.widgets.choice_toggle import ChoiceToggle
from app.ui.widgets.legend import LegendBar


class LiveGraphs:
    """Builds the switch (`toggle`) and the area that holds the shown view (`area`), for the screen to place; reports
    the metrics graph's shown lines through its hook. A hidden view's graphs don't draw."""

    on_lines_shown = Hook()  # the metrics graph's shown lines changed: their keys

    def __init__(self) -> None:
        self.toggle = ChoiceToggle([("metrics", "Metrics"), ("raw", "Raw EEG")], "metrics", self.show_view,
                                   button={"height": dp(28), "font_size": F.SMALL}, size_hint_y=None, height=dp(28),
                                   spacing=S.GAP_SM)
        self._training_key: str | None = None  # the series a program segment trains: bold, with », in the legend
        self._metrics_view = BoxLayout(orientation="vertical", spacing=S.GAP_SM)
        self.metrics = ScrollableGraphWidget(METRICS, graph_id="live_metrics", size_hint_y=1)
        # A solid line at 100, each metric's top, marked even when a formula's 200 scale puts it mid-graph.
        self.metrics.set_reference_line(100.0)
        wire(self.metrics, on_series_change=self._metric_lines_changed)
        self._metrics_view.add_widget(self.metrics)
        self._legend = LegendBar()
        self._metrics_view.add_widget(self._legend)
        self._show_metric_legend(self.metrics.visible_keys())  # set_visible rebuilds it only on a change
        self._raw_view = BoxLayout(orientation="vertical", spacing=S.GAP_SM)
        self.raw = ScrollableGraphWidget(RAW_EEG, graph_id="live_raw", max_points=APP.RAW_WAVEFORM_MAX,
                                         size_hint_y=0.5)
        self._raw_view.add_widget(self.raw)
        self.band = ScrollableGraphWidget(BAND_POWER, graph_id="live_band", size_hint_y=0.5)
        self._raw_view.add_widget(self.band)
        self._band_legend = LegendBar()
        wire(self.band, on_series_change=self._show_band_legend)
        self._show_band_legend()
        self._raw_view.add_widget(self._band_legend)
        self.area = BoxLayout(size_hint_y=None, height=dp(400))
        self.area.add_widget(self._metrics_view)
        for graph in self._view_graphs("raw"):
            graph.set_drawing_enabled(False)

    @property
    def view(self) -> str:
        """The view in the area: 'metrics' or 'raw'."""
        return "raw" if self._raw_view.parent is self.area else "metrics"

    def _view_graphs(self, view: str) -> tuple[ScrollableGraphWidget, ...]:
        return (self.raw, self.band) if view == "raw" else (self.metrics,)

    def show_view(self, view: str) -> None:
        """'metrics' or 'raw' in the area; a detached graph keeps its size, so it would keep drawing every tick
        unseen."""
        if view == self.view:
            return
        for graph in self._view_graphs(self.view):
            graph.set_drawing_enabled(False)
        for graph in self._view_graphs(view):
            graph.set_drawing_enabled(True)
        self.area.clear_widgets()
        self.area.add_widget(self._raw_view if view == "raw" else self._metrics_view)
        self.toggle.show(view)

    def _metric_lines_changed(self) -> None:
        shown = self.metrics.visible_keys()
        self._show_metric_legend(shown)
        self.on_lines_shown(shown)

    def _show_metric_legend(self, shown: list) -> None:
        """The metrics legend: the lines shown, » on the one a program segment trains."""
        self._legend.show_graph(self.metrics, [m for m in METRICS_COLORS if m in shown],
                                active_key=self._training_key if self._training_key in METRICS_COLORS else None)

    def _show_band_legend(self) -> None:
        self._band_legend.show_graph(self.band)

    def set_training_series(self, key: str | None) -> None:
        """Mark the series a program segment trains (bold, with »), or with None or a key not plotted, none. The line
        colours come with each point (add_point's `scored`), so a new mark recolours nothing already drawn."""
        self._training_key = key
        self._show_metric_legend(self.metrics.visible_keys())

    def add_raw_sample(self, sample: dict[str, float]) -> None:
        """A tick's raw sample: its waveform (or the bands' sum, without one) and its band powers."""
        waveform = sample.get("raw_eeg_waveform", [])
        if waveform:
            self.raw.add_points_batch("eeg", waveform)
        else:
            self.raw.add_point({"eeg": sum(sample.get(k, 0.0) for k in BAND_KEYS)})
        self.band.add_point(group_powers(lambda k: sample.get(k, 0.0)))

    def load_mirror(self, view: MirrorView) -> None:
        """Reload the three graphs from a session's mirror, one load per graph, with their markers and the threshold
        steps."""
        if view.metrics:
            self.metrics.load_static_data({key: [d.get(key, 0.0) for d in view.metrics] for key in METRICS_COLORS},
                                          new_session=False, markers=view.tick_marks)
            self.metrics.set_threshold_steps(target_steps(d.get("score_target") for d in view.metrics))
            self.metrics.set_gradient_steps(scored_steps(d.get("score_key") for d in view.metrics))
        if view.bands:
            self.band.load_static_data({key: [d.get(key, 0.0) for d in view.bands] for key in GROUP_KEYS},
                                       new_session=False, markers=view.tick_marks)
        if view.waveform:
            self.raw.load_static_data({"eeg": view.waveform}, new_session=False, markers=view.sample_marks)
