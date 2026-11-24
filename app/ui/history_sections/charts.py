"""History's charts, one period at a time: the day heatmap and the 14-day bars. A tap reports a day, a swipe pages."""
import datetime
import math

from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.widget import Widget

from app.ui.history_sections import common
from app.ui.history_sections.common import score_colour
from app.ui.hooks import Hook
from app.ui.theme import C, F, ThemedLabel
from app.ui.touch_utils import point_in_rect

_SWIPE = dp(40)  # a sideways move this long pages the chart
_TAP_SLOP = dp(20)  # a fingertip's drift: a press that moves less is still a tap


class DayChart(Widget):
    """Days, one period at a time: a tap reports a day on the lift (so a swipe that starts on a day reports none) and a
    sideways swipe pages. Subclasses `_draw` `window(end)` for the period end their owner gives, each day through
    `_draw_cell`; a chart off screen doesn't draw until it is back."""

    on_day_tap = Hook()
    on_swipe = Hook()
    period_source = Hook()  # the owner's period end; today without one

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint_y = None
        self._day_values: dict[str, float] = {}  # "YYYY-MM-DD" -> avg_shamatha
        self._cell_positions: dict[str, tuple] = {}  # each shown day's rect, in date order, as last drawn
        self._selected_date: str | None = None
        self.bind(size=self.redraw, pos=self.redraw)
        C.add_listener(self.redraw)
        F.add_listener(self.redraw)

    @classmethod
    def window(cls, end: datetime.date) -> tuple[datetime.date, datetime.date]:
        """(first, last) day shown for a period ending at `end`."""
        raise NotImplementedError

    @classmethod
    def step(cls, end: datetime.date, direction: int) -> datetime.date:
        """The period end one window later (1) or earlier (-1)."""
        raise NotImplementedError

    def _shown_window(self) -> tuple[datetime.date, datetime.date]:
        return self.window(self.period_source() or common.today())

    def set_data(self, day_values: dict[str, float]) -> None:
        self._day_values = day_values
        self.redraw()

    def select(self, day: str | None) -> None:
        """Outline this day ("YYYY-MM-DD"), or none: the day the list is filtered to."""
        self._selected_date = day
        self.redraw()

    def on_touch_down(self, touch):
        if touch.is_mouse_scrolling or not self.collide_point(*touch.pos):  # a wheel tick is no tap
            return super().on_touch_down(touch)
        touch.grab(self)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_up(touch)
        touch.ungrab(self)
        dx, dy = touch.x - touch.ox, touch.y - touch.oy
        if abs(dx) >= _SWIPE and abs(dx) > abs(dy):
            self.on_swipe(-1 if dx > 0 else 1)  # dragging the days right brings earlier ones in
        elif math.hypot(dx, dy) <= _TAP_SLOP:
            self._tap_day(touch.ox, touch.oy)  # where the finger came down: it aimed there
        return True

    def _tap_day(self, x: float, y: float) -> None:
        day = next((d for d, rect in self._cell_positions.items() if point_in_rect(x, y, rect)), None)
        if day is not None:
            self.on_day_tap(day)  # the owner's filter selects it

    def redraw(self, *args) -> None:
        """Draw now; a chart off screen draws when it is back."""
        if self.parent is not None:
            self._draw()

    def _draw(self) -> None:
        raise NotImplementedError

    def _clear(self) -> None:
        """Before a draw: no cells, no labels."""
        self.canvas.clear()
        self._cell_positions = {}
        for child in list(self.children):
            self.remove_widget(child)

    def _draw_cell(self, day: str, rect: tuple, colour) -> None:
        """A day's cell, outlined when it is the selected day; its rect is where a tap picks it (call in the canvas)."""
        x, y, w, h = rect
        if day == self._selected_date:
            Color(1.0, 1.0, 1.0, 0.9)
            Rectangle(pos=(x - dp(1), y - dp(1)), size=(w + dp(2), h + dp(2)))
        Color(*colour)
        RoundedRectangle(pos=(x, y), size=(w, h), radius=[dp(2)])
        self._cell_positions[day] = rect

    def _add_label(self, text: str, colour, rect: tuple, halign: str, valign: str = "middle") -> None:
        """A small text over the chart (a canvas draws no text) in `rect` (x, y, w, h): a day's initial, a month, a
        score, an axis value."""
        x, y, w, h = rect
        label = ThemedLabel(text=text, font_size=F.TINY, color=colour, size_hint=(None, None), size=(w, h), pos=(x, y),
                            halign=halign, valign=valign)
        label.text_size = label.size
        self.add_widget(label)


