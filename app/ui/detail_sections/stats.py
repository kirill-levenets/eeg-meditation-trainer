"""The session detail's stats: one (title, value) row per stat, in a grid as tall as its rows."""
from kivy.metrics import dp
from kivy.uix.gridlayout import GridLayout

from app.ui.theme import C, F, S, ThemedLabel, fit_width_to_text, text_fills_box


def _row() -> tuple[ThemedLabel, ThemedLabel]:
    # A title takes its text's width (the column, its widest title) and the value the rest of the row.
    title = ThemedLabel(text="", font_size=F.SMALL, color=C.TEXT_SECONDARY, size_hint=(None, None), height=dp(20))
    fit_width_to_text(title, S.GAP)
    value = ThemedLabel(text="-", font_size=F.H3, bold=True, color=C.TEXT, halign="left", size_hint_y=None,
                        height=dp(20), shorten=True, shorten_from="right")
    text_fills_box(value)
    return title, value


class StatsRows:
    """Builds the grid into `layout`; a session that saved no metric has one threshold row where the others have Metric
    and Threshold, so the rows are made as needed and kept for the next session."""

    def __init__(self, layout) -> None:
        self.grid = GridLayout(cols=2, size_hint_y=None, spacing=dp(4), padding=dp(4))
        self._pool: list[tuple[ThemedLabel, ThemedLabel]] = []
        self.rows: list[tuple[ThemedLabel, ThemedLabel]] = []  # (title, value) of the rows shown, in order
        self.show([])
        layout.add_widget(self.grid)

    def show(self, rows: list[tuple[str, str]]) -> None:
        """These (title, value) rows, the grid as tall as they are."""
        while len(self._pool) < len(rows):
            self._pool.append(_row())
        grid = self.grid
        grid.clear_widgets()
        self.rows = self._pool[:len(rows)]
        for (text, shown), (title, value) in zip(rows, self.rows):
            title.text, value.text = text, shown
            grid.add_widget(title)
            grid.add_widget(value)
        n = len(rows)
        grid.height = n * dp(20) + max(n - 1, 0) * grid.spacing[1] + grid.padding[1] + grid.padding[3]
