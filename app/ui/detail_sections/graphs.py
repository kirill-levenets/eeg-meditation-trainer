"""The session detail's graphs: their data, built from a session's stored rows off the main thread, and the three
graphs (metrics, raw EEG, band power) behind their tabs with the shown one's legend."""
import math

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app.eeg.band_spec import BAND_KEYS, group_powers
from app.logger import timed
from app.metrics.formula_slots import COMPUTED_SERIES
from app.session.scoring import scored_steps, target_steps
from app.session.session_program import RunnablePlan, recorded_program
from app.ui.graph_kinds import BAND_POWER, METRICS, METRICS_COLORS, RAW_EEG
from app.ui.graph_series import show_program_series
from app.ui.hooks import wire
from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.theme import C, F, S, ThemedLabel
from app.ui.widgets.band_totals import BAND_COLORS
from app.ui.widgets.choice_toggle import ChoiceToggle
from app.ui.widgets.legend import LegendBar
from app.ui.widgets.what_if import LOAD_FAILED, LOADING

_SYNTH_RATE: float = RAW_EEG.sample_rate
_TICK_DURATION: float = 0.5
_SAMPLES_PER_TICK: int = int(_SYNTH_RATE * _TICK_DURATION)

_BAND_FREQS = {
    "delta": 2.5,
    "theta": 6.0,
    "alpha1": 9.0,
    "alpha2": 11.0,
    "beta1": 15.0,
    "beta2": 24.0,
    "gamma1": 35.0,
    "gamma2": 45.0,
}

_AMPLITUDE_SCALE: float = 0.0004


_RAW_KEYS = {k: f"{k}_raw" for k in BAND_KEYS}
# The raw-EEG preview graph's deque is capped at sample_rate*60 (last 60s), so
# synthesizing the whole session then discarding all but the tail cost ~3.6s on
# a 47-min session. Synthesize only the retained tail.
_RAW_MAX_SAMPLES: int = int(_SYNTH_RATE * 60)