class CalendarHeatmap(DayChart):
    """GitHub-style grid of day cells, colored by value.

    Shows WEEKS_VISIBLE weeks of data. Cell size adapts to the widget's
    available width so the heatmap fills its row when the window resizes.
    """

    CELL_SIZE = dp(14)       # minimum / default cell size
    CELL_MAX = dp(28)        # cap so a wide window doesn't make the heatmap huge
    CELL_GAP = dp(2)
    LEFT_MARGIN = dp(22)     # space for day-of-week labels
    TOP_MARGIN = dp(20)      # space for month labels
    WEEKS_VISIBLE = 18

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.height = 7 * (self.CELL_SIZE + self.CELL_GAP) + self.TOP_MARGIN

    @classmethod
    def window(cls, end: datetime.date) -> tuple[datetime.date, datetime.date]:
        """WEEKS_VISIBLE whole weeks from a Monday, the last one `end`'s, but never past today: pages meet."""
        monday = end - datetime.timedelta(days=end.weekday())
        return monday - datetime.timedelta(weeks=cls.WEEKS_VISIBLE - 1), min(monday + datetime.timedelta(days=6),
                                                                              common.today())

    @classmethod
    def step(cls, end: datetime.date, direction: int) -> datetime.date:
        return end + datetime.timedelta(weeks=cls.WEEKS_VISIBLE * direction)

    def _compute_cell_size(self) -> float:
        """Cell size that fills the available width given WEEKS_VISIBLE columns,
        clamped to [CELL_SIZE, CELL_MAX] so the heatmap stays a reasonable
        height on wide windows."""
        avail = max(self.width - self.LEFT_MARGIN, dp(10))
        cell = avail / self.WEEKS_VISIBLE - self.CELL_GAP
        return max(self.CELL_SIZE, min(cell, self.CELL_MAX))

    def fitted_height(self) -> float:
        """Seven rows of cells at the size the width gives, under the month labels."""
        return 7 * (self._compute_cell_size() + self.CELL_GAP) + self.TOP_MARGIN

    def _draw(self) -> None:
        # The height first, at the cell size the width gives (the chart row follows it): setting it draws again, which
        # the clear after it wipes, so a resize leaves one set of cells and labels.
        new_height = self.fitted_height()
        if abs(self.height - new_height) > 0.5:
            self.height = new_height
        self._clear()
        start, last = self._shown_window()
        cell = self._compute_cell_size()
        gap = self.CELL_GAP
        x0 = self.x + self.LEFT_MARGIN
        y_top = self.top - dp(18)  # leave space for month labels

        with self.canvas:
            current = start
            col = 0
            while current <= last:
                dow = current.weekday()  # 0=Mon, 6=Sun
                cx = x0 + col * (cell + gap)
                cy = y_top - dow * (cell + gap) - cell
                date_str = current.isoformat()
                self._draw_cell(date_str, (cx, cy, cell, cell), score_colour(self._day_values.get(date_str, 0)))
                if dow == 6:
                    col += 1
                current += datetime.timedelta(days=1)
        self._render_labels(y_top, cell, gap)

    def _render_labels(self, y_top: float, cell: float, gap: float) -> None:
        """The day-of-week initials beside the rows, and a month's name over its first week's column."""
        for i, text in enumerate(["M", "", "W", "", "F", "", "S"]):
            if text:
                self._add_label(text, C.TEXT_MUTED, (self.x, y_top - i * (cell + gap) - cell, dp(18), cell), "center")
        prev_month = -1
        for date_str, (cx, _cy, _w, _h) in self._cell_positions.items():
            day = datetime.date.fromisoformat(date_str)
            if day.day <= 7 and day.month != prev_month and day.weekday() <= 3:
                self._add_label(day.strftime("%b"), C.TEXT_SECONDARY, (cx, y_top + dp(2), dp(30), dp(14)), "left")
                prev_month = day.month


