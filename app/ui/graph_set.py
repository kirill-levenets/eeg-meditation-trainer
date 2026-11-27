"""The app's six graphs as one set: the Session screen's three and a session detail's three, the corner buttons they
share, the line width they all draw at and the zoom the live ones keep."""
from collections.abc import Callable

from app.settings.registry import FLOAT, Setting, held, kept
from app.ui.raw_eeg_screen import ScrollableGraphWidget


class GraphSet:
    """Two zoom groups: a detail zoomed out over a long session must not reach the live graphs' saved zoom."""

    def __init__(self, live_screen, diary_screen, display_section) -> None:
        self.live = (live_screen.graph, live_screen.raw_graph, live_screen.band_graph)
        self.detail = diary_screen.graphs.all
        self._display = display_section  # its slider shows the line width
        ScrollableGraphWidget.link_zoom(*self.live)
        ScrollableGraphWidget.link_zoom(*self.detail)

    def all(self) -> tuple:
        """Every mounted graph, for the affordances they share (expand, series picker, fit, restore)."""
        return self.live + self.detail

    def wire_glyphs(self, expand: Callable, pick_series: Callable) -> None:
        """Every graph's corner buttons: fullscreen, the series picker where there is more than one series to choose
        from (on a single-series graph it could only blank the line) and fit, its zoom group together."""
        for graph in self.all():
            graph.set_expand_callback(expand)
            if len(graph.series_keys()) > 1:
                graph.set_series_picker_callback(pick_series)
            graph.set_fit_callback(ScrollableGraphWidget.toggle_fit)

    def settings(self) -> list[Setting]:
        """The line width every graph draws at, held (the Display slider shows it, persisted once a drag settles), and
        the zoom: the saved one starts both groups, but only the live group's is saved, so a detail's never comes back."""
        return [held("line_width", FLOAT, self._display.line_width, self._apply_line_width, settle=True),
                kept("graph_zoom_seconds", FLOAT, lambda: self.live[0].zoom_seconds, self._apply_zoom)]

    def _apply_line_width(self, width: float) -> None:
        self._display.show_line_width(width)
        for graph in self.all():
            graph.set_line_width(width)

    def _apply_zoom(self, seconds: float) -> None:
        self.live[0].set_zoom_seconds(seconds)
        self.detail[0].set_zoom_seconds(seconds)
