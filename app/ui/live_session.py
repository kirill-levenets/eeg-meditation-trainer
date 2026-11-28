"""The Session screen: its parts (`session_sections/`) in order, and the alert line under its header."""
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.screenmanager import Screen

from app.ui.graph_scroll import GraphAwareScrollView
from app.ui.session_sections.connect_overlay import ConnectOverlay
from app.ui.session_sections.control_bar import ControlBar
from app.ui.session_sections.end_card import EndCard
from app.ui.session_sections.header import SessionHeader
from app.ui.session_sections.live_graphs import LiveGraphs
from app.ui.session_sections.stats_strip import StatsStrip
from app.ui.theme import C, F, S, ThemedLabel, fill_background, text_fills_box

_GRAPH_MIN_FIXED = dp(400)  # the graph fills what the page leaves it from this height; below, the page scrolls
_GRAPH_FLOOR = dp(240)  # never shorter


def _graph_height(viewport_h: float, stats_h: float, bar_h: float) -> float:
    """What the page leaves the graph under the stats and the controls when that is tall enough, else the viewport's
    height, the page scrolling; never under the floor."""
    left = viewport_h - stats_h - bar_h - 2 * S.GAP_SM  # the body's two gaps
    return max(left if left >= _GRAPH_MIN_FIXED else viewport_h, _GRAPH_FLOOR)


class LiveSessionScreen(Screen):
    """The header, the alert line, the graphs (`graphs`), the stats strip and the controls (`controls`) in a page that
    scrolls when the screen is short, with the end card and the connecting card over them."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "live_session"
        float_root = FloatLayout()
        root = BoxLayout(orientation="vertical", padding=S.PAGE_PAD, spacing=S.GAP_SM, size_hint=(1, 1),
                         pos_hint={"x": 0, "y": 0})
        fill_background(root, C.BG)
        self.header = SessionHeader()
        root.add_widget(self.header)
        self._alert_label = ThemedLabel(text="", size_hint_y=None, height=dp(0), font_size=F.SMALL, color=C.WARM,
                                        halign="center")
        text_fills_box(self._alert_label)
        root.add_widget(self._alert_label)
        self.graphs = LiveGraphs()
        root.add_widget(self.graphs.toggle)
        self.stats = StatsStrip(self.graphs.metrics)
        self.controls = ControlBar()
        self._scroll = GraphAwareScrollView(size_hint=(1, 1), do_scroll_x=False)
        body = BoxLayout(orientation="vertical", size_hint=(1, None), spacing=S.GAP_SM)
        body.bind(minimum_height=body.setter("height"))
        for part in (self.graphs.area, self.stats, self.controls):
            body.add_widget(part)
        self._scroll.add_widget(body)
        root.add_widget(self._scroll)
        float_root.add_widget(root)
        self.end_card = EndCard(float_root)
        self.connect_overlay = ConnectOverlay()
        float_root.add_widget(self.connect_overlay)
        self.add_widget(float_root)
        self._scroll.bind(height=self._reflow)

    def on_enter(self, *args) -> None:
        Window.bind(on_resize=self._reflow, on_rotate=self._reflow)
        self._reflow()

    def _reflow(self, *args) -> None:
        """The graph's height for the page's viewport."""
        self.graphs.area.height = _graph_height(self._scroll.height, self.stats.height, self.controls.height)

    def on_leave(self, *args) -> None:
        Window.unbind(on_resize=self._reflow, on_rotate=self._reflow)

    def set_training_series(self, key) -> None:
        """Mark the series a program segment trains, in the legend and the stats strip's first title."""
        self.graphs.set_training_series(key)
        self.stats.set_scored(key)

    def clear_readout(self) -> None:
        """Back to the readout a fresh screen shows: no session's numbers, timer, start time, state or alert."""
        self.stats.clear()
        self.header.clear()
        self.graphs.metrics.set_start_wall_time(None)
        self.hide_alert()

    def set_start_time(self, epoch: float) -> None:
        """The session's start wall-clock time: the header's clock shows it, the graph's time axis counts from it."""
        self.header.set_start_time(epoch)
        self.graphs.metrics.set_start_wall_time(epoch)

    def show_alert(self, text: str) -> None:
        """Show a warning banner below the header."""
        self._alert_label.text = text
        lines = max(1, text.count("\n") + 1)
        self._alert_label.height = dp(18) * lines

    def hide_alert(self) -> None:
        self._alert_label.text = ""
        self._alert_label.height = dp(0)

