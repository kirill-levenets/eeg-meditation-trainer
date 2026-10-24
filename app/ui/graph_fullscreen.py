"""A graph shown alone in a full-window overlay, with its legend, and put back where it was on close."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout

from app.ui.hooks import is_wired, wire
from app.ui.theme import C, fill_background
from app.ui.widgets.legend import LegendBar


class GraphFullscreen:
    """The fullscreen view of any graph: reparented into an overlay on `root`, not cloned, so a live graph keeps
    updating there."""

    def __init__(self, root) -> None:
        self._root = root
        self._overlay = None
        self._content = None
        self._legend = None
        self._graph = None
        self._close = None  # the restore closure, set while a graph is fullscreen
        self._owner_series_change = None  # the graph's own on_series_change, chained while it is fullscreen

    @property
    def is_open(self) -> bool:
        return self._overlay is not None

    def present(self, graph) -> None:
        """Reparent `graph` into a full-window overlay; restore it on close.

        Reparenting (not cloning) keeps the widget's single Window bind and its
        live add_point feed, so a live graph keeps updating in fullscreen. A
        plain root overlay (not a Popup) is used so the graph reaches every
        edge — a Popup insets its content with title/border chrome.
        """
        parent = graph.parent
        if parent is None or self._overlay is not None:
            return
        index = parent.children.index(graph)
        # Copy these — size_hint/size are live ReferenceListProperties; a bare
        # reference would track the (1,1) we set below and break restore.
        orig_size_hint = list(graph.size_hint)
        orig_pos_hint = dict(graph.pos_hint)
        orig_size = list(graph.size)

        overlay = FloatLayout(size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        fill_background(overlay, C.BG_DARK)

        parent.remove_widget(graph)
        graph.size_hint = (1, 1)
        graph.pos_hint = {}
        # graph + legend stacked, so the fullscreen view keeps its legend.
        content = BoxLayout(orientation="vertical", spacing=dp(4))
        content.add_widget(graph)
        self._content = content
        self._legend = self._build_legend(graph)
        content.add_widget(self._legend)
        overlay.add_widget(content)
        self._root.add_widget(overlay)
        self._overlay = overlay
        self._graph = graph
        self._owner_series_change = graph.on_series_change if is_wired(graph, "on_series_change") else None
        wire(graph, on_series_change=self._series_changed)

        def _restore(*_a):
            self._close = None
            wire(graph, on_series_change=self._owner_series_change)
            self._owner_series_change = None
            self._root.remove_widget(overlay)
            if graph.parent is not None:
                graph.parent.remove_widget(graph)
            graph.size_hint = orig_size_hint
            graph.pos_hint = orig_pos_hint
            graph.size = orig_size
            parent.add_widget(graph, index=index)
            graph.set_expand_callback(self.present)
            graph._redraw()
            self._overlay = None
            self._content = None
            self._legend = None
            self._graph = None

        self._close = _restore
        # The expand glyph's corner becomes the close cross (the series picker and fit stay usable here too).
        graph.set_expand_callback(_restore, closes=True)

    def close(self) -> bool:
        """Put the fullscreen graph back; False if none was fullscreen."""
        if self._overlay is None or self._close is None:
            return False
        self._close()
        return True

    def _series_changed(self) -> None:
        """A series shown, hidden or renamed: the owner's legend and the fullscreen one follow."""
        if self._owner_series_change is not None:
            self._owner_series_change()
        self.refresh_legend()

    def refresh_legend(self) -> None:
        """Rebuild the fullscreen legend (if fullscreen)."""
        if self._overlay is None or self._graph is None:
            return
        self._content.remove_widget(self._legend)
        self._legend = self._build_legend(self._graph)
        self._content.add_widget(self._legend)

    @staticmethod
    def _build_legend(graph) -> LegendBar:
        """A wrapping legend (colored names) for the currently visible series."""
        legend = LegendBar()
        legend.show_graph(graph)
        return legend
