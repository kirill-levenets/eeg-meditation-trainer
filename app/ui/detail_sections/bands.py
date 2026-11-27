"""The session detail's band power: its title with a chevron that folds the table away, and the per-band totals over
the whole session, or a placeholder until they arrive."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

from app.ui.hooks import Hook, wire
from app.ui.theme import C, F, S, ThemedLabel, fit_width_to_text
from app.ui.widgets.band_totals import BandTotalsView
from app.ui.widgets.folds import Fold, FoldChevron, fold_away
from app.ui.widgets.what_if import LOAD_FAILED, LOADING


class BandSection:
    """Builds the title and the table's holder into `layout`, and reports a fold and a change of the table's view
    through its hooks."""

    on_view_change = Hook()  # (mode, sort_by, descending): the app keeps it per profile
    on_collapse = Hook()  # the user folded the table (True) or opened it

    def __init__(self, layout) -> None:
        self._header = BoxLayout(size_hint_y=None, height=dp(28), spacing=S.GAP_SM)
        title = ThemedLabel(text="Band Power (whole session)", font_size=F.SMALL, color=C.TEXT_SECONDARY,
                            size_hint_x=None)
        fit_width_to_text(title)
        self.chevron = FoldChevron(size_hint_y=None, height=dp(28))
        self._fold = Fold(self.chevron, lambda folded: fold_away(layout, self._holder, self._header, folded))
        wire(self._fold, on_change=lambda folded: self.on_collapse(folded))
        for w in (title, self.chevron, Widget()):
            self._header.add_widget(w)
        layout.add_widget(self._header)
        self.totals = BandTotalsView(on_change=lambda mode, sort_by, desc: self.on_view_change(mode, sort_by, desc))
        self._placeholder = ThemedLabel(text="", font_size=F.BODY, color=C.TEXT_SECONDARY, size_hint_y=None,
                                        height=dp(40))
        # Holds the table, or the placeholder until the session's totals arrive; as tall as what it holds.
        self._holder = BoxLayout(size_hint_y=None)
        self.totals.bind(height=self._fit_holder)
        self._placeholder.bind(height=self._fit_holder)
        layout.add_widget(self._holder)
        self._filled, self._failed = True, False  # built empty, as a session with no totals shows it
        self._show()

    @property
    def collapsed(self) -> bool:
        return self._fold.folded

    def set_collapsed(self, collapsed: bool) -> None:
        """Fold the table (or its placeholder) away, detached, or bring it back under its title; the title stays."""
        self._fold.set(collapsed)

    def set_view_state(self, mode: str, sort_by: str, descending: bool) -> None:
        """The profile's view of the table (mode, sort), before its totals arrive."""
        self.totals.set_view_state(mode, sort_by, descending)

    def show_loading(self) -> None:
        self._filled, self._failed = False, False
        self._show()

    def show_failed(self) -> None:
        """Totals that haven't arrived won't: the placeholder says so."""
        self._failed = True
        self._show()

    def show_totals(self, totals: dict[str, float]) -> None:
        self.totals.set_totals(totals)
        self._filled = True
        self._show()

    def _show(self) -> None:
        shown = self.totals if self._filled else self._placeholder
        self._placeholder.text = LOAD_FAILED if self._failed else LOADING
        if shown.parent is not self._holder:
            self._holder.clear_widgets()
            self._holder.add_widget(shown)
        self._fit_holder()

    def _fit_holder(self, *_a) -> None:
        if self._holder.children:
            self._holder.height = self._holder.children[0].height
