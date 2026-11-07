"""The live graph's series picker as a test reads it: the row labels it would list now."""
import app.ui.graph_series as graph_series


def picker_rows(app, monkeypatch) -> list[str]:
    """The series picker's row labels for the live graph, as it would open now."""
    shown = []

    class _Popup:
        def bind(self, **_kw):
            pass

        def open(self):
            pass

    def capture(_title, rows, footer=None, **_kw):
        # A row is its toggle, or a box with the toggle first (a formula slot's, with Choose…).
        shown.extend(getattr(row, "text", None) or row.children[-1].text for row in rows)
        return _Popup()

    monkeypatch.setattr(graph_series, "make_scroll_popup", capture)
    app._graph_series.present_picker(app._live_screen.graph)
    return shown
