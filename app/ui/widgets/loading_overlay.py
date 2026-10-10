from kivy.clock import Clock
from kivy.metrics import dp

from app.ui.theme import C, F, ModalPanel, ModalScrim, ThemedLabel


class LoadingOverlay(ModalScrim):
    """App-global modal spinner: the theme's modal panel (status text + animated dots) over a dimmed backdrop.

    Hidden by collapsing size_hint to (0,0) so it leaves the touch chain when
    inactive. Caller must move long work off the main thread — a Clock-animated
    overlay can't paint while the main thread is blocked.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        panel = ModalPanel(size_hint_x=0.8)

        self._status = ThemedLabel(
            text="", font_size=F.BODY, color=C.TEXT,
            halign="center", valign="middle", size_hint_y=None,
        )
        self._status.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                          texture_size=lambda w, v: setattr(w, "height", max(v[1], dp(24))))
        panel.add_widget(self._status)

        self._dots = ThemedLabel(
            text="", font_size=F.px(24), color=C.PRIMARY,
            size_hint_y=None, height=dp(30),
        )
        panel.add_widget(self._dots)
        self.add_widget(panel)

        self._dot_event = None
        self._reveal_event = None
        self._dot_count = 0
        self._active = False
        self.opacity = 0
        self.size_hint = (0, 0)
        self.size = (0, 0)

    @property
    def is_visible(self) -> bool:
        return self.opacity > 0

    def on_touch_down(self, touch):
        # Modal from show() on, also before a delayed show paints: swallow taps so they don't reach the screen
        # behind (e.g. a tap on a session row while it is being deleted).
        if self._active:
            return True
        return super().on_touch_down(touch)

    def show(self, text: str = "Loading…", delay: float = 0.0) -> None:
        """Make the screen modal now and paint after `delay` seconds, so a job that ends sooner never flashes it."""
        self._status.text = text
        self._active = True
        self.size_hint = (1, 1)
        self._cancel_events()
        if delay > 0:
            self._reveal_event = Clock.schedule_once(lambda _dt: self._reveal(), delay)
        else:
            self._reveal()

    def _reveal(self) -> None:
        self._reveal_event = None
        self.opacity = 1
        self._dot_count = 0
        self._dot_event = Clock.schedule_interval(self._animate_dots, 0.5)

    def update(self, text: str) -> None:
        """Change the status text, but only while the overlay is showing."""
        if self._active:
            self._status.text = text

    def hide(self) -> None:
        self._active = False
        self.opacity = 0
        self.size_hint = (0, 0)
        self.size = (0, 0)
        self._cancel_events()
        self._dots.text = ""

    def _cancel_events(self) -> None:
        for event in (self._dot_event, self._reveal_event):
            if event:
                event.cancel()
        self._dot_event = self._reveal_event = None

    def _animate_dots(self, dt: float) -> None:
        self._dot_count = (self._dot_count + 1) % 4
        self._dots.text = ".  " * self._dot_count
