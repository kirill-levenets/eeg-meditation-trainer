"""History screen: calendar heatmap + session detail.

Replaces separate Diary and Analytics screens. Shows a GitHub-style
contribution heatmap colored by daily avg shamatha score. Tap a day
to see sessions for that date; tap a session to see full detail.
"""

import datetime
import math
from collections.abc import Callable
from typing import Optional

from kivy.clock import Clock
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from app.logger import logger
from app.ui.period_totals import (
    ALL_TIME,
    day_month,
    day_range,
    period_totals,
    periods_around,
    session_day,
)
from app.ui.session_labels import (
    session_label,
    session_notes_line,
    session_stats_line,
    session_title,
)
from app.ui.theme import (
    ICONS_AVAILABLE,
    C,
    Card,
    Divider,
    F,
    FoldChevron,
    Icons,
    RenameRow,
    RevealBox,
    S,
    StyledButton,
    ThemedLabel,
    confirm_popup,
    fill_background,
    format_duration,
)
from app.ui.touch_utils import point_in_rect


def _today() -> datetime.date:
    return datetime.date.today()


def _lerp_color(t: float):
    """Lerp from dark gray (no data) through blue→green by score 0..100."""
    if t <= 0:
        return C.BG_CARD
    t = min(t / 100.0, 1.0)
    # Low scores: dim blue; high scores: bright green
    r = 0.12 + (0.20 - 0.12) * (1 - t) + (0.25 * t)
    g = 0.18 + (0.85 - 0.18) * t
    b = 0.30 + (0.55 - 0.30) * (1 - t) * (1 - t)
    return (r, g, b, 1.0)