def _synthesize_waveform(rows: list[dict]) -> tuple[list[float], int]:
    """(the waveform's tail, its first tick): per tick, 0.5 s of sines at each band's frequency, amplitude the root of
    its stored power; only the samples the graph keeps are built, on the global sample index, so the tail matches a
    full synthesis."""
    spt = _SAMPLES_PER_TICK
    keep_ticks = -(-_RAW_MAX_SAMPLES // spt)  # ceil
    start = max(0, len(rows) - keep_ticks)
    waveform: list[float] = []
    sample_idx = start * spt
    for row in rows[start:]:
        amps = {}
        for band, db_key in _RAW_KEYS.items():
            power = max(row.get(db_key, 0.0), 0.0)
            amps[band] = math.sqrt(power) * _AMPLITUDE_SCALE

        for _i in range(spt):
            t = sample_idx / _SYNTH_RATE
            val = 0.0
            for band, freq in _BAND_FREQS.items():
                val += amps.get(band, 0.0) * math.sin(2.0 * math.pi * freq * t)
            waveform.append(val)
            sample_idx += 1

    if not waveform:
        return waveform, start
    peak = max(abs(v) for v in waveform) or 1.0
    scale_factor = (500.0 * 0.8) / peak
    return [v * scale_factor for v in waveform], start


def detail_graph_data(rows: list[dict], formula_series: dict[str, list[float]]) -> dict:
    """{"metrics" | "raw" | "freq": (series, marker indices), "threshold_steps": ...} from a session's stored rows: pure
    Python, so the open builds it on its worker and the main thread only loads it."""
    # Formula lines (the Settings slots', a program's) aren't stored per tick: they come entirely from the session's
    # formula replay. A slot the session didn't record stays empty (no flat zero-line phantom).
    stored = [k for k in METRICS_COLORS if k not in COMPUTED_SERIES]
    metrics_series: dict[str, list[float]] = {k: [row.get(k, 0.0) for row in rows] for k in stored}
    metrics_series.update({k: formula_series.get(k, []) for k in METRICS_COLORS if k in COMPUTED_SERIES})

    with timed("diary.synth_waveform"):
        synth, raw_start = _synthesize_waveform(rows)  # tail only, see _synthesize_waveform

    freq_series: dict[str, list[float]] = {k: [] for k in BAND_COLORS}
    for row in rows:
        for key, power in group_powers(lambda k: row.get(f"{k}_raw", 0.0)).items():
            freq_series[key].append(power)

    markers = [i for i, row in enumerate(rows) if row.get("marker", 0)]
    # The raw graph holds only the tail (from raw_start): its markers are offset to it.
    raw_markers = [(i - raw_start) * _SAMPLES_PER_TICK for i in markers if i >= raw_start]
    return {"metrics": (metrics_series, markers), "raw": ({"eeg": synth}, raw_markers), "freq": (freq_series, markers),
            "threshold_steps": target_steps(row.get("score_target") for row in rows),  # None: rows without targets
            "gradient_steps": scored_steps(row.get("score_key") for row in rows)}  # a program's, segment by segment


TABS = (("metrics", "Metrics"), ("raw", "Raw EEG"), ("freq", "Frequencies"))


class DetailGraphs:
    """Builds the tabs, the graph area and the legend into `layout`. A graph whose data hasn't arrived shows a
    placeholder in its place; the legend marks the series the session was scored on."""

    def __init__(self, layout) -> None:
        self._tabs = ChoiceToggle(list(TABS), "metrics", self.show_tab, button={"font_size": F.SMALL, "height": dp(30)},
                                  size_hint_y=None, height=dp(30), spacing=S.GAP_SM)
        layout.add_widget(self._tabs)
        self._area = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(200))  # one graph at a time
        layout.add_widget(self._area)
        self._placeholder = ThemedLabel(text="", font_size=F.BODY, color=C.TEXT_SECONDARY)
        self._ready: set[str] = {key for key, _label in TABS}  # the graphs with their data in place
        self._failed = False
        self._scored_key: str | None = None  # the series the shown session was scored on, marked in its legend
        # The Session screen's kinds: a session's Metric is saved under the live graph's names.
        self.metrics = ScrollableGraphWidget(METRICS, graph_id="diary_metrics", size_hint_y=1)
        # Its cap is what the synthesizer keeps: the raw marker indices count into it.
        self.raw = ScrollableGraphWidget(RAW_EEG, graph_id="diary_raw", max_points=_RAW_MAX_SAMPLES, size_hint_y=1)
        self.freq = ScrollableGraphWidget(BAND_POWER, graph_id="diary_freq", size_hint_y=1)
        self._by_tab = {"metrics": self.metrics, "raw": self.raw, "freq": self.freq}
        # The legend follows the shown graph's visible set; a picker toggle (or a restore) on it rebuilds the legend.
        for graph in self.all:
            wire(graph, on_series_change=lambda g=graph: self._on_series_change(g))
        self._legend = LegendBar()  # a wrapping flow: many series fit
        layout.add_widget(self._legend)
        self._area.add_widget(self.metrics)
        self._rebuild_legend()

    @property
    def all(self) -> tuple[ScrollableGraphWidget, ...]:
        """The three graphs: metrics, raw EEG, band power."""
        return self.metrics, self.raw, self.freq

    @property
    def tab(self) -> str:
        return self._tabs.chosen

    def show_loading(self, scored_key: str | None) -> None:
        """A newly opened session: every graph empty and waiting for its data, on the Metrics tab."""
        self._scored_key = scored_key
        self.metrics.clear_data()
        self.metrics.set_gradient_series(scored_key)
        self.raw.clear_data()
        self.freq.clear_data()
        self._ready, self._failed = set(), False
        self.show_tab("metrics")

    def show_failed(self) -> None:
        """Data that hasn't arrived won't: the placeholder says so."""
        self._failed = True
        self.show_tab(self.tab)

    def set_formula_names(self, names: dict[str, str]) -> None:
        """The session's formula lines' names, as it recorded them."""
        for key, name in names.items():
            self.metrics.set_series_name(key, name)

    def set_threshold(self, value: float) -> None:
        self.metrics.set_threshold(value)

    def show_program(self, program_json: str) -> None:
        """The recorded program's stepped threshold on the metrics graph; none (or one that doesn't parse) clears the
        steps, so a simple session shows its single threshold."""
        prog = recorded_program(program_json)
        self.metrics.set_threshold_steps(prog.threshold_steps(self.metrics._sample_rate) if prog is not None else None)

    def show_program_lines(self, plan: RunnablePlan | None) -> None:
        """A program session shows exactly its program's lines, as the Session screen did while it ran, marked as the
        program's (never saved as the profile's selection); None, a simple session, clears the mark."""
        if plan is not None:
            show_program_series(self.metrics, plan)
        else:
            self.metrics.set_program_lines()

    def fill_order(self) -> list[str]:
        """The graphs in the order to fill them: the shown tab first."""
        return [self.tab] + [key for key, _label in TABS if key != self.tab]

    def fill(self, section: str, data: dict) -> None:
        """Put one graph's data (from detail_graph_data) in place, and show it if its tab is the shown one."""
        series, markers = data[section]
        graph = self._by_tab[section]
        with timed(f"diary.fill_{section}"):
            graph.load_static_data(series, markers=markers)
            if section == "metrics" and data["threshold_steps"]:  # else the line the open drew from the session row
                graph.set_threshold_steps(data["threshold_steps"])
            if section == "metrics" and data["gradient_steps"]:  # else the series the open coloured from the row
                graph.set_gradient_steps(data["gradient_steps"])
            graph.set_scroll_offset(0)  # at the end, so the user sees the latest data and can drag back
        self._ready.add(section)
        if section == self.tab:
            self.show_tab(section)

    def show_tab(self, tab: str) -> None:
        """The tab's graph in the area, or its placeholder while its data hasn't arrived."""
        self._tabs.show(tab)
        self._area.clear_widgets()
        shown = self._by_tab[tab] if tab in self._ready else None
        if shown is None:
            self._placeholder.text = LOAD_FAILED if self._failed else LOADING
            self._area.add_widget(self._placeholder)
        else:
            self._area.add_widget(shown)
        for graph in self.all:
            graph.set_drawing_enabled(graph is shown)  # a hidden tab's graph draws once it is shown (enabling redraws)
        self._rebuild_legend()

    def _on_series_change(self, graph: ScrollableGraphWidget) -> None:
        if graph is self._by_tab[self.tab]:
            self._rebuild_legend()

    def _rebuild_legend(self) -> None:
        """The shown tab's visible series, » on the one the session was scored on."""
        graph = self._by_tab[self.tab]
        scored = self._scored_key if self.tab == "metrics" and self._scored_key in graph.visible_keys() else None
        self._legend.show_graph(graph, active_key=scored)
