"""History screen: calendar heatmap + session detail.

Replaces separate Diary and Analytics screens. Shows a GitHub-style
contribution heatmap colored by daily avg shamatha score. Tap a day
to see sessions for that date; tap a session to see full detail.
"""

import datetime
from collections.abc import Callable
from typing import Optional

from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from app.ui.theme import C, Card, Divider, F, Icons, S, StyledButton, format_duration


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


class CalendarHeatmap(Widget):
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
        self.size_hint_y = None
        self.height = 7 * (self.CELL_SIZE + self.CELL_GAP) + self.TOP_MARGIN
        self._day_values: dict[str, float] = {}  # "YYYY-MM-DD" -> avg_shamatha
        self._cell_positions: dict[str, tuple] = {}
        self._on_day_tap: Optional[Callable] = None
        self._selected_date: Optional[str] = None
        self.bind(size=self._redraw, pos=self._redraw)

    def _compute_cell_size(self) -> float:
        """Cell size that fills the available width given WEEKS_VISIBLE columns,
        clamped to [CELL_SIZE, CELL_MAX] so the heatmap stays a reasonable
        height on wide windows."""
        avail = max(self.width - self.LEFT_MARGIN, dp(10))
        cell = avail / self.WEEKS_VISIBLE - self.CELL_GAP
        return max(self.CELL_SIZE, min(cell, self.CELL_MAX))
        self._day_values: dict[str, float] = {}  # "YYYY-MM-DD" -> avg_shamatha
        self._day_rects: dict[str, object] = {}
        self._on_day_tap: Optional[Callable] = None
        self._selected_date: Optional[str] = None
        self.bind(size=self._redraw, pos=self._redraw)

    def set_data(self, day_values: dict[str, float]) -> None:
        """Set day→score mapping and redraw."""
        self._day_values = day_values
        self._redraw()

    def set_day_tap_callback(self, cb: Callable) -> None:
        self._on_day_tap = cb

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        # Find which cell was tapped
        for date_str, (rx, ry, rw, rh) in self._cell_positions.items():
            if rx <= touch.x <= rx + rw and ry <= touch.y <= ry + rh:
                self._selected_date = date_str
                self._redraw()
                if self._on_day_tap:
                    self._on_day_tap(date_str)
                return True
        return super().on_touch_down(touch)

    def _redraw(self, *args):
        self.canvas.clear()
        self._cell_positions = {}
        today = datetime.date.today()
        # Start from WEEKS_VISIBLE weeks ago, aligned to Monday
        start = today - datetime.timedelta(days=today.weekday(), weeks=self.WEEKS_VISIBLE - 1)
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
            # Day-of-week labels (M, W, F)
            for i, label_text in enumerate(["M", "", "W", "", "F", "", "S"]):
                if label_text:
                    lx = self.x
                    ly = y_top - i * (cell + gap) - cell
                    Color(*C.TEXT_MUTED)
                    # We'll use rectangles for cells; labels via texture below

            # Month labels and cells
            prev_month = -1
            current = start
            col = 0
            while current <= today:
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
                rect = RoundedRectangle(pos=(cx, cy), size=(cell, cell), radius=[dp(2)])
                self._cell_positions[date_str] = (cx, cy, cell, cell)

                # Month label at column top when month changes
                if current.month != prev_month and dow <= 3:
                    Color(*C.TEXT_MUTED)
                    # Month text rendered as small rect indicator
                    prev_month = current.month

                if dow == 6:
                    col += 1
                current += datetime.timedelta(days=1)

        # Render text labels using Label textures
        # (Kivy canvas can't render text directly; we overlay labels)
        self._render_labels(x0, y_top, start, cell, gap)

    def _render_labels(self, x0, y_top, start, cell, gap):
        """Add day-of-week and month text labels."""
        # Remove old label widgets
        for child in list(self.children):
            self.remove_widget(child)

        # Day-of-week labels
        for i, text in enumerate(["M", "", "W", "", "F", "", "S"]):
            if text:
                lbl = Label(
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
        today = datetime.date.today()
        current = start
        col = 0
        prev_month = -1
        while current <= today:
            dow = current.weekday()
            if current.day <= 7 and current.month != prev_month and dow <= 3:
                month_name = current.strftime("%b")
                mx = x0 + col * (cell + gap)
                lbl = Label(
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


class Last14DaysBars(Widget):
    """14-day bar chart of avg shamatha — alternative to the calendar heatmap.

    Public API mirrors CalendarHeatmap so HistoryScreen can swap them.
    Renders a y-axis with gridlines/labels at 0/25/50/75/100, per-bar score
    labels above non-empty bars, and a polyline trend through bar tops.
    """

    DAYS = 14
    MIN_BAR_HEIGHT = dp(2)
    BASELINE_HEIGHT = dp(20)  # space for date labels under bars
    PAD_LEFT = dp(24)         # space for y-axis labels
    PAD_RIGHT = dp(4)
    GRID_VALUES = (0, 25, 50, 75, 100)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.height = dp(132)
        self._day_values: dict[str, float] = {}
        self._cell_positions: dict[str, tuple] = {}
        self._on_day_tap: Optional[Callable] = None
        self._selected_date: Optional[str] = None
        self.bind(size=self._redraw, pos=self._redraw)

    def set_data(self, day_values: dict[str, float]) -> None:
        self._day_values = day_values
        self._redraw()

    def set_day_tap_callback(self, cb: Callable) -> None:
        self._on_day_tap = cb

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        for date_str, (rx, ry, rw, rh) in self._cell_positions.items():
            if rx <= touch.x <= rx + rw and ry <= touch.y <= ry + rh:
                self._selected_date = date_str
                self._redraw()
                if self._on_day_tap:
                    self._on_day_tap(date_str)
                return True
        return super().on_touch_down(touch)

    def _redraw(self, *args):
        self.canvas.clear()
        self._cell_positions = {}
        if self.width < 10 or self.height < 10:
            return

        today = datetime.date.today()
        days = [today - datetime.timedelta(days=i) for i in range(self.DAYS - 1, -1, -1)]

        avail_w = max(self.width - self.PAD_LEFT - self.PAD_RIGHT, dp(10))
        slot_w = avail_w / self.DAYS
        bar_w = max(slot_w - dp(4), dp(4))

        graph_h = self.height - self.BASELINE_HEIGHT
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
            ylbl = Label(
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
            day_lbl = Label(
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
                score_lbl = Label(
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


class HistoryScreen(Screen):
    """Unified history: calendar heatmap + session list + session detail."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "history"
        self._on_session_select: Optional[Callable] = None
        self._on_save_notes: Optional[Callable] = None
        self._on_delete_session: Optional[Callable] = None
        self._on_export_csv: Optional[Callable] = None
        self._on_rename_session: Optional[Callable] = None
        self._sessions: list[dict] = []
        self._filtered_date: Optional[str] = None
        self._view_mode: str = "calendar"
        self._on_view_mode_change: Optional[Callable] = None
        self._build_ui()
        C.add_listener(self._refresh_theme)

    def _build_ui(self) -> None:
        self._root = BoxLayout(orientation="vertical", padding=S.PAGE_PAD, spacing=S.GAP)
        root = self._root
        with root.canvas.before:
            Color(*C.BG)
            self._bg = Rectangle(size=root.size, pos=root.pos)
        root.bind(
            size=lambda w, v: setattr(self._bg, "size", v),
            pos=lambda w, v: setattr(self._bg, "pos", v),
        )

        # Title
        title = Label(
            text="History",
            font_size=F.H1,
            bold=True,
            color=C.TEXT,
            size_hint_y=None,
            height=dp(32),
            halign="left",
            valign="middle",
        )
        title.bind(size=title.setter("text_size"))
        root.add_widget(title)

        # Graph row: graph (calendar OR bars) on the left, narrow toggle
        # column (Cal / 14d) on the right. Row height tracks the visible
        # graph's height so the heatmap can grow when the window widens.
        self._graph_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(132),
            spacing=dp(4),
        )

        # Graph wrapper holds both views; only one is visible at a time
        # (the other has height=0 + opacity=0).
        graph_wrap = BoxLayout(orientation="vertical", size_hint_x=1)

        # Calendar heatmap
        self._heatmap = CalendarHeatmap()
        self._heatmap.set_day_tap_callback(self._on_day_tap)
        self._heatmap.bind(height=self._on_active_graph_height_change)
        graph_wrap.add_widget(self._heatmap)

        # Bar-chart view (initially hidden)
        self._bars = Last14DaysBars()
        self._bars.set_day_tap_callback(self._on_day_tap)
        self._bars.opacity = 0
        self._bars.disabled = True
        self._bars.size_hint_y = None
        self._bars.height = 0
        self._bars.bind(height=self._on_active_graph_height_change)
        graph_wrap.add_widget(self._bars)

        self._graph_row.add_widget(graph_wrap)

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
            text_color=C.TEXT,
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

        root.add_widget(self._graph_row)

        # Date label + Show All button
        date_row = BoxLayout(size_hint_y=None, height=dp(28), spacing=S.GAP)
        self._date_label = Label(
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
        root.add_widget(date_row)

        root.add_widget(Divider())

        # Session list (scrollable)
        scroll = ScrollView()
        self._session_list = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=S.GAP_SM,
            padding=[0, S.GAP_SM],
        )
        self._session_list.bind(minimum_height=self._session_list.setter("height"))
        # Single manual touch router for the session list. Avoids flakiness
        # with Kivy's nested widget on_touch_down dispatch: we explicitly find
        # which row/action the tap landed on and call the right callback.
        self._session_list.bind(on_touch_down=self._list_touch_down)
        scroll.add_widget(self._session_list)
        root.add_widget(scroll)

        self.add_widget(root)

    def set_callbacks(
        self,
        on_session_select=None,
        on_save_notes=None,
        on_delete_session=None,
        on_export_csv=None,
        on_rename_session=None,
    ) -> None:
        self._on_session_select = on_session_select
        self._on_save_notes = on_save_notes
        self._on_delete_session = on_delete_session
        self._on_export_csv = on_export_csv
        self._on_rename_session = on_rename_session

    def _on_active_graph_height_change(self, instance, value):
        """Match graph_row height to whichever child widget is active.

        Bound to both _heatmap.height and _bars.height. Each toggles to 0
        when hidden; we ignore those zeros and pick up the non-zero one.
        """
        if value > 0:
            self._graph_row.height = value

    def _redraw_heatmap_after_layout(self, *args):
        """Force a heatmap _redraw after Kivy's layout pass settles.

        When set_view_mode flips heatmap.height from 0 to cal_h, the size
        bind fires _redraw synchronously — but heatmap.y is still its
        stale value from the bars view (top of graph_wrap). Cells render
        offset. We schedule a redraw twice:
        - 0s: at end of current tick (catches simple cases)
        - 0.05s: after one frame (catches deferred BoxLayout layout pass)
        """
        from kivy.clock import Clock
        Clock.schedule_once(lambda dt: self._heatmap._redraw(), 0)
        Clock.schedule_once(lambda dt: self._heatmap._redraw(), 0.05)

    def set_view_mode(self, mode: str) -> None:
        """Switch between 'calendar' and 'bars'."""
        if mode not in ("calendar", "bars"):
            return
        self._view_mode = mode
        if mode == "calendar":
            # Compute current cell-based height (it adapts to width)
            cell = self._heatmap._compute_cell_size()
            cal_h = 7 * (cell + self._heatmap.CELL_GAP) + self._heatmap.TOP_MARGIN
            self._heatmap.opacity = 1
            self._heatmap.disabled = False
            self._heatmap.size_hint_y = None
            self._heatmap.height = cal_h
            self._bars.opacity = 0
            self._bars.disabled = True
            self._bars.height = 0
            self._btn_calendar.bg_color = C.PRIMARY
            self._btn_calendar.text_color = C.TEXT
            self._btn_calendar.bold = True
            self._btn_bars.bg_color = C.BG_CARD
            self._btn_bars.text_color = C.TEXT_SECONDARY
            self._btn_bars.bold = False
            # Re-render after parent re-layout settles heatmap.y
            self._redraw_heatmap_after_layout()
        else:
            self._heatmap.opacity = 0
            self._heatmap.disabled = True
            self._heatmap.height = 0
            self._bars.opacity = 1
            self._bars.disabled = False
            self._bars.size_hint_y = None
            self._bars.height = dp(132)
            self._btn_calendar.bg_color = C.BG_CARD
            self._btn_calendar.text_color = C.TEXT_SECONDARY
            self._btn_calendar.bold = False
            self._btn_bars.bg_color = C.PRIMARY
            self._btn_bars.text_color = C.TEXT
            self._btn_bars.bold = True

    def set_view_mode_callback(self, cb: Callable) -> None:
        """Called with the new mode string when the user toggles."""
        self._on_view_mode_change = cb

    def _on_toggle_pressed(self, mode: str) -> None:
        self.set_view_mode(mode)
        if self._on_view_mode_change:
            self._on_view_mode_change(mode)

    def load_sessions(self, sessions: list[dict]) -> None:
        """Load all sessions and build heatmap data."""
        self._sessions = sessions
        # Build day → avg shamatha mapping
        day_scores: dict[str, list[float]] = {}
        for s in sessions:
            dt_str = s.get("date_time", "")
            if len(dt_str) >= 10:
                day = dt_str[:10]
                score = s.get("avg_shamatha", 0) or 0
                day_scores.setdefault(day, []).append(score)

        day_avg = {}
        for day, scores in day_scores.items():
            day_avg[day] = sum(scores) / len(scores) if scores else 0

        self._heatmap.set_data(day_avg)
        self._bars.set_data(day_avg)
        # Show all sessions initially
        self._show_sessions(sessions, "All sessions")

    def _on_day_tap(self, date_str: str) -> None:
        """Filter sessions to the tapped day. Tap again to reset."""
        if date_str == self._filtered_date:
            self._reset_filter()
            return
        self._filtered_date = date_str
        day_sessions = [
            s for s in self._sessions
            if s.get("date_time", "")[:10] == date_str
        ]
        try:
            dt = datetime.date.fromisoformat(date_str)
            nice_date = dt.strftime("%B %d, %Y")
        except (ValueError, TypeError):
            nice_date = date_str
        self._show_sessions(day_sessions, nice_date)
        self._btn_show_all.opacity = 1
        self._btn_show_all.disabled = False

    def _reset_filter(self) -> None:
        """Clear day filter and show all sessions."""
        self._filtered_date = None
        self._heatmap._selected_date = None
        self._heatmap._redraw()
        self._show_sessions(self._sessions, "All sessions")
        self._btn_show_all.opacity = 0
        self._btn_show_all.disabled = True

    def _show_sessions(self, sessions: list[dict], header: str) -> None:
        """Populate the session list."""
        self._session_list.clear_widgets()
        self._date_label.text = f"{header} ({len(sessions)} sessions)"

        if not sessions:
            lbl = Label(
                text="No sessions on this day",
                font_size=F.BODY,
                color=C.TEXT_MUTED,
                size_hint_y=None,
                height=dp(40),
            )
            self._session_list.add_widget(lbl)
            return

        for s in sessions:
            self._session_list.add_widget(self._make_session_row(s))

    def _make_session_row(self, session: dict) -> BoxLayout:
        """Create a session row: tap to view, rename/delete buttons on right."""
        sid = session.get("id", 0)
        dt_str = session.get("date_time", "")
        duration = session.get("duration", 0)
        avg_sh = session.get("avg_shamatha", 0) or 0
        name = session.get("session_name", "") or ""

        time_str = dt_str[11:16] if len(dt_str) > 16 else dt_str
        if not name:
            name = f"{time_str} ({format_duration(duration)})"

        # Outer wrapper holds the normal row + hidden rename input
        wrapper = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(56),
            spacing=0,
        )

        row = Card(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(56),
            bg_color=C.BG_CARD,
            spacing=S.GAP_SM,
            padding=0,
        )

        # Score indicator (colored bar)
        score_color = _lerp_color(avg_sh)
        score_bar = Widget(size_hint_x=None, width=dp(4))
        with score_bar.canvas:
            Color(*score_color)
            score_bar._rect = RoundedRectangle(
                pos=score_bar.pos, size=score_bar.size, radius=[dp(2)]
            )
        score_bar.bind(
            pos=lambda w, v: setattr(w._rect, "pos", v),
            size=lambda w, v: setattr(w._rect, "size", v),
        )
        row.add_widget(score_bar)

        # Info column (tappable → session detail)
        info = BoxLayout(orientation="vertical", padding=[dp(6), 0])
        name_label = Label(
            text=name,
            font_size=F.BODY,
            color=C.TEXT,
            halign="left",
            valign="middle",
            size_hint_y=0.55,
        )
        name_label.bind(size=name_label.setter("text_size"))
        stats_line = Label(
            text=f"Shamatha: {avg_sh:.0f}  |  {format_duration(duration)}",
            font_size=F.TINY,
            color=C.TEXT_MUTED,
            halign="left",
            valign="middle",
            size_hint_y=0.45,
        )
        stats_line.bind(size=stats_line.setter("text_size"))
        info.add_widget(name_label)
        info.add_widget(stats_line)
        row.add_widget(info)

        # Row/button actions are routed manually via _list_touch_down
        # at the session-list level. See _list_touch_down for details.

        # Right side: rename + delete buttons (visual only)
        actions = BoxLayout(
            orientation="horizontal",
            size_hint_x=None,
            width=dp(80),
            spacing=dp(2),
        )
        btn_rename = StyledButton(
            text="", icon=Icons.PENCIL,
            bg_color=C.PRIMARY,
            text_color=C.PRIMARY,
            font_size=F.SMALL,
            size_hint_y=1,  # fill parent height so click area matches visible area
            bold=False,
            outline=True,
        )
        btn_del = StyledButton(
            text="", icon=Icons.DELETE,
            bg_color=C.DANGER,
            text_color=C.DANGER,
            font_size=F.SMALL,
            size_hint_y=1,
            bold=False,
            outline=True,
        )
        actions.add_widget(btn_rename)
        actions.add_widget(btn_del)
        row.add_widget(actions)

        wrapper.add_widget(row)

        # Hidden rename input row (shown when rename button pressed).
        # disabled=True is required — otherwise the fixed-size rename_save
        # button inside stays 60×34dp at the wrapper's bottom edge and
        # steals touches from the delete button above it.
        rename_row = BoxLayout(
            size_hint_y=None,
            height=0,
            spacing=S.GAP_SM,
            padding=[dp(10), 0],
            opacity=0,
            disabled=True,
        )
        rename_input = TextInput(
            text=name,
            font_size=F.BODY,
            foreground_color=C.TEXT,
            background_color=list(C.BG_INPUT),
            cursor_color=C.PRIMARY,
            multiline=False,
            write_tab=False,
            size_hint_x=1,
        )
        rename_save = StyledButton(
            text="Save", icon=Icons.CHECK,
            bg_color=C.ACCENT,
            font_size=F.SMALL,
            height=dp(34),
            size_hint_x=None,
            width=dp(60),
        )
        rename_row.add_widget(rename_input)
        rename_row.add_widget(rename_save)
        wrapper.add_widget(rename_row)

        # Wire rename toggle
        def _toggle_rename(*args):
            if rename_row.opacity == 0:
                rename_row.opacity = 1
                rename_row.height = dp(38)
                rename_row.disabled = False
                wrapper.height = dp(56) + dp(38) + dp(2)
                rename_input.focus = True
            else:
                rename_row.opacity = 0
                rename_row.height = 0
                rename_row.disabled = True
                wrapper.height = dp(56)

        def _do_rename(*args):
            txt = rename_input.text.strip()
            if txt:
                name_label.text = txt
                if self._on_rename_session:
                    self._on_rename_session(sid, txt)
            _toggle_rename()

        # rename_save and rename_input still fire directly (they're inside
        # the expanded rename_row which _list_touch_down lets propagate).
        rename_save.bind(on_release=_do_rename)
        rename_input.bind(on_text_validate=_do_rename)

        # Store per-wrapper opts so the session-list router can dispatch.
        wrapper._session_opts = {
            "sid": sid,
            "name": name,
            "rename_row": rename_row,
            "toggle_rename": _toggle_rename,
        }

        return wrapper

    def _confirm_delete(self, session_id: int, name: str) -> None:
        """Show a delete confirmation popup."""
        from kivy.uix.popup import Popup

        content = BoxLayout(orientation="vertical", spacing=S.GAP, padding=S.GAP)
        content.add_widget(Label(
            text=f"Delete session\n\"{name}\"?",
            font_size=F.BODY,
            color=C.TEXT,
            halign="center",
            valign="middle",
            size_hint_y=0.6,
        ))
        btn_row = BoxLayout(spacing=S.GAP, size_hint_y=0.4)
        btn_cancel = StyledButton(
            text="Cancel",
            bg_color=C.BG_CARD,
            text_color=C.TEXT_SECONDARY,
            height=dp(38),
        )
        btn_confirm = StyledButton(
            text="Delete",
            bg_color=C.DANGER,
            height=dp(38),
        )
        btn_row.add_widget(btn_cancel)
        btn_row.add_widget(btn_confirm)
        content.add_widget(btn_row)

        popup = Popup(
            title="Confirm Delete",
            content=content,
            size_hint=(0.7, 0.3),
            auto_dismiss=True,
        )
        btn_cancel.bind(on_release=popup.dismiss)

        def _do_delete(*args):
            popup.dismiss()
            if self._on_delete_session:
                self._on_delete_session(session_id)

        btn_confirm.bind(on_release=_do_delete)
        popup.open()

    def _list_touch_down(self, list_widget, touch) -> bool:
        """Single touch router for the session list.

        Bypasses Kivy's flaky nested dispatch for row actions. We walk the
        visible wrappers, find the one the tap landed in, and route to
        rename/delete/navigate based on x-position.
        """
        if not list_widget.collide_point(*touch.pos):
            return False
        for wrapper in list_widget.children:
            opts = getattr(wrapper, "_session_opts", None)
            if opts is None:
                continue
            if not wrapper.collide_point(*touch.pos):
                continue
            rename_row = opts["rename_row"]
            # If rename editor is open and touch is in it, let Kivy dispatch
            # normally so the TextInput + Save button work.
            if rename_row.opacity > 0 and rename_row.collide_point(*touch.pos):
                return False
            # actions strip: rightmost dp(80) of the row area
            actions_left = wrapper.right - dp(80)
            if touch.x >= actions_left:
                mid = actions_left + dp(80) / 2
                if touch.x < mid:
                    opts["toggle_rename"]()
                else:
                    self._confirm_delete(opts["sid"], opts["name"])
                return True
            # Body tap → open session detail
            if self._on_session_select:
                self._on_session_select(opts["sid"])
            return True
        return False

    def _refresh_theme(self):
        """Update background when theme changes."""
        self._root.canvas.before.clear()
        with self._root.canvas.before:
            Color(*C.BG)
            self._bg = Rectangle(size=self._root.size, pos=self._root.pos)
        self._date_label.color = C.TEXT_SECONDARY
        self._heatmap._redraw()