def _iso_date(text: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def period_text(first: datetime.date, last: datetime.date) -> str:
    """The chart's period as the totals write a week, with the year wherever it isn't this one (no row under it says)."""
    if first.year != last.year:
        return f"{day_month(first)} {first.year} – {day_month(last)} {last.year}"
    return day_range(first, last) + ("" if last.year == _today().year else f" {last.year}")


_SWIPE = dp(40)  # a sideways move this long pages the chart
_TAP_SLOP = dp(20)  # a fingertip's drift: a press that moves less is still a tap


class _DayChart(Widget):
    """Days, one period at a time: a tap picks a day on the lift (so a swipe that starts on a day picks none) and a
    sideways swipe pages. Subclasses `_draw` `window(end)` for the period end their owner gives, and record each day's
    rect; a chart off screen doesn't draw until it is back."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint_y = None
        self._day_values: dict[str, float] = {}  # "YYYY-MM-DD" -> avg_shamatha
        self._cell_positions: dict[str, tuple] = {}
        self._on_day_tap: Callable | None = None
        self._on_swipe: Callable[[int], None] | None = None
        self._period_source: Callable[[], datetime.date] | None = None  # the owner's period end; today without one
        self._selected_date: str | None = None
        self.bind(size=self._redraw, pos=self._redraw)
        C.add_listener(self._redraw)

    @classmethod
    def window(cls, end: datetime.date) -> tuple[datetime.date, datetime.date]:
        """(first, last) day shown for a period ending at `end`."""
        raise NotImplementedError

    @classmethod
    def step(cls, end: datetime.date, direction: int) -> datetime.date:
        """The period end one window later (1) or earlier (-1)."""
        raise NotImplementedError

    def _shown_window(self) -> tuple[datetime.date, datetime.date]:
        return self.window((self._period_source or _today)())

    def set_period_source(self, source: Callable[[], datetime.date]) -> None:
        self._period_source = source

    def set_data(self, day_values: dict[str, float]) -> None:
        self._day_values = day_values
        self._redraw()

    def set_day_tap_callback(self, cb: Callable) -> None:
        self._on_day_tap = cb

    def set_swipe_callback(self, cb: Callable[[int], None]) -> None:
        """cb(-1) for a swipe that brings earlier days in, cb(1) for later ones."""
        self._on_swipe = cb

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
            if self._on_swipe:
                self._on_swipe(-1 if dx > 0 else 1)  # dragging the days right brings earlier ones in
        elif math.hypot(dx, dy) <= _TAP_SLOP:
            self._tap_day(touch.ox, touch.oy)  # where the finger came down: it aimed there
        return True

    def _tap_day(self, x: float, y: float) -> None:
        day = next((d for d, rect in self._cell_positions.items() if point_in_rect(x, y, rect)), None)
        if day is None:
            return
        self._selected_date = day
        self._redraw()
        if self._on_day_tap:
            self._on_day_tap(day)

    def _redraw(self, *args) -> None:
        if self.parent is not None:
            self._draw()

    def _draw(self) -> None:
        raise NotImplementedError


class CalendarHeatmap(_DayChart):
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
                                                                              _today())

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

    def _draw(self) -> None:
        self.canvas.clear()
        self._cell_positions = {}
        start, last = self._shown_window()
        cell = self._compute_cell_size()
        gap = self.CELL_GAP
        # Update self.height to match the (possibly resized) cell so the
        # graph row in HistoryScreen tracks via its size_hint_y=None bind.
        new_height = 7 * (cell + gap) + self.TOP_MARGIN
        if abs(self.height - new_height) > 0.5:
            self.height = new_height
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
                score = self._day_values.get(date_str, 0)
                color = _lerp_color(score)

                # Highlight selected day
                if date_str == self._selected_date:
                    Color(1.0, 1.0, 1.0, 0.9)
                    Rectangle(
                        pos=(cx - dp(1), cy - dp(1)),
                        size=(cell + dp(2), cell + dp(2)),
                    )

                Color(*color)
                RoundedRectangle(pos=(cx, cy), size=(cell, cell), radius=[dp(2)])
                self._cell_positions[date_str] = (cx, cy, cell, cell)

                if dow == 6:
                    col += 1
                current += datetime.timedelta(days=1)

        # Render text labels using Label textures
        # (Kivy canvas can't render text directly; we overlay labels)
        self._render_labels(x0, y_top, start, last, cell, gap)

    def _render_labels(self, x0, y_top, start, last, cell, gap):
        """Add day-of-week and month text labels."""
        # Remove old label widgets
        for child in list(self.children):
            self.remove_widget(child)

        # Day-of-week labels
        for i, text in enumerate(["M", "", "W", "", "F", "", "S"]):
            if text:
                lbl = ThemedLabel(
                    text=text,
                    font_size=F.TINY,
                    color=C.TEXT_MUTED,
                    size_hint=(None, None),
                    size=(dp(18), cell),
                    pos=(self.x, y_top - i * (cell + gap) - cell),
                    halign="center",
                    valign="middle",
                )
                lbl.text_size = lbl.size
                self.add_widget(lbl)

        # Month labels
        current = start
        col = 0
        prev_month = -1
        while current <= last:
            dow = current.weekday()
            if current.day <= 7 and current.month != prev_month and dow <= 3:
                month_name = current.strftime("%b")
                mx = x0 + col * (cell + gap)
                lbl = ThemedLabel(
                    text=month_name,
                    font_size=F.TINY,
                    color=C.TEXT_SECONDARY,
                    size_hint=(None, None),
                    size=(dp(30), dp(14)),
                    pos=(mx, y_top + dp(2)),
                    halign="left",
                    valign="middle",
                )
                lbl.text_size = lbl.size
                self.add_widget(lbl)
                prev_month = current.month
            if dow == 6:
                col += 1
            current += datetime.timedelta(days=1)


class Last14DaysBars(_DayChart):
    """14-day bar chart of avg shamatha — alternative to the calendar heatmap.

    Public API mirrors CalendarHeatmap so HistoryScreen can swap them.
    Renders a y-axis with gridlines/labels at 0/25/50/75/100, per-bar score
    labels above non-empty bars, and a polyline trend through bar tops.
    """

    DAYS = 14
    MIN_BAR_HEIGHT = dp(2)
    BASELINE_HEIGHT = dp(20)  # space for date labels under bars
    PAD_TOP = dp(12)          # a score label over a full bar, and the 100 label's upper half, stay inside
    PAD_LEFT = dp(24)         # space for y-axis labels
    PAD_RIGHT = dp(4)
    GRID_VALUES = (0, 25, 50, 75, 100)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.height = dp(132)

    @classmethod
    def window(cls, end: datetime.date) -> tuple[datetime.date, datetime.date]:
        return end - datetime.timedelta(days=cls.DAYS - 1), end

    @classmethod
    def step(cls, end: datetime.date, direction: int) -> datetime.date:
        return end + datetime.timedelta(days=cls.DAYS * direction)

    def _draw(self) -> None:
        self.canvas.clear()
        self._cell_positions = {}
        if self.width < 10 or self.height < 10:
            return

        start, _last = self._shown_window()
        days = [start + datetime.timedelta(days=i) for i in range(self.DAYS)]

        avail_w = max(self.width - self.PAD_LEFT - self.PAD_RIGHT, dp(10))
        slot_w = avail_w / self.DAYS
        bar_w = max(slot_w - dp(4), dp(4))

        graph_h = self.height - self.BASELINE_HEIGHT - self.PAD_TOP
        graph_y = self.y + self.BASELINE_HEIGHT
        graph_x_left = self.x + self.PAD_LEFT
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

                if score > 0:
                    bar_h = max(score / 100.0 * graph_h, self.MIN_BAR_HEIGHT)
                else:
                    bar_h = self.MIN_BAR_HEIGHT

                color = _lerp_color(score) if score > 0 else C.BG_CARD

                if date_str == self._selected_date:
                    Color(1.0, 1.0, 1.0, 0.9)
                    Rectangle(
                        pos=(cx - dp(1), graph_y - dp(1)),
                        size=(bar_w + dp(2), bar_h + dp(2)),
                    )

                Color(*color)
                RoundedRectangle(
                    pos=(cx, graph_y), size=(bar_w, bar_h), radius=[dp(2)],
                )
                self._cell_positions[date_str] = (cx, graph_y, bar_w, bar_h)

                if score > 0:
                    trend_points.extend([cx + bar_w / 2, graph_y + bar_h])

            # Trend polyline through bar tops (only days with data)
            if len(trend_points) >= 4:
                Color(*C.PRIMARY)
                Line(points=trend_points, width=1.4)

        self._render_labels(days, slot_w, bar_w, graph_x_left, graph_y, graph_h)

    def _render_labels(self, days, slot_w, bar_w, graph_x_left, graph_y, graph_h):
        """Y-axis labels (0/25/50/75/100), day labels under bars, and per-bar scores."""
        for child in list(self.children):
            self.remove_widget(child)

        # Y-axis labels on the left
        for v in self.GRID_VALUES:
            gy = graph_y + (v / 100.0) * graph_h
            ylbl = ThemedLabel(
                text=str(v),
                font_size=F.TINY,
                color=C.TEXT_MUTED,
                size_hint=(None, None),
                size=(self.PAD_LEFT - dp(2), dp(14)),
                pos=(self.x, gy - dp(7)),
                halign="right",
                valign="middle",
            )
            ylbl.text_size = ylbl.size
            self.add_widget(ylbl)

        # Day-of-week initials under each bar (day-number on the first slot
        # of each new month) and per-bar score numbers above non-empty bars
        dow_initials = ["M", "T", "W", "T", "F", "S", "S"]
        for idx, day in enumerate(days):
            cx = graph_x_left + idx * slot_w + (slot_w - bar_w) / 2
            initial = dow_initials[day.weekday()]
            day_num = day.day
            text = initial if day_num != 1 and idx > 0 else f"{day_num}"
            day_lbl = ThemedLabel(
                text=text,
                font_size=F.TINY,
                color=C.TEXT_MUTED,
                size_hint=(None, None),
                size=(bar_w + dp(8), dp(16)),
                pos=(cx - dp(4), self.y),
                halign="center",
                valign="middle",
            )
            day_lbl.text_size = day_lbl.size
            self.add_widget(day_lbl)

            date_str = day.isoformat()
            score = self._day_values.get(date_str, 0)
            if score > 0:
                bar_h = max(score / 100.0 * graph_h, self.MIN_BAR_HEIGHT)
                score_lbl = ThemedLabel(
                    text=f"{int(round(score))}",
                    font_size=F.TINY,
                    color=C.TEXT,
                    size_hint=(None, None),
                    size=(bar_w + dp(12), dp(12)),
                    pos=(cx - dp(6), graph_y + bar_h),
                    halign="center",
                    valign="bottom",
                )
                score_lbl.text_size = score_lbl.size
                self.add_widget(score_lbl)


class _StableScrollView(ScrollView):
    """A ScrollView whose content height changes while it may be scrolled: a change keeps the pixel offset from the top."""

    def _update_effect_y_bounds(self, *args):
        # Kivy 2.3 rescales the fraction (max * scroll_y): past an edge the overscroll grew with every height change
        # until the list ran out of view (#56). Keep the offset from the top, where the list starts.
        effect = self.effect_y
        if not self._viewport or not effect:
            return
        new_max = self.height - self.viewport_size[1]
        if new_max == effect.max:  # the touch start/stop resync: keep Kivy's own overscroll bounce
            super()._update_effect_y_bounds(*args)
            return
        from_top = effect.max * (self.scroll_y - 1)
        effect.min = 0 if new_max < 0 else new_max
        effect.max = new_max
        effect.value = new_max + from_top


_ROW_H = dp(56)
_ROW_H_NOTES = dp(76)  # a row with a notes line
_RENAME_H = dp(40)  # the inline editor under a row being renamed


def _checkbox_glyph(selected: bool) -> str:
    if ICONS_AVAILABLE:
        return Icons.CHECKBOX_MARKED if selected else Icons.CHECKBOX_BLANK
    return "[x]" if selected else "[ ]"


class _SessionRow(RecycleDataViewBehavior, BoxLayout):
    """One History row, reused for whichever session scrolls into it: every refresh sets everything it shows."""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.sid = None
        self._card = Card(orientation="horizontal", size_hint_y=None, height=_ROW_H, bg_color=C.BG_CARD,
                          spacing=S.GAP_SM, padding=0)
        self._checkbox = ThemedLabel(font_name="Icons" if ICONS_AVAILABLE else "Roboto", font_size=F.H2,
                                     size_hint_x=None, width=dp(36), halign="center", valign="middle")
        score_bar = Widget(size_hint_x=None, width=dp(4))
        with score_bar.canvas:
            self._score_color = Color(1, 1, 1, 1)
            rect = RoundedRectangle(pos=score_bar.pos, size=score_bar.size, radius=[dp(2)])
        score_bar.bind(pos=lambda w, v: setattr(rect, "pos", v), size=lambda w, v: setattr(rect, "size", v))
        self._info = info = BoxLayout(orientation="vertical", padding=[dp(6), 0])
        # One line each, cut with an ellipsis: a long name or note never wraps out of its row.
        self._name_label = ThemedLabel(font_size=F.BODY, color=C.TEXT, halign="left", valign="middle",
                                       size_hint_y=0.55, shorten=True, shorten_from="right")
        self._stats_label = ThemedLabel(font_size=F.TINY, color=C.TEXT_MUTED, halign="left", valign="middle",
                                        size_hint_y=0.45, shorten=True, shorten_from="right")
        self._notes_label = ThemedLabel(font_size=F.TINY, color=C.TEXT_MUTED, halign="left", valign="middle",
                                        size_hint_y=0.45, shorten=True, shorten_from="right")
        for label in (self._name_label, self._stats_label, self._notes_label):
            label.bind(size=label.setter("text_size"))
        info.add_widget(self._name_label)
        info.add_widget(self._stats_label)
        # Rename + delete are drawn only: the screen's list router hit-tests the strip (see _list_touch_down).
        self._actions = BoxLayout(orientation="horizontal", size_hint_x=None, width=dp(80), spacing=dp(2))
        for icon, color in ((Icons.PENCIL, C.PRIMARY), (Icons.DELETE, C.DANGER)):
            self._actions.add_widget(StyledButton(text="", icon=icon, bg_color=color, text_color=color,
                                                  font_size=F.SMALL, size_hint_y=1, bold=False, outline=True))
        for w in (score_bar, info, self._actions):
            self._card.add_widget(w)
        self.add_widget(self._card)

    def on_parent(self, _row, parent):
        owner = getattr(self, "_owner", None)
        if owner is None:
            return
        if parent is not None:
            # Back at the position it last showed, Kivy reuses a row without refresh_view_attrs: it may have
            # missed a select-mode, selection or rename change while it was off screen.
            self.sync(owner)
        elif owner._rename_row.parent is self:
            # Scrolled off, a row keeps its widgets until it is reused: it mustn't keep the editor. A relayout also
            # removes and re-adds every row, so the focus (the keyboard) is dropped only if no row takes it back.
            self.remove_widget(owner._rename_row)
            owner._rename_focus_check()

    def refresh_view_attrs(self, rv, index, data):
        # Size and position come from the layout; nothing else in the data is a view property.
        self._owner = rv.owner
        self.sid = data["sid"]
        self._name_label.text = data["name"]
        self._stats_label.text = data["stats"]
        self._notes_label.text = data["notes"]
        if bool(data["notes"]) != (self._notes_label.parent is not None):
            if data["notes"]:
                self._info.add_widget(self._notes_label, index=0)
            else:
                self._info.remove_widget(self._notes_label)
        self._card.height = data["card_h"]
        self._score_color.rgba = data["color"]
        self.sync(rv.owner)

    def sync(self, owner: "HistoryScreen") -> None:
        """Show the screen's state for this row's session: select mode, its checkbox, the rename editor."""
        select = owner._select_mode
        if select != (self._checkbox.parent is not None):
            if select:
                self._card.add_widget(self._checkbox, index=len(self._card.children))
                self._card.remove_widget(self._actions)
            else:
                self._card.remove_widget(self._checkbox)
                self._card.add_widget(self._actions)
        selected = self.sid in owner._selected_ids
        self._checkbox.text = _checkbox_glyph(selected)
        self._checkbox.color = C.ACCENT if selected else C.TEXT_SECONDARY
        editor = owner._rename_row
        if owner._renaming_sid == self.sid and self.sid is not None:
            if editor.parent is not self:
                if editor.parent is not None:
                    editor.parent.remove_widget(editor)
                self.add_widget(editor)
        elif editor.parent is self:
            self.remove_widget(editor)


class _SessionList(_StableScrollView, RecycleView):
    """The session list: one data item per shown session, row widgets only for the rows on screen."""

    def __init__(self, owner: "HistoryScreen", **kwargs):
        super().__init__(**kwargs)
        self.owner = owner
        rows = RecycleBoxLayout(orientation="vertical", size_hint_y=None, default_size=(None, _ROW_H),
                                default_size_hint=(1, None), spacing=S.GAP_SM, padding=[0, S.GAP_SM])
        rows.bind(minimum_height=rows.setter("height"))
        self.add_widget(rows)
        self.viewclass = _SessionRow  # stored on the layout manager, so only once there is one


class HistoryScreen(Screen):
    """Unified history: calendar heatmap + session list + session detail."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "history"
        self._on_session_select: Optional[Callable] = None
        self._on_save_notes: Optional[Callable] = None
        self._on_delete_sessions: Optional[Callable] = None  # (ids, done) -> done(True) once deleted
        self._on_export_csv: Optional[Callable] = None
        self._on_rename_session: Optional[Callable] = None
        self._sessions: list[dict] = []
        self._filtered_date: Optional[str] = None
        self._view_mode: str = "calendar"
        self._on_view_mode_change: Optional[Callable] = None
        self._shown: list[dict] = []  # the sessions the list shows: all of them, or the filtered day's
        self._renaming_sid: int | None = None
        self._settled_log_ev = None
        self._current_header: str = "All sessions"
        self._select_mode: bool = False
        self._selected_ids: set[int] = set()
        self._on_export_sessions: Optional[Callable] = None
        self._period_offset = 0  # days from today to the chart's period end: 0 is today's page, a page back below it
        self._first_day: datetime.date | None = None  # the first session's: paging back stops once it is shown
        self._build_ui()

    def _build_ui(self) -> None:
        self._root = BoxLayout(orientation="vertical", padding=S.PAGE_PAD, spacing=S.GAP)
        root = self._root
        fill_background(root, C.BG)

        # Title, and right after it the chevron that folds the chart and the totals away (the list gets their room)
        self._title_row = BoxLayout(size_hint_y=None, height=dp(32), spacing=S.GAP_SM)
        self._title = ThemedLabel(text="History", font_size=F.H1, bold=True, color=C.TEXT, size_hint_x=None)
        self._title.bind(texture_size=lambda w, ts: setattr(w, "width", ts[0]))
        self._btn_collapse = FoldChevron()
        self._btn_collapse.bind(on_release=lambda *a: self._toggle_chart())
        for w in (self._title, self._btn_collapse):
            self._title_row.add_widget(w)
        root.add_widget(self._title_row)

        # Graph row: graph (calendar OR bars) on the left, narrow toggle
        # column (Cal / 14d) on the right. Row height matches the active
        # widget. Only one of heatmap/bars is parented at a time — the
        # inactive one is removed from graph_wrap. BoxLayout natively
        # observes its own children list, so swapping fires a layout
        # pass automatically.
        self._graph_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(132) + self._PERIOD_H,
            spacing=dp(4),
        )

        # The chart, under the period row it shows when upright (_place_totals).
        self._graph_wrap = BoxLayout(orientation="vertical", size_hint_x=1)
        self._build_period_row()

        # Calendar heatmap (initial active widget).
        self._heatmap = CalendarHeatmap()
        self._bars = Last14DaysBars()  # built but NOT parented until the user toggles to the bars view
        for chart in (self._heatmap, self._bars):
            chart.set_day_tap_callback(self._on_day_tap)
            chart.set_swipe_callback(self.shift_period)
            chart.set_period_source(lambda: self.period_end)
            chart.bind(height=self._on_active_widget_height)
        self._graph_wrap.add_widget(self._heatmap)

        self._graph_row.add_widget(self._graph_wrap)

        # Toggle column on the right — fixed 40dp wide, two compact buttons
        # stacked vertically.
        toggle_col = BoxLayout(
            orientation="vertical",
            size_hint_x=None,
            width=dp(40),
            spacing=dp(4),
        )
        self._btn_calendar = StyledButton(
            text="Cal",
            bg_color=C.PRIMARY,
            font_size=F.SMALL,
            bold=True,
        )
        self._btn_bars = StyledButton(
            text="14d",
            bg_color=C.BG_CARD,
            text_color=C.TEXT_SECONDARY,
            font_size=F.SMALL,
            bold=False,
        )
        self._btn_calendar.bind(on_release=lambda *a: self._on_toggle_pressed("calendar"))
        self._btn_bars.bind(on_release=lambda *a: self._on_toggle_pressed("bars"))
        toggle_col.add_widget(self._btn_calendar)
        toggle_col.add_widget(self._btn_bars)
        self._graph_row.add_widget(toggle_col)
        self._toggle_col = toggle_col

        # The chart and the totals fold away together: one block, detached when folded.
        self._chart_area = BoxLayout(orientation="vertical", size_hint_y=None, spacing=S.GAP)
        self._chart_area.bind(minimum_height=self._chart_area.setter("height"))
        self._chart_area.add_widget(self._graph_row)
        self._build_totals()
        # Sideways: the period row and the table beside the chart, the row over the table.
        self._side_col = BoxLayout(orientation="vertical", size_hint=(None, None), width=self._TOTALS_BESIDE_W,
                                   pos_hint={"top": 1})
        self._side_col.bind(minimum_height=self._side_col.setter("height"))
        root.add_widget(self._chart_area)
        root.bind(width=self._place_totals)
        self._place_totals()

        # Date label + Show All button
        date_row = BoxLayout(size_hint_y=None, height=dp(28), spacing=S.GAP)
        self._date_label = ThemedLabel(
            text="Tap a day to see sessions",
            font_size=F.BODY,
            color=C.TEXT_SECONDARY,
            halign="left",
            valign="middle",
        )
        self._date_label.bind(size=self._date_label.setter("text_size"))
        date_row.add_widget(self._date_label)
        self._btn_show_all = StyledButton(
            text="Show All",
            bg_color=C.BG_CARD,
            text_color=C.TEXT_SECONDARY,
            font_size=F.SMALL,
            size_hint_x=None,
            width=dp(80),
            height=dp(28),
            bold=False,
        )
        self._btn_show_all.bind(on_release=lambda *a: self._reset_filter())
        self._btn_show_all.opacity = 0
        self._btn_show_all.disabled = True
        date_row.add_widget(self._btn_show_all)
        self._btn_select = StyledButton(
            text="Select", bg_color=C.BG_CARD, text_color=C.TEXT_SECONDARY,
            font_size=F.SMALL, size_hint_x=None, width=dp(72), height=dp(28), bold=False,
        )
        self._btn_select.bind(on_release=lambda *a: self.set_select_mode(True))
        date_row.add_widget(self._btn_select)
        root.add_widget(date_row)

        # Multi-select export action bar (issue #7) — RevealBox detaches its
        # children when hidden, so it can't eat taps while inactive.
        self._select_bar = RevealBox(dp(40), spacing=S.GAP_SM)
        self._btn_export = StyledButton(
            text="Export 0", bg_color=C.ACCENT, font_size=F.SMALL, height=dp(40),
        )
        self._btn_export.disabled = True
        self._btn_export.bind(on_release=lambda *a: self.export_selected())
        self._btn_delete = StyledButton(text="Delete 0", bg_color=C.DANGER, font_size=F.SMALL, height=dp(40))
        self._btn_delete.disabled = True
        self._btn_delete.bind(on_release=lambda *a: self.delete_selected())
        self._btn_select_all = StyledButton(
            text="Select all", bg_color=C.BG_CARD, text_color=C.TEXT,
            font_size=F.SMALL, height=dp(40),
        )
        self._btn_select_all.bind(on_release=lambda *a: self.select_all_shown())
        self._btn_cancel = StyledButton(
            text="Cancel", bg_color=C.BG_CARD, text_color=C.TEXT_SECONDARY,
            font_size=F.SMALL, height=dp(40),
        )
        self._btn_cancel.bind(on_release=lambda *a: self.set_select_mode(False))
        self._select_bar.set_content(self._btn_export, self._btn_delete, self._btn_select_all, self._btn_cancel)
        root.add_widget(self._select_bar)

        root.add_widget(Divider())

        # Session list: a RecycleView. The router hit-tests the visible rows (see _list_touch_down).
        self._build_rename_row()
        self._empty_label = ThemedLabel(text="No sessions on this day", font_size=F.BODY, color=C.TEXT_MUTED,
                                        size_hint_y=None, height=dp(40))
        self._list_area = BoxLayout(orientation="vertical")
        self._rv = _SessionList(self)
        self._rv.layout_manager.bind(on_touch_down=self._list_touch_down)
        self._list_area.add_widget(self._rv)
        root.add_widget(self._list_area)

        self.add_widget(root)
        self._update_period_row()
        self._update_totals()

    _PERIOD_H = dp(28)

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

    def _fit_graph_row(self) -> None:
        """The chart's height, plus the period row's where it sits over the chart."""
        height = self._active_chart().height + (self._PERIOD_H if self._period_row.parent is self._graph_wrap else 0)
        if height != self._graph_row.height:
            self._graph_row.height = height
            self._cascade_layout()

    @property
    def period_end(self) -> datetime.date:
        return _today() + datetime.timedelta(days=self._period_offset)

    def _active_chart(self) -> _DayChart:
        return self._heatmap if self._view_mode == "calendar" else self._bars

    def _can_page_back(self) -> bool:
        return self._first_day is not None and self._active_chart().window(self.period_end)[0] > self._first_day

    def shift_period(self, direction: int) -> None:
        """Page the chart one window earlier (-1) or later (1): back as far as the first session, on as far as today."""
        if direction < 0 and not self._can_page_back():
            return
        end = self._active_chart().step(self.period_end, direction)
        self._set_period(min((end - _today()).days, 0))

    def _set_period(self, offset: int) -> None:
        """Days back from today: a page stays as far back as the day moves on, still meeting today's."""
        self._period_offset = offset
        for chart in (self._heatmap, self._bars):  # the one off screen draws when it is back
            chart._redraw()
        self._update_period_row()

    def _update_period_row(self) -> None:
        self._period_label.text = period_text(*self._active_chart().window(self.period_end))
        self._btn_prev.disabled = not self._can_page_back()
        self._btn_next.disabled = self._period_offset == 0

    _TOTALS_ROW_H = dp(20)
    _TOTALS_BESIDE_W = dp(290)  # its widest texts: "September 2025" and three "Best streak" columns
    # Beside the chart once the page fits the heatmap at its smallest cells next to the table and the Cal / 14d
    # buttons: ~670 dp, which a landscape phone of ~730 has; narrower, under the chart.
    _TOTALS_BESIDE_FROM = (2 * S.PAGE_PAD + CalendarHeatmap.LEFT_MARGIN
                           + CalendarHeatmap.WEEKS_VISIBLE * (CalendarHeatmap.CELL_SIZE + CalendarHeatmap.CELL_GAP)
                           + _TOTALS_BESIDE_W + dp(40) + 2 * dp(4))

    def _build_totals(self) -> None:
        """The Day / Week / Month / All time totals table, built once: _update_totals fills its cells."""
        def cell(text: str = "", first: bool = False, muted: bool = False) -> ThemedLabel:
            label = ThemedLabel(text=text, font_size=F.SMALL, color=C.TEXT_SECONDARY if muted else C.TEXT,
                                halign="left" if first else "right", valign="middle", shorten=True,
                                shorten_from="right", size_hint_x=1.5 if first else 1.0)
            label.bind(size=label.setter("text_size"))
            return label

        self._totals = GridLayout(cols=4, size_hint_y=None, height=5 * self._TOTALS_ROW_H, spacing=(dp(6), 0),
                                  row_default_height=self._TOTALS_ROW_H, row_force_default=True, pos_hint={"top": 1})
        self._totals_header = [cell(text, first=not text, muted=True)
                               for text in ("", "Total", "On target", "Best streak")]
        self._totals_rows = [[cell(first=True), cell(), cell(), cell()] for _ in range(4)]
        for label in self._totals_header + [label for row in self._totals_rows for label in row]:
            self._totals.add_widget(label)

    def _update_totals(self) -> None:
        """The rows: the tapped day's day, week and month (today's when no day is tapped), then all time."""
        today = _today()
        day = datetime.date.fromisoformat(self._filtered_date) if self._filtered_date else today
        for row, (label, start, end) in zip(self._totals_rows, [*periods_around(day, today), ALL_TIME]):
            totals = period_totals(self._sessions, start, end)
            row[0].text = label
            for cell, seconds in zip(row[1:], (totals.seconds, totals.on_target, totals.best_streak)):
                cell.text = format_duration(seconds) if totals.sessions else "–"

    def _place_totals(self, *_a) -> None:
        """Upright, the period row over the chart and the table under it. Sideways, where under the chart the list had
        no room, both beside it: the chart is taller than the table, which leaves the row the room over it."""
        beside = self._root.width >= self._TOTALS_BESIDE_FROM
        if self._totals.parent is (self._side_col if beside else self._chart_area):
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
            self._chart_area.add_widget(self._totals)  # under the chart
        self._fit_graph_row()

    _on_chart_collapse: Optional[Callable] = None

    @property
    def chart_collapsed(self) -> bool:
        return self._chart_area.parent is None

    def set_chart_collapsed(self, collapsed: bool) -> None:
        """Fold the chart and the totals away, detached, or bring them back under the title."""
        if collapsed != self.chart_collapsed:
            if collapsed:
                self._root.remove_widget(self._chart_area)
            else:
                self._root.add_widget(self._chart_area, index=self._root.children.index(self._title_row))
        self._btn_collapse.show_folded(collapsed)

    def set_chart_collapse_callback(self, cb: Callable) -> None:
        self._on_chart_collapse = cb

    def _toggle_chart(self) -> None:
        self.set_chart_collapsed(not self.chart_collapsed)
        if self._on_chart_collapse:
            self._on_chart_collapse(self.chart_collapsed)

    _drawn_for: datetime.date | None = None  # the "today" the chart and the totals were last drawn for

    def on_pre_enter(self, *_a) -> None:
        if _today() != self._drawn_for:  # the day moved on since the list was drawn: the chart and the totals follow
            self._set_day_data()

    def set_callbacks(
        self,
        on_session_select=None,
        on_save_notes=None,
        on_delete_sessions=None,
        on_export_csv=None,
        on_rename_session=None,
    ) -> None:
        self._on_session_select = on_session_select
        self._on_save_notes = on_save_notes
        self._on_delete_sessions = on_delete_sessions
        self._on_export_csv = on_export_csv
        self._on_rename_session = on_rename_session

    def set_export_sessions_callback(self, callback) -> None:
        self._on_export_sessions = callback

    # ── Multi-select CSV export (issue #7) ──
    @property
    def selected_ids(self) -> set:
        return self._selected_ids

    def _shown_sids(self) -> list:
        return [s.get("id") for s in self._shown]

    def set_select_mode(self, on: bool) -> None:
        """Enter/leave multi-select mode; leaving drops the selection. The rows on screen gain/lose their checkbox."""
        self._select_mode = bool(on)
        if not on:
            self._selected_ids = set()
        self._btn_select.opacity = 0 if on else 1
        self._btn_select.disabled = on
        self._select_bar.reveal(on)
        self._close_rename()
        self._update_selection_buttons()
        self._sync_rows()

    def toggle_session_selection(self, sid) -> None:
        if sid in self._selected_ids:
            self._selected_ids.discard(sid)
        else:
            self._selected_ids.add(sid)
        self._update_selection_buttons()
        self._sync_rows()

    def select_all_shown(self) -> None:
        self._selected_ids = {s for s in self._shown_sids() if s is not None}
        self._update_selection_buttons()
        self._sync_rows()

    def export_selected(self) -> None:
        if not self._selected_ids or not self._on_export_sessions:
            return
        self._on_export_sessions(sorted(self._selected_ids))

    def delete_selected(self) -> None:
        if self._selected_ids:
            self._confirm_delete(sorted(self._selected_ids))

    def _update_selection_buttons(self) -> None:
        n = len(self._selected_ids)
        for button, verb in ((self._btn_export, "Export"), (self._btn_delete, "Delete")):
            button.text = f"{verb} {n}"
            button.disabled = n == 0

    def _on_active_widget_height(self, instance, value):
        """Track the active widget's height onto graph_row.

        The widget swap pattern in `set_view_mode` re-parents heatmap or
        bars into graph_wrap; whichever is currently parented is the
        ACTIVE widget. Its height changes (e.g., heatmap recomputing its
        adaptive cell on window resize) should propagate to graph_row so
        the screen layout grows/shrinks accordingly.
        """
        if instance.parent is None or value <= 0:
            return
        self._fit_graph_row()

    def _cascade_layout(self):
        """Synchronous layout pass: root → graph_row → graph_wrap.

        BoxLayout only re-runs its layout when its own size/pos/children
        change. After we change graph_row.height (an explicit `height`
        on a `size_hint_y=None` child), the root needs to be told to
        re-position graph_row, then the graph_row layout positions
        graph_wrap, then graph_wrap positions its child. We force the
        cascade explicitly so the user sees the new layout immediately
        instead of waiting for a window resize.
        """
        if self._root.parent is not None:
            self._root.do_layout()
        self._chart_area.do_layout()
        self._graph_row.do_layout()
        self._graph_wrap.do_layout()
        if self._side_col.parent is not None:
            self._side_col.do_layout()

    def set_view_mode(self, mode: str) -> None:
        """Switch between 'calendar' and 'bars'.

        Architectural note: we swap which widget is parented in
        graph_wrap (clear_widgets + add_widget) rather than juggling
        opacity + height on two coexisting widgets. BoxLayout fires its
        own layout pass when its `children` list changes, which is the
        only Kivy-native trigger we can rely on for child swap. We then
        cascade do_layout() synchronously so graph_row.y / heatmap.pos /
        bar.pos all update in the same turn (no waiting on next-frame
        layout, no stale render flicker).
        """
        if mode not in ("calendar", "bars"):
            return
        self._view_mode = mode
        for chart in (self._heatmap, self._bars):  # the period row above stays
            if chart.parent is not None:
                self._graph_wrap.remove_widget(chart)
        self._update_period_row()  # the same period end, the other view's window
        if mode == "calendar":
            cell = self._heatmap._compute_cell_size()
            cal_h = 7 * (cell + self._heatmap.CELL_GAP) + self._heatmap.TOP_MARGIN
            self._heatmap.height = cal_h
            self._graph_wrap.add_widget(self._heatmap)
            self._btn_calendar.bg_color = C.PRIMARY
            self._btn_calendar.text_color = None
            self._btn_calendar.bold = True
            self._btn_bars.bg_color = C.BG_CARD
            self._btn_bars.text_color = C.TEXT_SECONDARY
            self._btn_bars.bold = False
        else:
            self._bars.height = dp(132)
            self._graph_wrap.add_widget(self._bars)
            self._btn_calendar.bg_color = C.BG_CARD
            self._btn_calendar.text_color = C.TEXT_SECONDARY
            self._btn_calendar.bold = False
            self._btn_bars.bg_color = C.PRIMARY
            self._btn_bars.text_color = None
            self._btn_bars.bold = True
        self._active_chart()._redraw()  # it didn't draw while off screen
        self._fit_graph_row()
        # Force the synchronous layout cascade so the user sees the new
        # geometry immediately.
        self._cascade_layout()

    def set_view_mode_callback(self, cb: Callable) -> None:
        """Called with the new mode string when the user toggles."""
        self._on_view_mode_change = cb

    def _on_toggle_pressed(self, mode: str) -> None:
        self.set_view_mode(mode)
        if self._on_view_mode_change:
            self._on_view_mode_change(mode)

    def load_sessions(self, sessions: list[dict], keep_filter: bool = True) -> None:
        """Load all sessions and build heatmap data."""
        self._sessions = sessions
        # A selection holds only this list's sessions: another profile's would be exported with it.
        self._selected_ids &= {s.get("id") for s in sessions}
        self._update_selection_buttons()
        if not keep_filter:  # another profile or the All Users view: its own history, from today
            self._set_filter(None)
            self._set_period(0)
        self._set_day_data()
        if self._filtered_date:  # a reload of the same view keeps the user's day filter, as a delete does
            self._show_day(self._filtered_date)
        else:
            self._show_sessions(sessions, "All sessions")

    def remove_sessions(self, session_ids) -> None:
        """Drop deleted sessions from the model and the list, in place: the scroll position and any day filter stay."""
        gone = set(session_ids)
        if not gone:
            return
        if self._renaming_sid in gone:
            self._close_rename()
        self._sessions = [s for s in self._sessions if s.get("id") not in gone]
        self._shown = [s for s in self._shown if s.get("id") not in gone]
        self._selected_ids -= gone
        self._update_selection_buttons()
        self._show_items()
        self._set_day_data()
        self._date_label.text = f"{self._current_header} ({len(self._shown)} sessions)"

    def update_session(self, sid, **fields) -> None:
        """Apply a saved edit (the fields not None) to that session in the model, in place: no reload."""
        session = next((s for s in self._sessions if s.get("id") == sid), None)
        if session is None:
            return
        session.update({k: v for k, v in fields.items() if v is not None})
        self._update_item(sid)

    def _set_day_data(self) -> None:
        """Calendar and bars both show each day's average shamatha over the model's sessions."""
        day_scores: dict[str, list[float]] = {}
        for s in self._sessions:
            day = session_day(s)
            if len(day) == 10:
                day_scores.setdefault(day, []).append(s.get("avg_shamatha", 0) or 0)
        day_avg = {day: sum(scores) / len(scores) for day, scores in day_scores.items()}
        self._first_day = min(filter(None, map(_iso_date, day_avg)), default=None)
        self._drawn_for = _today()
        self._heatmap.set_data(day_avg)
        self._bars.set_data(day_avg)
        self._update_period_row()
        self._update_totals()

    def _on_day_tap(self, date_str: str) -> None:
        """Filter sessions to the tapped day. Tap again to reset."""
        if date_str == self._filtered_date:
            self._reset_filter()
            return
        self._set_filter(date_str)
        self._show_day(date_str)

    def _set_filter(self, date_str: Optional[str]) -> None:
        """The one owner of the day filter: the filtered day, its highlight in both views and the Show-all button."""
        self._filtered_date = date_str
        for view in (self._heatmap, self._bars):
            view._selected_date = date_str
            view._redraw()
        self._btn_show_all.opacity = 1 if date_str else 0
        self._btn_show_all.disabled = not date_str
        self._update_totals()

    def _show_day(self, date_str: str) -> None:
        day_sessions = [s for s in self._sessions if session_day(s) == date_str]
        try:
            nice_date = datetime.date.fromisoformat(date_str).strftime("%B %d, %Y")
        except (ValueError, TypeError):
            nice_date = date_str
        self._show_sessions(day_sessions, nice_date)

    def _reset_filter(self) -> None:
        """Clear day filter and show all sessions."""
        self._set_filter(None)
        self._show_sessions(self._sessions, "All sessions")

    def _show_sessions(self, sessions: list[dict], header: str) -> None:
        """Show a new list, from the top: one data item per session, rows built only for what fits on screen."""
        if self._settled_log_ev is not None:
            self._settled_log_ev.cancel()
            self._settled_log_ev = None
        # A new list starts at the top, at rest: reset the effect itself (pixels, velocity, overscroll) —
        # setting scroll_y alone was overwritten by a fling still in flight.
        self._rv.effect_y.reset(self._rv.effect_y.max)
        self._rv.scroll_y = 1
        self._current_header = header
        self._date_label.text = f"{header} ({len(sessions)} sessions)"
        self._close_rename()
        self._shown = sessions
        self._show_items()
        self._settled_log_ev = Clock.schedule_once(lambda _dt: self._log_list_state("settled"), 1.0)

    def _item(self, session: dict) -> dict:
        sid = session.get("id", 0)
        notes = session_notes_line(session)
        card_h = _ROW_H_NOTES if notes else _ROW_H
        return {
            "sid": sid,
            "name": session_title(session),
            "stats": session_stats_line(session),
            "notes": notes,
            "color": _lerp_color(session.get("avg_shamatha", 0) or 0),
            "card_h": card_h,
            "height": card_h + (_RENAME_H if sid == self._renaming_sid else 0),
        }

    def _show_items(self) -> None:
        self._rv.data = [self._item(s) for s in self._shown]
        empty = not self._shown
        if empty and self._empty_label.parent is None:
            self._list_area.add_widget(self._empty_label, index=len(self._list_area.children))
        elif not empty and self._empty_label.parent is not None:
            self._list_area.remove_widget(self._empty_label)

    def _update_item(self, sid) -> None:
        """Re-derive one session's item after a rename opened, closed or saved, or its notes were saved."""
        for i, s in enumerate(self._shown):
            if s.get("id") == sid:
                self._rv.data[i] = self._item(s)
                return

    def _sync_rows(self) -> None:
        for view in self._rv.layout_manager.children:
            if isinstance(view, _SessionRow):
                view.sync(self)

    def _log_list_state(self, tag: str) -> None:
        """Rows, heights and scroll state, so a device log shows where a list ended up (#56)."""
        rv = self._rv
        ey = rv.effect_y
        views = sum(1 for w in rv.layout_manager.children if isinstance(w, _SessionRow))
        logger.info(
            f"History list {tag}: sessions={len(rv.data)} row_widgets={views} list_h={rv.layout_manager.height:.0f} "
            f"viewport_h={rv.height:.0f} scroll_y={rv.scroll_y:.3f} effect={ey.value:.1f} "
            f"bounds=({ey.min:.1f},{ey.max:.1f}) v={ey.velocity:.1f} chart_h={self._graph_row.height:.0f} "
            f"chart_w={self._heatmap.width:.0f} page_h={self._root.height:.0f}"
        )

    # ── Inline rename: one editor, shown under the row of the session being renamed ──

    def _build_rename_row(self) -> None:
        self._rename_row = RenameRow(self._do_rename, height=_RENAME_H, padding=[dp(10), dp(2)])
        self._rename_input = self._rename_row.input
        self._rename_focus_check = Clock.create_trigger(self._drop_rename_focus_if_hidden)

    def _drop_rename_focus_if_hidden(self, _dt) -> None:
        if self._rename_row.parent is None:
            self._rename_input.focus = False

    def session_by_id(self, sid) -> dict | None:
        """A listed session's row, as History holds it (kept current by in-place updates)."""
        return next((s for s in self._shown if s.get("id") == sid), None)

    def _toggle_rename(self, sid) -> None:
        """Open the editor on this session's row, or close it if it is already open there."""
        reopen = self._renaming_sid != sid
        self._close_rename()
        session = self.session_by_id(sid)
        if not reopen or session is None:
            return
        self._renaming_sid = sid
        self._rename_input.text = session_label(session)
        self._update_item(sid)
        self._sync_rows()
        self._rename_row.focus_soon()

    def _close_rename(self) -> None:
        sid, self._renaming_sid = self._renaming_sid, None
        if sid is None:
            return
        self._rename_row.close()
        self._update_item(sid)

    def _do_rename(self) -> None:
        sid = self._renaming_sid
        session = self.session_by_id(sid)
        txt = self._rename_input.text.strip()
        if txt and session is not None and txt != session_label(session):  # unchanged: the stored name stays
            session["session_name"] = txt  # the model row this list shows
            if self._on_rename_session:
                self._on_rename_session(sid, txt)
        self._close_rename()

    def _confirm_delete(self, session_ids: list[int]) -> None:
        """Confirm, then delete one session (a row's delete) or the selection (Delete N) through the one callback."""
        wanted = set(session_ids)
        sessions = [s for s in self._sessions if s.get("id") in wanted]
        if len(session_ids) == 1:
            what = f'Delete session\n"{session_title(sessions[0])}"?' if sessions else "Delete this session?"
        else:
            days = sorted({session_day(s) for s in sessions})
            span = "" if not days else f" on {days[0]}" if len(days) == 1 else f" from {days[0]} to {days[-1]}"
            what = f"Delete {len(session_ids)} sessions{span}?"
            profiles = {s.get("user_id") for s in sessions} - {None}
            if len(profiles) > 1:
                what += f"\nThey are from {len(profiles)} profiles."
        def _deleted(ok: bool) -> None:
            if ok and self._select_mode:
                self.set_select_mode(False)

        def _delete() -> None:
            if self._on_delete_sessions:
                self._on_delete_sessions(list(session_ids), _deleted)

        confirm_popup("Confirm Delete", f"{what}\nThis can't be undone.", "Delete", _delete, ok_color=C.DANGER)

    def _list_touch_down(self, rows, touch) -> bool:
        """The one touch router for the session list.

        Bypasses Kivy's flaky nested dispatch for row actions: find the visible row the tap landed in and route to
        select / rename / delete / open by position.
        """
        if not rows.collide_point(*touch.pos):
            return False
        for view in rows.children:
            if not isinstance(view, _SessionRow) or not view.collide_point(*touch.pos):
                continue
            if self._select_mode:
                self.toggle_session_selection(view.sid)
                return True
            # The open editor (its input and Save) gets the touch the normal way.
            if self._rename_row.parent is view and self._rename_row.collide_point(*touch.pos):
                return False
            actions_left = view.right - dp(80)
            if touch.x >= actions_left:
                if touch.x < actions_left + dp(40):
                    self._toggle_rename(view.sid)
                else:
                    self._confirm_delete([view.sid])
                return True
            if self._on_session_select:
                self._on_session_select(view.sid)
            return True
        return False
