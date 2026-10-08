"""The session detail's what-if panel (#50): threshold controls, -/+ and Reset over the time above threshold and the
longest streak the session's ticks give at them — one control for a simple session, one per segment for a program,
each with its own stats. It starts as recorded; a moved control applies its threshold to every tick of its segment.
View only: nothing is written."""

import math
from collections.abc import Callable

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.slider import Slider
from kivy.uix.widget import Widget

from app.session.what_if import ScoredTicks, Segment, Stats, line_steps, rescore
from app.ui.theme import (
    C,
    F,
    FoldChevron,
    S,
    StyledButton,
    ThemedLabel,
    format_duration,
)

_ROW_H = dp(20)


def _secondary(text: str = "") -> ThemedLabel:
    label = ThemedLabel(text=text, font_size=F.SMALL, color=C.TEXT_SECONDARY, halign="left", valign="middle",
                        shorten=True, shorten_from="right", size_hint_y=None, height=_ROW_H)
    label.bind(size=label.setter("text_size"))
    return label


class _SegmentControl(BoxLayout):
    """One segment's threshold: -5, a slider, its value, +5; a program's segment also has its title and its stats."""

    def __init__(self, segment: Segment, reach: list[float], on_value: Callable[["_SegmentControl", int], None],
                 title: str = "") -> None:
        super().__init__(orientation="vertical", size_hint_y=None, spacing=dp(2))
        self.bind(minimum_height=self.setter("height"))
        self.recorded = segment.target
        self._on_value = on_value
        self._setting = False  # a value set by the panel itself is not a what-if
        self.title = _secondary(title) if title else None
        self.stats = _secondary() if title else None

        row = BoxLayout(size_hint_y=None, height=dp(40), spacing=S.GAP_SM)
        minus = StyledButton(text="−", font_size=F.H2, bg_color=C.BG_CARD, size_hint_x=None, width=dp(44))
        plus = StyledButton(text="+", font_size=F.H2, bg_color=C.BG_CARD, size_hint_x=None, width=dp(44))
        minus.bind(on_release=lambda *_a: self.step(-5))
        plus.bind(on_release=lambda *_a: self.step(5))
        # Room for every value and recorded target in `reach`: a formula can go below 0 or past the usual 180.
        self.slider = Slider(step=1, min=min(0, math.floor(min(reach, default=0)), math.floor(segment.target)),
                             max=max(180, math.ceil(max(reach, default=0)), math.ceil(segment.target)))
        self.slider.bind(value=self._on_slider)
        self.value_label = ThemedLabel(text="", font_size=F.H3, bold=True, color=C.TEXT, size_hint_x=None,
                                       width=dp(56))
        for w in (minus, self.slider, self.value_label, plus):
            row.add_widget(w)
        for w in (self.title, row, self.stats):
            if w is not None:
                self.add_widget(w)
        self.show_recorded()

    def show_recorded(self) -> None:
        self._setting = True
        self.slider.value = self.recorded
        self._setting = False
        self.value_label.text = f"{self.recorded:g}"

    def show_stats(self, stats: Stats) -> None:
        if self.stats is not None:
            self.stats.text = (f"Above {format_duration(int(stats.time_above))} · "
                               f"Streak {format_duration(int(stats.longest_streak))}")

    def step(self, delta: int) -> None:
        s = self.slider
        s.value = max(s.min, min(s.max, int(s.value) + delta))

    def _on_slider(self, _slider, value) -> None:
        self.value_label.text = f"{int(value)}"
        if not self._setting:
            self._on_value(self, int(value))


