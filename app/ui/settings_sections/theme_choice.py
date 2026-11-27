"""Settings → Theme: the four colour themes, the active one marked whoever applied it."""

from kivy.metrics import dp

from app.ui.hooks import Hook
from app.ui.theme import THEMES, C, F, S
from app.ui.widgets.choice_toggle import ChoiceToggle


class ThemeSection:
    """Builds the section's content into `section`; a pick applies the theme, then reports it through its hook."""

    on_change = Hook()

    def __init__(self, section) -> None:
        self._toggle = ChoiceToggle([(name, name) for name in THEMES], C.theme_name, self._on_select,
                                    button={"font_size": F.TINY, "height": dp(34)},
                                    size_hint_y=None, height=dp(36), spacing=S.GAP_SM)
        section.add_widget(self._toggle)
        C.add_listener(self._show_active)

    def _on_select(self, name: str) -> None:
        C.set_theme(name)
        self.on_change(name)

    def _show_active(self) -> None:
        """Mark the active theme, whoever applied it (this selector or a profile's settings load)."""
        self._toggle.show(C.theme_name)
