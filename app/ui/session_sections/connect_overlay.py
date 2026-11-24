"""The Session screen's connection overlay: the headset's connect or scan status over Cancel, and Retry once it failed."""
from app.ui.theme import C, S, StyledButton
from app.ui.widgets.loading_overlay import LoadingOverlay


class ConnectOverlay(LoadingOverlay):
    """The loading overlay with Cancel; a failure stops the dots, adds Retry and makes Cancel a Close."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cancel_btn = StyledButton(text="Cancel", size_hint=(0.4, None), height=S.BTN_H,
                                       pos_hint={"center_x": 0.5}, bg_color=C.DANGER, bg_pressed=C.DANGER_DIM)
        self._panel.add_widget(self.cancel_btn)
        # Attached only on failure (show_retry): a hidden one left a blank slot in the card.
        self.retry_btn = StyledButton(text="Retry", size_hint=(0.4, None), height=S.BTN_H,
                                      pos_hint={"center_x": 0.5}, bg_color=C.PRIMARY, bg_pressed=C.PRIMARY_DIM)

    def show(self, text: str = "Connecting...") -> None:
        """At once: a delayed one would take taps on its unpainted Cancel."""
        if self.retry_btn.parent is not None:
            self._panel.remove_widget(self.retry_btn)
        self.cancel_btn.text = "Cancel"
        super().show(text)

    def show_retry(self, text: str) -> None:
        """The failure's message, with Retry and Close."""
        self._status.text = text
        if self.retry_btn.parent is None:
            self._panel.add_widget(self.retry_btn)
        self.cancel_btn.text = "Close"
        self._cancel_events()
        self._dots.text = ""
