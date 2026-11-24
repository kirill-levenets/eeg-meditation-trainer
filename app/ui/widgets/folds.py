"""Folding a section away: its chevron, its folded state, and detaching its body (never hidden in place)."""

from collections.abc import Callable

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app.ui.hooks import Hook
from app.ui.theme import ICONS_AVAILABLE, C, F, Icons
from app.ui.widgets.styled_button import StyledButton


class FoldChevron(StyledButton):
    """The chevron that folds a section away: down open, right folded (the accordion's), "Hide"/"Show" with no icon font.
    40 dp wide: an icon-only StyledButton narrower than ~36 dp crops its glyph to a tick."""

    def __init__(self, **kwargs) -> None:
        super().__init__(text="" if ICONS_AVAILABLE else "Hide", icon=Icons.CHEVRON_DOWN, bg_color=C.BG_CARD,
                         text_color=C.TEXT_SECONDARY, font_size=F.SMALL, size_hint_x=None, width=dp(40), **kwargs)

    def show_folded(self, folded: bool) -> None:
        self.set_icon(Icons.CHEVRON_RIGHT if folded else Icons.CHEVRON_DOWN)
        if not ICONS_AVAILABLE:
            self.text = "Show" if folded else "Hide"


class Fold:
    """A section's fold: whether it's folded, its chevron showing it, and a user's toggle reported to `on_change`."""

    on_change = Hook()

    def __init__(self, chevron: FoldChevron, apply: Callable[[bool], None]) -> None:
        self.folded = False
        self._chevron = chevron
        self._apply = apply
        chevron.bind(on_release=lambda *_a: self.toggle())

    def set(self, folded: bool) -> None:
        self.folded = folded
        self._apply(folded)
        self._chevron.show_folded(folded)

    def toggle(self) -> None:
        self.set(not self.folded)
        self.on_change(self.folded)


def fold_away(parent, body, anchor, folded: bool) -> None:
    """Detach `body` from `parent` (never hidden in place), or put it back right below `anchor`."""
    if folded and body.parent is parent:
        parent.remove_widget(body)
    elif not folded and body.parent is None:
        parent.add_widget(body, index=parent.children.index(anchor))


class RevealBox(BoxLayout):
    """Touch-safe conditional row: shows/hides its content by DETACHING the children,
    never collapse-in-place. Hidden = height 0 and no attached children, so it can't
    overflow or eat a neighbour's taps. (Kivy's Widget.on_touch_down consumes a tap on
    any colliding `disabled` widget, so the height=0/opacity=0/disabled idiom turns a
    hidden row into an invisible tap-eater — use this instead.)"""

    def __init__(self, content_height, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        super().__init__(**kwargs)
        self._content_height = content_height
        self._content_widgets: list = []
        self._revealed = False
        self.height = 0

    def set_content(self, *widgets) -> None:
        """Register the row's widgets; the row starts hidden (children detached)."""
        self._content_widgets = list(widgets)
        self._refresh()

    def reveal(self, show: bool) -> None:
        if bool(show) == self._revealed:
            return
        self._revealed = bool(show)
        self._refresh()

    def _refresh(self) -> None:
        self.clear_widgets()
        if self._revealed:
            for w in self._content_widgets:
                self.add_widget(w)
            self.height = self._content_height
        else:
            self.height = 0
