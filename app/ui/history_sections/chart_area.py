"""History's chart area: the chart (heatmap or 14-day bars), the period it shows and its paging, and the totals table."""
import datetime

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout

from app.ui import period_totals
from app.ui.formatting import format_duration
from app.ui.history_sections import common
from app.ui.history_sections.charts import CalendarHeatmap, DayChart, Last14DaysBars
from app.ui.hooks import Hook, wire
from app.ui.period_totals import ALL_TIME, period_text, periods_around, session_day
from app.ui.theme import ICONS_AVAILABLE, C, F, Icons, S, ThemedLabel, text_fills_box
from app.ui.widgets.choice_toggle import ChoiceToggle
from app.ui.widgets.styled_button import StyledButton


def _iso_date(text: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


class ChartArea(BoxLayout):
    """Upright, the period row over the chart, the Cal / 14d buttons beside it and the totals table under it; sideways,
    the row and the table beside the chart. It shows the sessions and the picked day its screen gives it."""

    on_day_tap = Hook()  # a day tapped on the chart: "YYYY-MM-DD"
    on_view_mode_change = Hook()  # the user picked "calendar" or "bars"

    _PERIOD_H = dp(28)
    _TOTALS_ROW_H = dp(20)
    _TOTALS_BESIDE_W = dp(290)  # its widest texts: "September 2025" and three "Best streak" columns
    # Beside the chart once the page fits the heatmap at its smallest cells next to the table and the Cal / 14d
    # buttons: ~670 dp, which a landscape phone of ~730 has; narrower, under the chart.
    _TOTALS_BESIDE_FROM = (2 * S.PAGE_PAD + CalendarHeatmap.LEFT_MARGIN
                           + CalendarHeatmap.WEEKS_VISIBLE * (CalendarHeatmap.CELL_SIZE + CalendarHeatmap.CELL_GAP)
                           + _TOTALS_BESIDE_W + dp(40) + 2 * dp(4))

    def __init__(self) -> None:
        super().__init__(orientation="vertical", size_hint_y=None, spacing=S.GAP)
        self.bind(minimum_height=self.setter("height"))
        self._sessions: list[dict] = []  # its screen's, given at every change
        self._picked: str | None = None  # the day the list is filtered to: the totals are around it
        self._view_mode = "calendar"
        self._period_offset = 0  # days from today to the chart's period end: 0 is today's page, a page back below it
        self._first_day: datetime.date | None = None  # the first session's: paging back stops once it is shown
        self._drawn_for: datetime.date | None = None  # the "today" the chart and the totals were last drawn for

        # The chart row: the chart (heatmap OR bars, one parented at a time) under the period row, the Cal / 14d
        # buttons on the right; its height follows the chart (_fit_graph_row).
        self._graph_row = BoxLayout(orientation="horizontal", size_hint_y=None,
                                    height=Last14DaysBars.HEIGHT + self._PERIOD_H, spacing=dp(4))
        self._graph_wrap = BoxLayout(orientation="vertical", size_hint_x=1)
        self._build_period_row()
        self._heatmap = CalendarHeatmap()
        self._bars = Last14DaysBars()  # built but NOT parented until the user toggles to the bars view
        for chart in (self._heatmap, self._bars):
            wire(chart, on_day_tap=lambda day: self.on_day_tap(day), on_swipe=self.shift_period,
                 period_source=lambda: self.period_end)
            chart.bind(height=self._on_active_widget_height)
        self._graph_wrap.add_widget(self._heatmap)
        self._graph_row.add_widget(self._graph_wrap)
        self._toggle_col = ChoiceToggle([("calendar", "Cal"), ("bars", "14d")], "calendar", self._on_toggle_pressed,
                                        button={"font_size": F.SMALL}, orientation="vertical", size_hint_x=None,
                                        width=dp(40), spacing=dp(4))
        self._graph_row.add_widget(self._toggle_col)
        self.add_widget(self._graph_row)
        self._build_totals()
        # Sideways: the period row and the table beside the chart, the row over the table.
        self._side_col = BoxLayout(orientation="vertical", size_hint=(None, None), width=self._TOTALS_BESIDE_W,
                                   pos_hint={"top": 1})
        self._side_col.bind(minimum_height=self._side_col.setter("height"))
        self.place_for(0)  # upright until its page has a width
        self._update_period_row()
        self._update_totals()

    def _build_period_row(self) -> None:
        self._period_row = BoxLayout(size_hint_y=None, height=self._PERIOD_H, spacing=dp(4))
        # 40 dp: an icon-only StyledButton narrower than ~36 dp crops its glyph (see FoldChevron). The glyph is the
        # rows' pencil blue: a disabled button greys it, where a grey one would look the same either way.
        self._btn_prev, self._btn_next = (
            StyledButton(text="" if ICONS_AVAILABLE else fallback, icon=icon, bg_color=C.BG_CARD,
                         text_color=C.PRIMARY, font_size=F.SMALL, size_hint_x=None, width=dp(40),
                         height=self._PERIOD_H)
            for icon, fallback in ((Icons.CHEVRON_LEFT, "‹"), (Icons.CHEVRON_RIGHT, "›")))
        self._period_label = StyledButton(text="", bg_color=C.BG_CARD, text_color=C.TEXT_SECONDARY,
                                          font_size=F.SMALL, bold=False, height=self._PERIOD_H)
        self._btn_prev.bind(on_release=lambda *a: self.shift_period(-1))
        self._btn_next.bind(on_release=lambda *a: self.shift_period(1))
        self._period_label.bind(on_release=lambda *a: self._set_period(0))  # back to today
        for w in (self._btn_prev, self._period_label, self._btn_next):
            self._period_row.add_widget(w)

    def _build_totals(self) -> None:
        """The Day / Week / Month / All time totals table, built once: _update_totals fills its cells."""
        def cell(text: str = "", first: bool = False, muted: bool = False) -> ThemedLabel:
            label = ThemedLabel(text=text, font_size=F.SMALL, color=C.TEXT_SECONDARY if muted else C.TEXT,
                                halign="left" if first else "right", valign="middle", shorten=True,
                                shorten_from="right", size_hint_x=1.5 if first else 1.0)
            text_fills_box(label)
            return label

        self._totals = GridLayout(cols=4, size_hint_y=None, height=5 * self._TOTALS_ROW_H, spacing=(dp(6), 0),
                                  row_default_height=self._TOTALS_ROW_H, row_force_default=True, pos_hint={"top": 1})
        self._totals_header = [cell(text, first=not text, muted=True)
                               for text in ("", "Total", "On target", "Best streak")]
        self._totals_rows = [[cell(first=True), cell(), cell(), cell()] for _ in range(4)]
        for label in self._totals_header + [label for row in self._totals_rows for label in row]:
            self._totals.add_widget(label)

    # ── What it shows ──

    def set_sessions(self, sessions: list[dict]) -> None:
        """Each day's average shamatha on both charts, the first day paging back stops at, and the totals."""
        day_scores: dict[str, list[float]] = {}
        for s in sessions:
            day = session_day(s)
            if len(day) == 10:
                day_scores.setdefault(day, []).append(s.get("avg_shamatha", 0) or 0)
        day_avg = {day: sum(scores) / len(scores) for day, scores in day_scores.items()}
        self._sessions = sessions
        self._first_day = min(filter(None, map(_iso_date, day_avg)), default=None)
        self._drawn_for = common.today()
        self._heatmap.set_data(day_avg)
        self._bars.set_data(day_avg)
        self._update_period_row()
        self._update_totals()

    def pick_day(self, day: str | None) -> None:
        """The day the list is filtered to ("YYYY-MM-DD"), or none: outlined on both charts, the totals around it."""
        self._picked = day
        for chart in (self._heatmap, self._bars):
            chart.select(day)
        self._update_totals()

    def follow_today(self) -> None:
        """Opened on another day than it last drew for: the chart and the totals move on with it."""
        if common.today() != self._drawn_for:
            self.set_sessions(self._sessions)

    def _update_totals(self) -> None:
        """The rows: the picked day's day, week and month (today's when no day is picked), then all time."""
        today = common.today()
        day = datetime.date.fromisoformat(self._picked) if self._picked else today
        for row, (label, start, end) in zip(self._totals_rows, [*periods_around(day, today), ALL_TIME]):
            totals = period_totals.period_totals(self._sessions, start, end)
            row[0].text = label
            for cell, seconds in zip(row[1:], (totals.seconds, totals.on_target, totals.best_streak)):
                cell.text = format_duration(seconds) if totals.sessions else "–"

    def state_text(self) -> str:
        """The chart row's height and the calendar's width (0 or Kivy's 100 while the bars show), for History's log."""
        return f"chart_h={self._graph_row.height:.0f} chart_w={self._heatmap.width:.0f}"

    # ── The period ──

    @property
    def period_end(self) -> datetime.date:
        return common.today() + datetime.timedelta(days=self._period_offset)

    def _active_chart(self) -> DayChart:
        return self._heatmap if self._view_mode == "calendar" else self._bars

    def _can_page_back(self) -> bool:
        return self._first_day is not None and self._active_chart().window(self.period_end)[0] > self._first_day

    def shift_period(self, direction: int) -> None:
        """Page the chart one window earlier (-1) or later (1): back as far as the first session, on as far as today."""
        if direction < 0 and not self._can_page_back():
            return
        end = self._active_chart().step(self.period_end, direction)
        self._set_period(min((end - common.today()).days, 0))

    def to_today(self) -> None:
        """Today's page: another profile's history starts there."""
        self._set_period(0)

    def _set_period(self, offset: int) -> None:
        """Days back from today: a page stays as far back as the day moves on, still meeting today's."""
        self._period_offset = offset
        for chart in (self._heatmap, self._bars):  # the one off screen draws when it is back
            chart.redraw()
        self._update_period_row()

    def _update_period_row(self) -> None:
        self._period_label.text = period_text(*self._active_chart().window(self.period_end), common.today())
        self._btn_prev.disabled = not self._can_page_back()
        self._btn_next.disabled = self._period_offset == 0

    # ── The view and the layout ──

    @property
    def view_mode(self) -> str:
        return self._view_mode

    def set_view_mode(self, mode: str) -> None:
        """Switch between 'calendar' and 'bars': the other chart is parented in the chart's place (a BoxLayout lays out
        again only when its children change), and the layout cascades at once, with no stale frame."""
        if mode not in ("calendar", "bars"):
            return
        self._view_mode = mode
        for chart in (self._heatmap, self._bars):  # the period row above stays
            if chart.parent is not None:
                self._graph_wrap.remove_widget(chart)
        self._update_period_row()  # the same period end, the other view's window
        if mode == "calendar":
            self._heatmap.height = self._heatmap.fitted_height()
            self._graph_wrap.add_widget(self._heatmap)
        else:
            self._bars.height = Last14DaysBars.HEIGHT
            self._graph_wrap.add_widget(self._bars)
        self._toggle_col.show(mode)
        self._active_chart().redraw()  # it didn't draw while off screen
        self._fit_graph_row()
        self._cascade_layout()

    def _on_toggle_pressed(self, mode: str) -> None:
        self.set_view_mode(mode)
        self.on_view_mode_change(mode)

    def place_for(self, page_width: float) -> None:
        """Upright, the period row over the chart and the table under it. Sideways, where under the chart the list had
        no room, both beside it: the chart is taller than the table, which leaves the row the room over it. It follows
        the page's width, folded away too, so the area comes back laid out for the page it returns to."""
        beside = page_width >= self._TOTALS_BESIDE_FROM
        if self._totals.parent is (self._side_col if beside else self):
            return
        for w in (self._totals, self._period_row, self._side_col):
            if w.parent is not None:
                w.parent.remove_widget(w)
        if beside:
            self._side_col.add_widget(self._period_row)
            self._side_col.add_widget(self._totals)
            self._graph_row.add_widget(self._side_col, index=1)  # between the chart and the Cal / 14d buttons
        else:
            self._graph_wrap.add_widget(self._period_row, index=len(self._graph_wrap.children))  # over the chart
            self.add_widget(self._totals)  # under the chart
        self._fit_graph_row()

    def _on_active_widget_height(self, chart, height) -> None:
        """The parented chart's height (the heatmap's cells follow the width) is the chart row's."""
        if chart.parent is None or height <= 0:
            return
        self._fit_graph_row()

    def _fit_graph_row(self) -> None:
        """The chart's height, plus the period row's where it sits over the chart."""
        height = self._active_chart().height + (self._PERIOD_H if self._period_row.parent is self._graph_wrap else 0)
        if height != self._graph_row.height:
            self._graph_row.height = height
            self._cascade_layout()

    def _cascade_layout(self) -> None:
        """Lay out at once from the page down to the chart (a BoxLayout lays out again only when its own size,
        position or children change), so a new height shows now, not at the next window resize."""
        if self.parent is not None:
            self.parent.do_layout()
        self.do_layout()
        self._graph_row.do_layout()
        self._graph_wrap.do_layout()
        if self._side_col.parent is not None:
            self._side_col.do_layout()
