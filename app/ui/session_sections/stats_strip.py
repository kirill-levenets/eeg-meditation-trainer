"""The Session screen's stats strip: three slots on the metric the session is scored on, and the LIVE / AVG switch."""
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app.session.manager import NO_SCORE, LiveScore
from app.ui.formatting import format_duration
from app.ui.hooks import Hook
from app.ui.session_labels import average_text
from app.ui.theme import C, Card, F, ThemedLabel
from app.ui.widgets.choice_toggle import ChoiceToggle


def _format_stats_slots(mode: str, name: str, score: LiveScore) -> tuple[list[str], list[str]]:
    """(titles, values) of the stats bar's three slots, on the metric the session is scored on: LIVE, its value, the
    target and the streak now; AVG, the end card's numbers so far (a program's average is its running segment's)."""
    if mode == "aggregate":
        average = "-" if score.average is None else average_text(score.average)
        return (["Segment avg" if score.segmented else "Average", "On target", "Best streak"],  # History's words
                [average, format_duration(int(score.time_above)), format_duration(int(score.longest_streak))])
    value = "-" if score.value is None else str(int(round(score.value)))
    target = "-" if score.target is None else f"{score.target:g}"
    return [name, "Target", "Streak"], [value, target, format_duration(int(score.streak))]


class StatsStrip(Card):
    """The last `LiveScore` handed to it, as live values or session averages; the first title is the scored series'
    name on `graph`."""

    on_mode = Hook()  # the view picked: "live" or "aggregate"

    def __init__(self, graph) -> None:
        super().__init__(orientation="horizontal", size_hint_y=None, height=dp(64), bg_color=C.BG_CARD)
        self._graph = graph
        self._last_score = NO_SCORE  # kept for the LIVE / AVG switch
        self._scored_key: str | None = None  # the series it was scored on, named until the readout clears
        self._titles: list[ThemedLabel] = []
        self._values: list[ThemedLabel] = []
        for slot in range(3):
            box = BoxLayout(orientation="vertical")
            title = ThemedLabel(font_size=F.TINY, color=C.TEXT_MUTED, size_hint_y=0.4)
            if slot == 0:  # the metric's name: a long formula name is cut, not run into the next slot
                title.shorten, title.shorten_from, title.halign, title.valign = True, "right", "center", "middle"
                title.bind(size=title.setter("text_size"))
            value = ThemedLabel(font_size=F.capped(F.H2), bold=True, color=C.TEXT, size_hint_y=0.6)  # "59m 59s"
            box.add_widget(title)
            box.add_widget(value)
            self._titles.append(title)
            self._values.append(value)
            self.add_widget(box)

        self._mode = "live"
        self._toggle = ChoiceToggle([("live", "LIVE"), ("aggregate", "AVG")], "live", self._choose_mode,
                                    button={"size_hint_y": 1, "font_size": F.capped(F.SMALL)},
                                    orientation="vertical", size_hint_x=None, width=dp(56), spacing=dp(2))
        self.add_widget(self._toggle)
        self._render()

    def update(self, score: LiveScore) -> None:
        self._last_score = score
        self._render()

    def set_scored(self, key: str | None) -> None:
        """The series the session is now scored on names the first slot; None keeps the last one's name."""
        if key is not None:
            self._scored_key = key
        self._render()

    def clear(self) -> None:
        """What a fresh screen shows: no session's numbers, "Score" for the name."""
        self._last_score, self._scored_key = NO_SCORE, None
        self._render()

    def _choose_mode(self, mode: str) -> None:
        self.set_mode(mode)
        self.on_mode(self._mode)

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        """Show the strip as live values or session averages, redrawn at once."""
        self._mode = mode if mode in ("live", "aggregate") else "live"
        self._toggle.show(self._mode)
        self._render()

    def _render(self) -> None:
        """The slots on the series the legend marks as scored (kept after the session ends), by its name on the graph."""
        key = self._scored_key
        name = self._graph.series_name(key) if key else "Score"
        titles, values = _format_stats_slots(self._mode, name, self._last_score)
        for title, value, title_text, value_text in zip(self._titles, self._values, titles, values):
            title.text, value.text = title_text, value_text
