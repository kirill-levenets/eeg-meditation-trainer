"""The Settings screen's accordion: one section open at a time, each a header over its scrolling content."""

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView

from app.ui.theme import C, F, Icons, S
from app.ui.widgets.styled_button import StyledButton


class ThemedAccordion(BoxLayout):
    """Custom accordion container — only one section open at a time.

    Usage:
        acc = ThemedAccordion()
        sec = acc.add_section("Device", collapsed=False)
        sec.add_widget(my_widget)
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_y", None)
        super().__init__(**kwargs)
        self._sections = []
        self.bind(minimum_height=self.setter("height"))

    def add_section(self, title, collapsed=True, icon=""):
        section = _AccordionSection(title=title, collapsed=collapsed, icon=icon,
                                    accordion=self)
        super().add_widget(section)
        self._sections.append(section)
        return section

    def _on_section_open(self, opened_section):
        """Close all other sections when one opens."""
        for sec in self._sections:
            if sec is not opened_section and not sec._collapsed:
                sec._set_collapsed(True, notify=False)


class _AccordionSection(BoxLayout):
    """Single section in ThemedAccordion — styled header + collapsible content."""

    def __init__(self, title="", collapsed=True, icon="", accordion=None, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_y", None)
        super().__init__(**kwargs)
        self._collapsed = collapsed
        self._accordion = accordion

        # Header button
        icon_text = icon if icon else (Icons.CHEVRON_RIGHT if collapsed else Icons.CHEVRON_DOWN)
        self._header = StyledButton(
            text=title,
            icon=icon_text,
            bg_color=C.BG_CARD,
            text_color=C.TEXT_SECONDARY,
            font_size=F.H3,
            height=dp(38),
            bold=True,
        )
        self._header.bind(on_release=self._toggle)
        self._header_icon_text = icon  # user icon (empty = use chevron)
        super().add_widget(self._header)

        # Content area (inside ScrollView for long sections)
        self._content = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=S.GAP,
            padding=[S.GAP_SM, S.GAP_SM],
        )
        self._content.bind(minimum_height=self._content.setter("height"))
        # Also re-fire _update_height when grandchild widgets resize the
        # content (e.g. populate_bt_devices appending rows after the section
        # was already opened). Without this, _scroll.height keeps the value
        # snapshotted on the original add_widget call and the ScrollView
        # clips later additions to a single visible row.
        self._content.bind(minimum_height=lambda *_: self._update_height())
        self._scroll = ScrollView(size_hint_y=None, height=0)
        self._scroll.add_widget(self._content)
        super().add_widget(self._scroll)

        if collapsed:
            self._scroll.height = 0
            self._scroll.opacity = 0
            self._scroll.remove_widget(self._content)

        self._scroll.bind(height=self._recalc_height)
        self._recalc_height()

    def add_widget(self, widget, *args, **kwargs):
        if hasattr(self, "_content"):
            self._content.add_widget(widget, *args, **kwargs)
            self._update_height()
        else:
            super().add_widget(widget, *args, **kwargs)

    def _toggle(self, *args):
        if self._collapsed:
            if self._accordion:
                self._accordion._on_section_open(self)
            self._set_collapsed(False)
        else:
            self._set_collapsed(True)

    def open(self):
        """Programmatically expand this section and collapse siblings."""
        if self._accordion:
            self._accordion._on_section_open(self)
        if self._collapsed:
            self._set_collapsed(False)

    def _set_collapsed(self, collapsed, notify=True):
        self._collapsed = collapsed
        if collapsed:
            # Detach the content so a collapsed section has no geometry below its
            # header. Otherwise its display-clipped widgets still overlap the
            # sections beneath in the touch layer and, via the nested-ScrollView
            # simulated click, steal taps aimed at those section headers.
            if self._content.parent is self._scroll:
                self._scroll.remove_widget(self._content)
            self._scroll.height = 0
            self._scroll.opacity = 0
            if not self._header_icon_text:
                self._header.set_icon(Icons.CHEVRON_RIGHT)
        else:
            if self._content.parent is not self._scroll:
                self._scroll.add_widget(self._content)
            self._scroll.opacity = 1
            self._update_height()
            if not self._header_icon_text:
                self._header.set_icon(Icons.CHEVRON_DOWN)

    def _recalc_height(self, *args):
        """Set section height = header + scroll content height."""
        self.height = dp(38) + self._scroll.height

    def _update_height(self):
        if self._collapsed:
            self._scroll.height = 0
        else:
            content_h = self._content.minimum_height
            self._scroll.height = min(content_h, dp(500))
