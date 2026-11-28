"""A graph shown alone in a full-window overlay, with its legend, and put back where it was on close."""
from collections.abc import Callable
from dataclasses import dataclass

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout

from app.ui.hooks import is_wired, wire
from app.ui.theme import C, fill_background
from app.ui.widgets.legend import LegendBar


@dataclass
class _Shown:
    """The graph while it is fullscreen, the overlay showing it, and where and how big it was."""

    graph: object
    parent: object
    index: int
    size_hint: list
    pos_hint: dict
    size: list
    overlay: FloatLayout
    content: BoxLayout  # the graph over its legend
    legend: LegendBar
    owner_series_change: Callable[[], None] | None  # the graph's own on_series_change, chained while it is fullscreen


class GraphFullscreen:
    """The fullscreen view of any graph: reparented into an overlay on `root`, not cloned, so a live graph keeps its one
    Window bind and its feed and goes on updating there. A plain overlay, not a Popup: the graph reaches every edge."""

    def __init__(self, root) -> None:
        self._root = root
        self._shown: _Shown | None = None

    @property
    def is_open(self) -> bool:
        return self._shown is not None

    def present(self, graph) -> None:
        """`graph` in a full-window overlay, over its legend; its expand glyph becomes the close cross (the series
        picker and fit stay usable)."""
        parent = graph.parent
        if parent is None or self._shown is not None:
            return
        # Copies: size_hint and size are live ReferenceListProperties, which would follow the (1, 1) set below.
        shown = _Shown(graph, parent, parent.children.index(graph), list(graph.size_hint), dict(graph.pos_hint),
                       list(graph.size), FloatLayout(size_hint=(1, 1), pos_hint={"x": 0, "y": 0}),
                       BoxLayout(orientation="vertical", spacing=dp(4)), self._legend_for(graph),
                       graph.on_series_change if is_wired(graph, "on_series_change") else None)
        fill_background(shown.overlay, C.BG_DARK)
        parent.remove_widget(graph)
        graph.size_hint = (1, 1)
        graph.pos_hint = {}
        shown.content.add_widget(graph)
        shown.content.add_widget(shown.legend)
        shown.overlay.add_widget(shown.content)
        self._root.add_widget(shown.overlay)
        self._shown = shown
        wire(graph, on_series_change=self._series_changed)
        graph.set_expand_callback(self._close_cross, closes=True)

    def _close_cross(self, _graph) -> None:
        self.close()

    def close(self) -> bool:
        """Put the fullscreen graph back where it was, as big as it was; False if none was fullscreen."""
        shown, self._shown = self._shown, None
        if shown is None:
            return False
        graph = shown.graph
        wire(graph, on_series_change=shown.owner_series_change)
        self._root.remove_widget(shown.overlay)
        if graph.parent is not None:
            graph.parent.remove_widget(graph)
        graph.size_hint = shown.size_hint
        graph.pos_hint = shown.pos_hint
        graph.size = shown.size
        shown.parent.add_widget(graph, index=shown.index)
        graph.set_expand_callback(self.present)
        graph._redraw()
        return True

    def _series_changed(self) -> None:
        """A series shown, hidden or renamed: the owner's legend and the fullscreen one follow."""
        shown = self._shown
        if shown is None:
            return
        if shown.owner_series_change is not None:
            shown.owner_series_change()
        shown.content.remove_widget(shown.legend)
        shown.legend = self._legend_for(shown.graph)
        shown.content.add_widget(shown.legend)

    @staticmethod
    def _legend_for(graph) -> LegendBar:
        """A wrapping legend (coloured names) of the graph's visible series."""
        legend = LegendBar()
        legend.show_graph(graph)
        return legend
