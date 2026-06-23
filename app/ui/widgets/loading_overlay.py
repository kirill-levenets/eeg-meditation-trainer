from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label

from app.ui.theme import POPUP_TEXT, C, F


class LoadingOverlay(BoxLayout):
    """App-global modal spinner: dimmed backdrop + status text + animated dots.

    Hidden by collapsing size_hint to (0,0) so it leaves the touch chain when
    inactive. Caller must move long work off the main thread — a Clock-animated
    overlay can't paint while the main thread is blocked.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(orientation="vertical", **kwargs)
        with self.canvas.before:
            self._bg_color = Color(*C.BG_OVERLAY)
            self._bg_rect = Rectangle(size=self.size, pos=self.pos)
        self.bind(
            size=lambda w, v: setattr(self._bg_rect, "size", v),
            pos=lambda w, v: setattr(self._bg_rect, "pos", v),
        )

        self.add_widget(BoxLayout(size_hint_y=1))  # top spacer

        self._status = Label(
            text="", font_size=F.BODY, color=POPUP_TEXT,
            halign="center", valign="middle",
            size_hint_y=None, height=dp(80),
        )
        self._status.bind(size=self._status.setter("text_size"))
        self.add_widget(self._status)

        self._dots = Label(
            text="", font_size=dp(24), color=C.PRIMARY,
            size_hint_y=None, height=dp(30),
        )
        self.add_widget(self._dots)

        self.add_widget(BoxLayout(size_hint_y=1))  # bottom spacer

        self._dot_event = None
        self._dot_count = 0
        self.opacity = 0
        self.size_hint = (0, 0)
        self.size = (0, 0)
        C.add_listener(self._refresh_theme)

    @property
    def is_visible(self) -> bool:
        return self.opacity > 0

    def on_touch_down(self, touch):
        # Modal while loading: swallow taps so they don't reach the screen
        # behind (e.g. a second session-row tap spawning a second load).
        if self.is_visible:
            return True
        return super().on_touch_down(touch)

    def show(self, text: str = "Loading…") -> None:
        self._status.text = text
        self.opacity = 1
        self.size_hint = (1, 1)
        self._dot_count = 0
        if self._dot_event:
            self._dot_event.cancel()
        self._dot_event = Clock.schedule_interval(self._animate_dots, 0.5)

    def update(self, text: str) -> None:
        """Change the status text, but only while the overlay is showing."""
        if self.is_visible:
            self._status.text = text

    def hide(self) -> None:
        self.opacity = 0
        self.size_hint = (0, 0)
        self.size = (0, 0)
        if self._dot_event:
            self._dot_event.cancel()
            self._dot_event = None
        self._dots.text = ""

    def _animate_dots(self, dt: float) -> None:
        self._dot_count = (self._dot_count + 1) % 4
        self._dots.text = ".  " * self._dot_count

    def _refresh_theme(self, *args) -> None:
        self._bg_color.rgba = C.BG_OVERLAY
        self._dots.color = C.PRIMARY
