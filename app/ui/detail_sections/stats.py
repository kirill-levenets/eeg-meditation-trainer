"""The session detail's stats: one (title, value) row per stat, in a grid as tall as its rows."""
from kivy.metrics import dp
from kivy.uix.gridlayout import GridLayout

from app.ui.theme import C, F, S, ThemedLabel, fit_width_to_text, text_fills_box
from app.ui.widgets.rows import StatRows


def _row() -> tuple[tuple[ThemedLabel, ThemedLabel], ThemedLabel, ThemedLabel]:
    # A title takes its text's width (the column, its widest title) and the value the rest of the row.
    title = ThemedLabel(text="", font_size=F.SMALL, color=C.TEXT_SECONDARY, size_hint=(None, None), height=dp(20))
    fit_width_to_text(title, S.GAP)
    value = ThemedLabel(text="-", font_size=F.H3, bold=True, color=C.TEXT, halign="left", size_hint_y=None,
                        height=dp(20), shorten=True, shorten_from="right")
    text_fills_box(value)
    return (title, value), title, value


def stats_rows(layout) -> StatRows:
    """The grid, built into `layout`, its title column and value column one row per stat."""
    grid = GridLayout(cols=2, size_hint_y=None, spacing=dp(4), padding=dp(4))
    rows = StatRows(grid, _row, dp(20))
    rows.show([])
    layout.add_widget(grid)
    return rows
