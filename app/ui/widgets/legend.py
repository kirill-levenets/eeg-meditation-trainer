"""Wrapping legend bar: colored series labels that flow onto extra rows.

A single-row BoxLayout split the width equally across labels, so many series
(e.g. 6 metrics + 3 custom formulas) overlapped or were clipped. This flows
labels left-to-right and wraps to new rows, growing its own height.
"""

from kivy.metrics import dp
from kivy.uix.label import Label
from kivy.uix.stacklayout import StackLayout

from app.ui.theme import F


class LegendBar(StackLayout):
    """Flow-layout legend. Feed it `(text, rgba)` items via `set_items`."""

    def __init__(self, font_size: float | None = None, **kwargs) -> None:
        super().__init__(
            orientation="lr-tb",
            size_hint_y=None,
            spacing=(dp(10), dp(2)),
            **kwargs,
        )
        self._font_size = font_size if font_size is not None else F.TINY
        self.bind(minimum_height=self.setter("height"))

    def set_items(self, items: list[tuple[str, tuple]],
                  active_text: str | None = None) -> None:
        """Render the legend. `active_text` (matched against an item's text) is
        the series currently driving the program target — shown bold with a »
        marker so the user can see what's being trained right now. (» renders in
        Roboto; the geometric ▸/▶ triangles render as tofu in this build.)"""
        self.clear_widgets()
        for text, color in items:
            is_active = active_text is not None and text == active_text
            lbl = Label(
                text=f"» {text}" if is_active else text,
                font_size=self._font_size,
                color=color,
                bold=is_active,
                size_hint=(None, None),
                height=dp(18),
            )
            # Size each label to its text so the flow layout can pack/wrap them;
            # texture_size resolves after the first render, then width follows.
            lbl.bind(texture_size=lambda inst, ts: setattr(inst, "width", ts[0] + dp(6)))
            self.add_widget(lbl)
