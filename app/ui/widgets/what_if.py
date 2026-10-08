"""The session detail's what-if panel (#50): a threshold slider, -/+ and Reset over the time above threshold and the
longest streak the session's ticks give at it. It starts as recorded; moving it applies one threshold to every tick.
View only: nothing is written."""

import math
from collections.abc import Callable

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.slider import Slider

from app.session.what_if import ScoredTicks, rescore
from app.ui.theme import C, F, S, StyledButton, ThemedLabel, format_duration

_ROW_H = dp(20)


class WhatIfPanel(BoxLayout):
    def __init__(self, on_threshold: Callable[[float | None], None], **kwargs) -> None:
        super().__init__(orientation="vertical", size_hint_y=None, spacing=dp(4), **kwargs)
        self.bind(minimum_height=self.setter("height"))
        self._on_threshold = on_threshold  # the graph's line: a value, or None for the recorded line
        self._ticks: ScoredTicks | None = None
        self._recorded_target = 0.0
        self._override: float | None = None  # None: as recorded
        self._setting = False  # a value set by the panel itself is not a what-if

        header = BoxLayout(size_hint_y=None, height=dp(28), spacing=S.GAP)
        title = ThemedLabel(text="Try another threshold", font_size=F.SMALL, bold=True, color=C.TEXT_SECONDARY,
                            halign="left", valign="middle", shorten=True, shorten_from="right")
        title.bind(size=title.setter("text_size"))
        self._btn_reset = StyledButton(text="Reset", font_size=F.SMALL, bg_color=C.BG_CARD,
                                       text_color=C.TEXT_SECONDARY, size_hint=(None, None), width=dp(64),
                                       height=dp(28))
        self._btn_reset.bind(on_release=lambda *_a: self.reset())
        header.add_widget(title)
        header.add_widget(self._btn_reset)
        self.add_widget(header)

        self._recorded_label = ThemedLabel(text="", font_size=F.SMALL, color=C.TEXT_SECONDARY, halign="left",
                                           valign="middle", shorten=True, shorten_from="right", size_hint_y=None,
                                           height=_ROW_H)
        self._recorded_label.bind(size=self._recorded_label.setter("text_size"))

        slider_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=S.GAP_SM)
        minus = StyledButton(text="−", font_size=F.H2, bg_color=C.BG_CARD, size_hint_x=None, width=dp(44))
        plus = StyledButton(text="+", font_size=F.H2, bg_color=C.BG_CARD, size_hint_x=None, width=dp(44))
        minus.bind(on_release=lambda *_a: self._step(-5))
        plus.bind(on_release=lambda *_a: self._step(5))
        self._slider = Slider(min=0, max=180, step=1, value=0)
        self._slider.bind(value=self._on_slider)
        self._value_label = ThemedLabel(text="", font_size=F.H3, bold=True, color=C.TEXT, size_hint_x=None,
                                        width=dp(56))
        for w in (minus, self._slider, self._value_label, plus):
            slider_row.add_widget(w)

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
        self._controls = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        self._controls.bind(minimum_height=self._controls.setter("height"))
        for w in (self._recorded_label, slider_row, results):
            self._controls.add_widget(w)
        self._message = ThemedLabel(text="", font_size=F.BODY, color=C.TEXT_SECONDARY, size_hint_y=None,
                                    height=dp(28))
        # One recompute per frame, however fast the slider moves (a 3 h session is 21,600 ticks).
        self._recompute_trigger = Clock.create_trigger(lambda _dt: self._recompute(), 0)
        self._show_message("")

    def _show(self, content) -> None:
        """The controls or the message under the header, the other one detached (never hidden in place)."""
        for w in (self._controls, self._message):
            if w is not content and w.parent is self:
                self.remove_widget(w)
        if content.parent is None:
            self.add_widget(content)

    def _show_message(self, text: str) -> None:
        """A message in place of the controls: no session to rescore, so Reset has nothing to do either."""
        self._ticks = None
        self._override = None
        self._btn_reset.disabled = True
        self._message.text = text
        self._show(self._message)

    def show_loading(self) -> None:
        self._show_message("Loading…")

    def show_load_failed(self) -> None:
        self._show_message("Couldn't load this session's data.")

    def set_session(self, ticks: ScoredTicks | None, recorded_target: float, recorded_text: str,
                    unavailable: str = "") -> None:
        """Show a session as recorded, or, for one it can't rescore (None), `unavailable` in place of the controls."""
        if ticks is None:
            self._show_message(unavailable)
            return
        self._ticks = ticks
        self._recorded_label.text = f"Recorded at {recorded_text} · nothing is saved"
        self._show(self._controls)
        self._recorded_target = recorded_target
        self._override = None
        self._setting = True
        # Room for every value and the recorded target: a formula can go below 0 or past the usual 180.
        self._slider.min = min(0, math.floor(min(ticks.values, default=0)), math.floor(recorded_target))
        self._slider.max = max(180, math.ceil(max(ticks.values, default=0)), math.ceil(recorded_target))
        self._slider.value = recorded_target
        self._setting = False
        self._value_label.text = f"{recorded_target:g}"
        self._recompute()

    def reset(self) -> None:
        """Back to the session as recorded: its own targets, and the graph's recorded line."""
        if self._ticks is None:
            return
        self._setting = True
        self._slider.value = self._recorded_target
        self._setting = False
        self._value_label.text = f"{self._recorded_target:g}"
        self._override = None
        self._recompute()
        self._on_threshold(None)

    def _step(self, delta: int) -> None:
        s = self._slider
        s.value = max(s.min, min(s.max, int(s.value) + delta))

    def _on_slider(self, _slider, value) -> None:
        self._value_label.text = f"{int(value)}"
        if self._setting:
            return
        self._override = int(value)
        self._recompute_trigger()

    def _recompute(self) -> None:
        ticks = self._ticks
        if ticks is None:
            return
        segments = ticks.segments
        targets = [s.target for s in segments] if self._override is None else [self._override] * len(segments)
        total, _ = rescore(ticks, targets, per_segment=False)
        self._time_above.text = format_duration(int(total.time_above))
        self._streak.text = format_duration(int(total.longest_streak))
        self._btn_reset.disabled = self._override is None
        if self._override is not None:
            self._on_threshold(self._override)
