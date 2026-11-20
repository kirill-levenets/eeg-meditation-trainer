"""The Session screen's end card: the saved session's name and stats, a notes field, Delete and OK."""
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from app.ui.session_labels import session_score_rows
from app.ui.theme import (
    C,
    Card,
    F,
    Icons,
    ModalPanel,
    ModalScrim,
    S,
    StyledButton,
    ThemedLabel,
    ThemedTextInput,
    fit_width_to_text,
    format_duration,
    text_width,
)


def _cut_to_width(text: str, label) -> str:
    """`text`, or its longest start plus an ellipsis, no wider than `label` at its font."""
    def width(s: str) -> float:
        return text_width(s, label.font_size, label.bold)

    if width(text) <= label.width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if width(text[:mid].rstrip() + "…") <= label.width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "…"


class EndCard(ModalScrim):
    """The theme's modal panel over the dimmed screen, like every popup.
    Shown by attaching it to `host`, hidden by detaching: invisible attached buttons swallowed Start/Stop taps."""

    def __init__(self, host) -> None:
        super().__init__(size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
                         padding=[dp(20), dp(6)])  # tight vertically: a landscape phone has ~314 dp above the bottom nav
        self._host = host
        self._session_id: int | None = None
        # Every ending saves the session; the title says so, and names the session (_fit_title).
        panel = ModalPanel(title="Session saved")
        self._panel = panel
        self._title = panel.title_label
        self._session_title = ""
        self._title.bind(width=self._fit_title, font_size=self._fit_title)

        # Stats card: one (label, value) row per stat, set by show — a session that saved no metric has one
        # threshold row where the others have Metric and Threshold. Lines are 22 dp with no gap between them.
        self._stats_card = Card(
            orientation="vertical",
            size_hint_y=None,
            bg_color=C.BG_CARD,
            spacing=0,
        )
        self._line_h = dp(22)
        self._row_pool: list[tuple[BoxLayout, ThemedLabel, ThemedLabel]] = []
        self._rows: list[tuple[ThemedLabel, ThemedLabel]] = []  # (label, value) of the rows shown, in order

        # The stats, then the notes field and Save notes: arranged by _arrange in one column or two.
        self._body = BoxLayout(size_hint_y=None, spacing=S.GAP)
        self._notes_box = BoxLayout(size_hint_y=None, spacing=S.GAP)
        self._notes = ThemedTextInput(
            hint_text="Quick notes: how was the session?",
            multiline=True,
            font_size=F.BODY,
            foreground_color=C.TEXT,
            background_color=C.BG_INPUT,
            cursor_color=C.PRIMARY,
        )
        self.save_notes_btn = StyledButton(
            text="Save notes", bg_color=C.PRIMARY, bg_pressed=C.PRIMARY_DIM,
            size_hint_x=None, width=dp(110),
        )
        self._save_holder = AnchorLayout(anchor_x="right", size_hint_y=None, height=S.BTN_H)
        self._save_holder.add_widget(self.save_notes_btn)
        self._notes_box.add_widget(self._notes)
        self._notes_box.add_widget(self._save_holder)
        self._body.add_widget(self._stats_card)
        self._body.add_widget(self._notes_box)
        panel.add_widget(self._body)
        self._set_rows([])
        panel.bind(width=self._arrange)
        F.add_listener(self._arrange)  # the notes field's height follows its text

        # Delete is low-emphasis and kept apart from OK: it is the one destructive action here.
        buttons = BoxLayout(size_hint_y=None, height=S.BTN_H, spacing=S.GAP)
        self.delete_btn = StyledButton(
            text="Delete session", icon=Icons.DELETE,
            bg_color=C.BG_CARD, text_color=C.DANGER,
            size_hint_x=None, width=dp(150),
        )
        self.ok_btn = StyledButton(
            text="OK", icon=Icons.CHECK,
            bg_color=C.ACCENT, bg_pressed=C.ACCENT_DIM,
            size_hint_x=None, width=dp(120),
        )
        buttons.add_widget(self.delete_btn)
        buttons.add_widget(Widget())
        buttons.add_widget(self.ok_btn)
        panel.add_widget(buttons)
        # As tall as the card when it fits, else the space there is, scrolling the rest: like every popup's cap.
        scroll = ScrollView(size_hint=(1, None), do_scroll_x=False)
        scroll.add_widget(panel)
        self._scroll = scroll

        def _fit_scroll(*_a):
            pad = self.padding
            scroll.height = min(panel.height, max(0, self.height - pad[1] - pad[3]))

        panel.bind(height=_fit_scroll)
        self.bind(height=_fit_scroll, padding=_fit_scroll)
        self.add_widget(scroll)

    def show(self, session_id: int, stats: dict, title: str = "") -> None:
        """Show the post-session card: the session's name, its duration and scored stats, and a notes field."""
        self._session_id = session_id
        self._session_title = title
        self._fit_title()
        self._set_rows([
            ("Duration", format_duration(int(stats.get("duration", 0) or 0))),
            *session_score_rows(stats),  # the scored metric, its average and threshold
            ("Time Above Threshold", format_duration(int(stats.get("time_above_threshold", 0) or 0))),
            ("Longest Streak", format_duration(int(stats.get("longest_streak", 0) or 0))),
        ])
        self._notes.text = ""
        self._scroll.scroll_y = 1  # each card opens at its title, wherever the last one was scrolled to
        if self.parent is None:
            self._host.add_widget(self)

    def _fit_title(self, *_a) -> None:
        """"Session saved · <name>" on one line over two columns, else the name on a line of its own under it; a name
        too long for its line is cut with an ellipsis, so the title never takes more lines than that."""
        title, name = self._title, self._session_title
        if not name:
            title.text = "Session saved"
        elif self._in_two_columns(title.width):  # the title spans the card's inside, as the columns do
            title.text = _cut_to_width(f"Session saved · {name}", title)
        else:
            title.text = "Session saved\n" + _cut_to_width(name, title)

    def _make_row(self) -> tuple[BoxLayout, ThemedLabel, ThemedLabel]:
        row = BoxLayout(size_hint_y=None, height=self._line_h)
        # The label takes its text's width and the value the rest: a Metric value can be longer than its label.
        label = ThemedLabel(text="", font_size=F.BODY, color=C.TEXT_SECONDARY, size_hint_x=None)
        fit_width_to_text(label, S.GAP)
        value = ThemedLabel(text="-", font_size=F.BODY, bold=True, color=C.TEXT, halign="right", valign="middle",
                            shorten=True, shorten_from="right")
        value.bind(size=value.setter("text_size"))
        row.add_widget(label)
        row.add_widget(value)
        return row, label, value

    def _set_rows(self, rows: list[tuple[str, str]]) -> None:
        """Show these (label, value) rows under the session's name; the card is as tall as its lines."""
        card = self._stats_card
        while len(self._row_pool) < len(rows):
            self._row_pool.append(self._make_row())
        for box, _label, _value in self._row_pool:
            if box.parent is not None:
                card.remove_widget(box)
        used = self._row_pool[:len(rows)]
        for (text, shown), (box, label, value) in zip(rows, used):
            label.text, value.text = text, shown
            card.add_widget(box)
        self._rows = [(label, value) for _box, label, value in used]
        lines = len(rows)
        card.height = lines * self._line_h + max(lines - 1, 0) * card.spacing + card.padding[1] + card.padding[3]
        self._arrange()

    @staticmethod
    def _in_two_columns(inner_width: float) -> bool:
        """Two columns from 520 dp inside the card: a landscape phone has ~670 dp there, a portrait one ~300."""
        return inner_width >= dp(520)

    def _arrange(self, *_a) -> None:
        """Two columns on a wide card (a landscape phone): the stats left, the notes field over Save notes right, which
        gives the notes a few lines and keeps OK well inside the screen. Else one column: the stats, then the notes
        field as tall as Save notes beside it. Delete and OK stay under both."""
        panel, card, body, box, holder = (self._panel, self._stats_card, self._body, self._notes_box,
                                          self._save_holder)
        two = self._in_two_columns(panel.width - panel.padding[0] - panel.padding[2])
        if two:
            body.orientation, body.height = "horizontal", card.height
            box.orientation, box.height = "vertical", card.height
            holder.size_hint_x = 1
        else:
            body.orientation, body.height = "vertical", card.height + S.GAP + self._notes_h()
            box.orientation, box.height = "horizontal", self._notes_h()
            holder.size_hint_x, holder.width = None, self.save_notes_btn.width

    @staticmethod
    def _notes_h() -> float:
        return F.box(44)  # two lines of the notes field's text, at any text size

    def hide(self) -> None:
        if self.parent is not None:
            self.parent.remove_widget(self)
        self._session_id = None

    @property
    def notes(self) -> str:
        return self._notes.text.strip()

    @property
    def session_id(self) -> int | None:
        return self._session_id
