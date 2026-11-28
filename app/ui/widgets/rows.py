"""Rows: quick-pick presets for a value, the inline name editor under a list's row, and a session's stats rows."""

from collections.abc import Callable, Sequence

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app.ui.theme import C, CenteredTextInput, F, Icons, S, ThemedLabel
from app.ui.widgets.styled_button import StyledButton


class RenameRow(BoxLayout):
    """The inline name editor under a list's row: a field and Save (or Enter) calling `on_save`; its owner places it.
    `max_length` stops the field there while typing."""

    def __init__(self, on_save: Callable[[], None], max_length: int = 0, **kwargs) -> None:
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(40))
        kwargs.setdefault("spacing", S.GAP_SM)
        kwargs.setdefault("padding", [0, dp(2)])
        super().__init__(**kwargs)
        self.input = CenteredTextInput(font_size=F.BODY, foreground_color=C.TEXT, background_color=C.BG_INPUT,
                                       cursor_color=C.PRIMARY, multiline=False, write_tab=False, size_hint_x=1)
        if max_length:
            self.input.input_filter = lambda text, _undo: text[:max(0, max_length - len(self.input.text))]
        # 84 dp: the button's 2 x 12 dp padding and 26 dp icon leave 34 dp, room for "Save" on one line.
        save = StyledButton(text="Save", icon=Icons.CHECK, bg_color=C.ACCENT, font_size=F.SMALL,
                            size_hint_x=None, width=dp(84), size_hint_y=1)
        self.add_widget(self.input)
        self.add_widget(save)
        save.bind(on_release=lambda *_a: on_save())
        self.input.bind(on_text_validate=lambda *_a: on_save())

    def focus_soon(self) -> None:
        # A tap's own touch-up unfocuses every input it didn't land on (the pencil's tap too): focus a frame later.
        Clock.schedule_once(self._focus_if_shown)

    def _focus_if_shown(self, _dt) -> None:
        if self.parent is not None:  # closed in between: a keyboard for a field nobody sees
            self.input.focus = True

    def close(self) -> None:
        self.input.focus = False
        if self.parent is not None:
            self.parent.remove_widget(self)


class PresetRow(BoxLayout):
    """Row of quick-pick value buttons for a slider or action.

    Two APIs:
        # numeric presets
        presets = PresetRow(values=[30, 50, 70], callback=slider_set, fmt="{}")

        # labelled presets (allows non-numeric entries like "Free")
        presets = PresetRow(
            items=[("5 min", 5), ("Free", None)],
            callback=handler,
        )

    Optional selection highlight:
        presets.set_selected(5)      # highlights the "5 min" button
        presets.set_selected(None)   # highlights "Free" if present, else clears all
    """

    def __init__(self, values=None, items=None, callback=None, fmt="{}", **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(28))
        kwargs.setdefault("spacing", S.GAP_SM)
        super().__init__(**kwargs)

        if items is None:
            if values is None:
                raise ValueError("PresetRow requires either 'values' or 'items'")
            items = [(fmt.format(v), v) for v in values]

        self._buttons: dict = {}
        self._default_bg = C.BG_CARD
        self._default_text = C.TEXT_MUTED
        self._selected_bg = C.ACCENT
        self._selected_text = None  # AUTO on the accent fill

        for label, value in items:
            btn = StyledButton(
                text=label,
                bg_color=self._default_bg,
                text_color=self._default_text,
                font_size=F.TINY,
                height=dp(26),
                bold=False,
            )
            btn._preset_value = value
            if callback:
                btn.bind(on_release=lambda b, cb=callback, val=value: cb(val))
            self._buttons[value] = btn
            self.add_widget(btn)

    def buttons(self) -> dict:
        """Each button by the value it picks."""
        return dict(self._buttons)

    def set_selected(self, value) -> None:
        """Highlight the button whose stored value equals `value`; clear others.

        If `value` is not a key, all buttons are un-highlighted.
        """
        for key, btn in self._buttons.items():
            if key == value:
                btn.bg_color = self._selected_bg
                btn.text_color = self._selected_text
                btn.bold = True
            else:
                btn.bg_color = self._default_bg
                btn.text_color = self._default_text
                btn.bold = False


class StatRows:
    """A session's (title, value) rows in `container`, as tall as its lines: the row widgets come from `make_row` as
    needed and are kept, since a session that saved no metric has one threshold row where the others have two.
    `make_row` returns (the widgets the row adds to the container, its title label, its value label)."""

    def __init__(self, container, make_row: Callable[[], tuple[Sequence, ThemedLabel, ThemedLabel]],
                 line_h: float) -> None:
        self.container = container
        self._make_row = make_row
        self._line_h = line_h
        self._pool: list[tuple[Sequence, ThemedLabel, ThemedLabel]] = []
        self.rows: list[tuple[ThemedLabel, ThemedLabel]] = []  # (title, value) of the rows shown, in order

    def show(self, rows: list[tuple[str, str]]) -> None:
        """These (title, value) rows, the container as tall as they are."""
        while len(self._pool) < len(rows):
            self._pool.append(self._make_row())
        box = self.container
        box.clear_widgets()
        used = self._pool[:len(rows)]
        for (text, shown), (widgets, title, value) in zip(rows, used):
            title.text, value.text = text, shown
            for widget in widgets:
                box.add_widget(widget)
        self.rows = [(title, value) for _widgets, title, value in used]
        gap = box.spacing[1] if isinstance(box.spacing, (list, tuple)) else box.spacing  # a grid's is (x, y)
        n = len(rows)
        box.height = n * self._line_h + max(n - 1, 0) * gap + box.padding[1] + box.padding[3]