class WhatIfPanel(BoxLayout):
    def __init__(self, on_threshold: Callable[[list[tuple[int, float]] | None], None], **kwargs) -> None:
        super().__init__(orientation="vertical", size_hint_y=None, spacing=dp(4), **kwargs)
        self.bind(minimum_height=self.setter("height"))
        self._on_threshold = on_threshold  # the graph's line: its steps, or None for the recorded line
        self._ticks: ScoredTicks | None = None
        self._overrides: list[float | None] = []  # per segment; None: as recorded
        self._seg_controls: list[_SegmentControl] = []
        self._per_segment = False  # a program's segments show their own stats
        self._collapsed = False
        self._on_collapse: Callable[[bool], None] | None = None

        # The title, its chevron right after it (History's fold), and Reset, which stays in reach while folded.
        header = BoxLayout(size_hint_y=None, height=dp(28), spacing=S.GAP_SM)
        self._title = ThemedLabel(text="Try another threshold", font_size=F.SMALL, bold=True,
                                  color=C.TEXT_SECONDARY, size_hint_x=None)
        self._title.bind(texture_size=lambda w, ts: setattr(w, "width", ts[0]))
        self._btn_collapse = FoldChevron(size_hint_y=None, height=dp(28))
        self._btn_collapse.bind(on_release=lambda *_a: self.toggle_collapsed())
        self._btn_reset = StyledButton(text="Reset", font_size=F.SMALL, bg_color=C.BG_CARD,
                                       text_color=C.TEXT_SECONDARY, size_hint=(None, None), width=dp(64),
                                       height=dp(28))
        self._btn_reset.bind(on_release=lambda *_a: self.reset())
        for w in (self._title, self._btn_collapse, Widget(), self._btn_reset):
            header.add_widget(w)
        self.add_widget(header)

        self._note = _secondary()
        self._segments_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        self._segments_box.bind(minimum_height=self._segments_box.setter("height"))

        # The detail's stats grid's padding and spacing, so the values line up under its values.
        results = GridLayout(cols=2, size_hint_y=None, height=2 * _ROW_H + dp(4), spacing=dp(4),
                             padding=(dp(4), 0, dp(4), 0))

        def row(text: str) -> ThemedLabel:
            # As the session detail's stats rows: the title takes its text's width, the value the rest.
            label = ThemedLabel(text=text, font_size=F.SMALL, color=C.TEXT_SECONDARY, size_hint=(None, None),
                                height=_ROW_H)
            label.bind(texture_size=lambda w, ts: setattr(w, "width", ts[0] + S.GAP))
            value = ThemedLabel(text="", font_size=F.H3, bold=True, color=C.TEXT, halign="left", valign="middle",
                                size_hint_y=None, height=_ROW_H)
            value.bind(size=value.setter("text_size"))
            results.add_widget(label)
            results.add_widget(value)
            return value

        self._time_above = row("Time Above Threshold")
        self._streak = row("Longest Streak")
        self._results = results
        self._total_title = _secondary("Whole session")  # a program's totals, under its segments' own
        self._controls = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        self._controls.bind(minimum_height=self._controls.setter("height"))
        for w in (self._note, self._segments_box, results):
            self._controls.add_widget(w)
        self._message = ThemedLabel(text="", font_size=F.BODY, color=C.TEXT_SECONDARY, size_hint_y=None,
                                    height=dp(28))
        # One recompute per frame, however fast a slider moves (a 3 h session is 21,600 ticks).
        self._recompute_trigger = Clock.create_trigger(lambda _dt: self._recompute(), 0)
        self._content = self._message
        self._show_message("")

    def _show(self, content) -> None:
        """The controls or the message under the header, the other one detached (never hidden in place); neither
        while folded."""
        self._content = content
        for w in (self._controls, self._message):
            if (w is not content or self._collapsed) and w.parent is self:
                self.remove_widget(w)
        if not self._collapsed and content.parent is None:
            self.add_widget(content)

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        """Fold the body away, detached, or bring back what it shows; the header stays."""
        self._collapsed = collapsed
        self._show(self._content)
        self._btn_collapse.show_folded(collapsed)

    def set_collapse_callback(self, cb: Callable[[bool], None]) -> None:
        self._on_collapse = cb

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)
        if self._on_collapse:
            self._on_collapse(self._collapsed)

    def _show_message(self, text: str) -> None:
        """A message in place of the controls: no session to rescore, so Reset has nothing to do either."""
        self._ticks = None
        self._overrides = []
        self._seg_controls = []
        self._segments_box.clear_widgets()
        self._btn_reset.disabled = True
        self._message.text = text
        self._show(self._message)

    def show_loading(self) -> None:
        self._show_message("Loading…")

    def show_load_failed(self) -> None:
        self._show_message("Couldn't load this session's data.")

    def set_session(self, ticks: ScoredTicks | None, note: str, titles: list[str] | None = None,
                    unavailable: str = "") -> None:
        """Show a session as recorded — one control, or with `titles` one per segment with its own stats — or, for
        one it can't rescore (None), `unavailable` in place of the controls."""
        if ticks is None:
            self._show_message(unavailable)
            return
        self._ticks = ticks
        self._overrides = [None] * len(ticks.segments)
        self._per_segment = titles is not None
        self._note.text = note
        self._segments_box.clear_widgets()
        self._seg_controls = [
            _SegmentControl(segment, [*ticks.values[segment.start:segment.end], *ticks.targets[segment.start:segment.end]],
                            self._on_value, titles[i] if titles else "")
            for i, segment in enumerate(ticks.segments)]
        for control in self._seg_controls:
            self._segments_box.add_widget(control)
        if self._per_segment and self._total_title.parent is None:
            self._controls.add_widget(self._total_title, index=self._controls.children.index(self._results) + 1)
        elif not self._per_segment and self._total_title.parent is not None:
            self._controls.remove_widget(self._total_title)
        self._show(self._controls)
        self._recompute()

    def reset(self) -> None:
        """Back to the session as recorded: its own targets, and the graph's recorded line."""
        if self._ticks is None:
            return
        self._overrides = [None] * len(self._overrides)
        for control in self._seg_controls:
            control.show_recorded()
        self._recompute()
        self._on_threshold(None)

    def _on_value(self, control: _SegmentControl, value: int) -> None:
        if control not in self._seg_controls:
            return  # the last session's control, moved after the panel did
        self._overrides[self._seg_controls.index(control)] = value
        self._recompute_trigger()

    def _recompute(self) -> None:
        ticks = self._ticks
        if ticks is None:
            return
        total, per_segment = rescore(ticks, self._overrides, per_segment=self._per_segment)
        self._time_above.text = format_duration(int(total.time_above))
        self._streak.text = format_duration(int(total.longest_streak))
        for control, stats in zip(self._seg_controls, per_segment):
            control.show_stats(stats)
        moved = any(o is not None for o in self._overrides)
        self._btn_reset.disabled = not moved
        if moved:
            self._on_threshold(line_steps(ticks, self._overrides))