class Last14DaysBars(DayChart):
    """14-day bar chart of avg shamatha — alternative to the calendar heatmap.

    Public API mirrors CalendarHeatmap so HistoryScreen can swap them.
    Renders a y-axis with gridlines/labels at 0/25/50/75/100, per-bar score
    labels above non-empty bars, and a polyline trend through bar tops.
    """

    DAYS = 14
    HEIGHT = dp(132)
    MIN_BAR_HEIGHT = dp(2)
    PAD_RIGHT = dp(4)
    GRID_VALUES = (0, 25, 50, 75, 100)

    # Room for its labels, at the text size in use (F.box).
    @staticmethod
    def _baseline_h() -> float:
        return F.box(20)  # the day labels under the bars

    @staticmethod
    def _pad_top() -> float:
        return F.box(12)  # a score label over a full bar, and the 100 label's upper half, stay inside

    @staticmethod
    def _pad_left() -> float:
        return F.box(24)  # the y-axis labels

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.height = self.HEIGHT

    @classmethod
    def window(cls, end: datetime.date) -> tuple[datetime.date, datetime.date]:
        return end - datetime.timedelta(days=cls.DAYS - 1), end

    @classmethod
    def step(cls, end: datetime.date, direction: int) -> datetime.date:
        return end + datetime.timedelta(days=cls.DAYS * direction)

    def _draw(self) -> None:
        self._clear()
        if self.width < 10 or self.height < 10:
            return

        start, _last = self._shown_window()
        days = [start + datetime.timedelta(days=i) for i in range(self.DAYS)]

        avail_w = max(self.width - self._pad_left() - self.PAD_RIGHT, dp(10))
        slot_w = avail_w / self.DAYS
        bar_w = max(slot_w - dp(4), dp(4))

        graph_h = self.height - self._baseline_h() - self._pad_top()
        graph_y = self.y + self._baseline_h()
        graph_x_left = self.x + self._pad_left()
        graph_x_right = self.x + self.width - self.PAD_RIGHT

        # Track bar-top centers so we can stitch a trend polyline below
        trend_points: list[float] = []

        with self.canvas:
            # Horizontal gridlines at 0/25/50/75/100
            for v in self.GRID_VALUES:
                gy = graph_y + (v / 100.0) * graph_h
                Color(*C.TEXT_MUTED)
                Line(
                    points=[graph_x_left, gy, graph_x_right, gy],
                    width=1, dash_offset=2, dash_length=4,
                )

            for idx, day in enumerate(days):
                cx = graph_x_left + idx * slot_w + (slot_w - bar_w) / 2
                date_str = day.isoformat()
                score = self._day_values.get(date_str, 0)
                bar_h = max(score / 100.0 * graph_h, self.MIN_BAR_HEIGHT) if score > 0 else self.MIN_BAR_HEIGHT
                self._draw_cell(date_str, (cx, graph_y, bar_w, bar_h), score_colour(score))
                if score > 0:
                    trend_points.extend([cx + bar_w / 2, graph_y + bar_h])

            # Trend polyline through bar tops (only days with data)
            if len(trend_points) >= 4:
                Color(*C.PRIMARY)
                Line(points=trend_points, width=1.4)

        self._render_labels(graph_y, graph_h)

    def _render_labels(self, graph_y: float, graph_h: float) -> None:
        """Y-axis labels (0/25/50/75/100), day labels under the bars and each bar's score over it, at its drawn rect."""
        for v in self.GRID_VALUES:
            gy = graph_y + (v / 100.0) * graph_h
            self._add_label(str(v), C.TEXT_MUTED, (self.x, gy - F.box(7), self._pad_left() - dp(2), F.box(14)), "right")
        # A day's initial under its bar, its date on the first slot and on a month's first day
        dow_initials = ["M", "T", "W", "T", "F", "S", "S"]
        for idx, (date_str, (cx, _y, bar_w, bar_h)) in enumerate(self._cell_positions.items()):
            day = datetime.date.fromisoformat(date_str)
            text = dow_initials[day.weekday()] if day.day != 1 and idx > 0 else f"{day.day}"
            self._add_label(text, C.TEXT_MUTED, (cx - dp(4), self.y, bar_w + dp(8), F.box(16)), "center")
            score = self._day_values.get(date_str, 0)
            if score > 0:
                self._add_label(f"{int(round(score))}", C.TEXT, (cx - dp(6), graph_y + bar_h, bar_w + dp(12), F.box(12)),
                                "center", valign="bottom")
