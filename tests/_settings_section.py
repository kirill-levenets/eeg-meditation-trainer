"""One Settings section built as SettingsScreen builds it, without the other ten (the whole screen is ~390 widgets)."""
from collections.abc import Callable

from kivy.uix.scrollview import ScrollView

from app.ui.theme import ThemedAccordion


def settings_section(build: Callable, title: str = "Section"):
    """`build(section, scroll)` makes the section object, as SettingsScreen's `_build_ui` does."""
    scroll = ScrollView()
    accordion = ThemedAccordion()
    scroll.add_widget(accordion)
    return build(accordion.add_section(title, collapsed=True), scroll)
