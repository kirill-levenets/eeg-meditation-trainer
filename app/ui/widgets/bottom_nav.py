"""The bottom navigation bar: one tab per screen, the active one marked."""

from kivy.graphics import Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout

from app.ui.theme import ICONS_AVAILABLE, C, F, Icons, S, ThemedColor, ThemedLabel


class BottomNav(BoxLayout):
    """3-tab bottom navigation bar.

    Usage:
        nav = BottomNav(tabs=[
            ("Session", "session"),
            ("History", "history"),
            ("Settings", "settings"),
        ], callback=on_tab_switch)
    """

    active_tab = StringProperty("")

    def __init__(self, tabs, callback=None, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", S.NAV_H)
        kwargs.setdefault("spacing", 0)
        super().__init__(orientation="horizontal", **kwargs)
        self._callback = callback
        self._tab_widgets = {}

        self._update_bg()
        self.bind(size=self._update_bg, pos=self._update_bg)

        _TAB_ICONS = {
            "session": Icons.BRAIN,
            "history": Icons.HISTORY,
            "settings": Icons.COG,
        }
        for label, key in tabs:
            tab = _NavTab(label=label, key=key, icon=_TAB_ICONS.get(key, ""))
            tab.bind(on_release=self._on_tab_press)
            self._tab_widgets[key] = tab
            self.add_widget(tab)

        if tabs:
            self.active_tab = tabs[0][1]

    def _update_bg(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            ThemedColor(C.BG_DARK)
            Rectangle(size=self.size, pos=self.pos)
            ThemedColor(C.BORDER)
            Rectangle(
                size=(self.size[0], dp(1)),
                pos=(self.pos[0], self.pos[1] + self.size[1] - dp(1)),
            )

    def _on_tab_press(self, tab):
        self.active_tab = tab.key
        if self._callback:
            self._callback(tab.key)

    def on_active_tab(self, *args):
        for key, tab in self._tab_widgets.items():
            tab.active = (key == self.active_tab)


class _NavTab(ButtonBehavior, BoxLayout):
    """Single tab in the bottom nav."""

    active = BooleanProperty(False)

    def __init__(self, label="", key="", icon="", **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.key = key
        self.padding = [0, dp(2)]
        self.spacing = 0

        self._icon = None
        if icon and ICONS_AVAILABLE:
            self._icon = ThemedLabel(
                text=icon,
                font_name="Icons",
                font_size=F.glyph(20),
                color=C.TEXT_MUTED,
                size_hint_y=None,
                height=dp(22),
            )
            self.add_widget(self._icon)

        self._label = ThemedLabel(
            text=label,
            font_size=F.TINY,
            bold=True,
            halign="center",
            valign="middle",
            color=C.TEXT_MUTED,
            size_hint_y=None,
            height=dp(14),
        )
        self._label.bind(size=self._label.setter("text_size"))
        self._indicator = BoxLayout(size_hint_y=None, height=dp(3))

        self.add_widget(self._label)
        self.add_widget(self._indicator)
        self.bind(active=self._redraw)
        self._redraw()

    def _redraw(self, *args):
        self._indicator.canvas.before.clear()
        if self.active:
            self._label.color = C.PRIMARY
            if self._icon:
                self._icon.color = C.PRIMARY
            with self._indicator.canvas.before:
                ThemedColor(C.PRIMARY)
                RoundedRectangle(
                    pos=self._indicator.pos,
                    size=self._indicator.size,
                    radius=[dp(2)],
                )
            self._indicator.bind(pos=self._redraw_indicator, size=self._redraw_indicator)
        else:
            self._label.color = C.TEXT_MUTED
            if self._icon:
                self._icon.color = C.TEXT_MUTED

    def _redraw_indicator(self, *args):
        if self.active:
            self._indicator.canvas.before.clear()
            with self._indicator.canvas.before:
                ThemedColor(C.PRIMARY)
                RoundedRectangle(
                    pos=self._indicator.pos,
                    size=self._indicator.size,
                    radius=[dp(2)],
                )
