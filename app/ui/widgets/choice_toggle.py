"""A switch whose every position reads as what it shows: one button per choice, the chosen one filled."""

from collections.abc import Callable, Hashable

from kivy.uix.boxlayout import BoxLayout

from app.ui.theme import C, StyledButton


class ChoiceToggle(BoxLayout):
    """One button per choice, all shown: the chosen one filled and bold, the others outlined and muted, which reads on a
    card as on the screen. A tap on another choice shows it and calls on_choose(key); `show` marks a choice made
    elsewhere (a loaded profile) without the call."""

    def __init__(self, choices: list[tuple[Hashable, str]], chosen: Hashable, on_choose: Callable[[Hashable], None], *,
                 button: dict, **layout) -> None:
        super().__init__(**layout)
        self._on_choose = on_choose
        self.buttons: dict[Hashable, StyledButton] = {}
        for key, text in choices:
            btn = StyledButton(text=text, **button)
            btn.bind(on_release=lambda _btn, k=key: self._choose(k))
            self.buttons[key] = btn
            self.add_widget(btn)
        self.show(chosen)

    def show(self, key: Hashable) -> None:
        self.chosen = key
        for k, btn in self.buttons.items():
            on = k == key
            btn.outline = not on
            btn.bg_color = C.PRIMARY if on else C.TEXT_SECONDARY  # unchosen: the outline's colour, as its text's
            btn.text_color = None if on else C.TEXT_SECONDARY  # None: the glyph colour that reads on the fill
            btn.bold = on

    def _choose(self, key: Hashable) -> None:
        if key == self.chosen:
            return
        self.show(key)
        self._on_choose(key)
