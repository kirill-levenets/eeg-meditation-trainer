"""The Session screen's controls: Start with the duration picker beside it, Pause (Resume while paused), Stop and Mark,
each enabled as the session's state allows."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app.ui.hooks import Hook
from app.ui.session_sections.duration_picker import DurationPicker
from app.ui.theme import C, Icons, S
from app.ui.widgets.styled_button import StyledButton


class ControlBar(BoxLayout):
    """The buttons in a row; a tap is reported through its hook, and `show_running`, `show_paused` and `show_idle`
    enable the ones that state takes."""

    on_start = Hook()
    on_pause = Hook()  # Pause, or Resume while paused
    on_stop = Hook()
    on_mark = Hook()

    def __init__(self) -> None:
        super().__init__(size_hint_y=None, height=S.BTN_H + dp(4), spacing=S.GAP, padding=[S.GAP, 0])
        self.start = StyledButton(text="Start", icon=Icons.PLAY, bg_color=C.ACCENT, bg_pressed=C.ACCENT_DIM,
                                  vertical=True)
        self.duration = DurationPicker()
        start_cluster = BoxLayout(orientation="horizontal", spacing=dp(1), size_hint_y=None, height=S.BTN_H)
        start_cluster.add_widget(self.start)
        start_cluster.add_widget(self.duration.button)
        self.add_widget(start_cluster)
        self.pause = self._button("Pause", Icons.PAUSE, C.WARM, C.WARM_DIM)
        self.stop = self._button("Stop", Icons.STOP, C.DANGER, C.DANGER_DIM)
        self.mark = self._button("Mark", Icons.MARKER, C.PURPLE, C.PURPLE_DIM)
        for button, hook in ((self.start, "on_start"), (self.pause, "on_pause"), (self.stop, "on_stop"),
                             (self.mark, "on_mark")):
            button.bind(on_release=lambda _b, h=hook: getattr(self, h)())

    def _button(self, text: str, icon: str, colour, pressed) -> StyledButton:
        """A button off until a session runs."""
        button = StyledButton(text=text, icon=icon, bg_color=colour, bg_pressed=pressed, disabled=True, vertical=True)
        self.add_widget(button)
        return button

    def show_running(self) -> None:
        self._show(start=False, pause="Pause", stop=True, mark=True)

    def show_paused(self) -> None:
        self._show(start=False, pause="Resume", stop=True, mark=False)

    def show_idle(self) -> None:
        self._show(start=True, pause=None, stop=False, mark=False)

    def _show(self, *, start: bool, pause: str | None, stop: bool, mark: bool) -> None:
        """Which buttons take a tap; `pause` names the Pause button, or with None leaves it off and named Pause."""
        self.start.disabled = self.duration.button.disabled = not start
        self.pause.text = pause or "Pause"
        self.pause.disabled = pause is None
        self.stop.disabled = not stop
        self.mark.disabled = not mark
