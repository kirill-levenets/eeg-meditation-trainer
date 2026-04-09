"""History screen: calendar heatmap + session detail.

Replaces separate Diary and Analytics screens. Shows a GitHub-style
contribution heatmap colored by daily avg shamatha score. Tap a day
to see sessions for that date; tap a session to see full detail.
"""

import datetime
from typing import Callable, Dict, List, Optional

from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.screenmanager import Screen
from kivy.uix.widget import Widget

from app.ui.theme import C, F, S, Card, StyledButton, Divider


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

    Shows ~16 weeks (4 months) of data. Each column is a week,
    rows are Mon-Sun. Scrolls horizontally for older data.
    """

    CELL_SIZE = dp(14)
    CELL_GAP = dp(2)
    WEEKS_VISIBLE = 18

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.height = 7 * (self.CELL_SIZE + self.CELL_GAP) + dp(20)  # 7 rows + month labels
        self._day_values: Dict[str, float] = {}  # "YYYY-MM-DD" -> avg_shamatha
        self._day_rects: Dict[str, object] = {}
        self._on_day_tap: Optional[Callable] = None
        self._selected_date: Optional[str] = None
        self.bind(size=self._redraw, pos=self._redraw)

    def set_data(self, day_values: Dict[str, float]) -> None:
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
        cell = self.CELL_SIZE
        gap = self.CELL_GAP
        x0 = self.x + dp(22)  # leave space for day-of-week labels
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
        self._sessions: List[Dict] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = BoxLayout(orientation="vertical", padding=S.PAGE_PAD, spacing=S.GAP)
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

        # Calendar heatmap
        self._heatmap = CalendarHeatmap()
        self._heatmap.set_day_tap_callback(self._on_day_tap)
        root.add_widget(self._heatmap)

        # Selected date label
        self._date_label = Label(
            text="Tap a day to see sessions",
            font_size=F.BODY,
            color=C.TEXT_SECONDARY,
            size_hint_y=None,
            height=dp(24),
            halign="left",
            valign="middle",
        )
        self._date_label.bind(size=self._date_label.setter("text_size"))
        root.add_widget(self._date_label)

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

    def load_sessions(self, sessions: List[Dict]) -> None:
        """Load all sessions and build heatmap data."""
        self._sessions = sessions
        # Build day → avg shamatha mapping
        day_scores: Dict[str, List[float]] = {}
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
        # Show all sessions initially
        self._show_sessions(sessions, "All sessions")

    def _on_day_tap(self, date_str: str) -> None:
        """Filter sessions to the tapped day."""
        day_sessions = [
            s for s in self._sessions
            if s.get("date_time", "")[:10] == date_str
        ]
        # Format date nicely
        try:
            dt = datetime.date.fromisoformat(date_str)
            nice_date = dt.strftime("%B %d, %Y")
        except (ValueError, TypeError):
            nice_date = date_str
        self._show_sessions(day_sessions, nice_date)

    def _show_sessions(self, sessions: List[Dict], header: str) -> None:
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

    def _make_session_row(self, session: Dict) -> BoxLayout:
        """Create a tappable session summary row."""
        sid = session.get("id", 0)
        dt_str = session.get("date_time", "")
        duration = session.get("duration", 0)
        avg_sh = session.get("avg_shamatha", 0) or 0

        # Format time
        time_str = dt_str[11:16] if len(dt_str) > 16 else dt_str
        dur_min = duration // 60
        dur_sec = duration % 60

        row = Card(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(52),
            bg_color=C.BG_CARD,
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

        # Info
        info = BoxLayout(orientation="vertical", padding=[dp(8), 0])
        top_line = Label(
            text=f"{time_str}  |  {dur_min}m {dur_sec:02d}s",
            font_size=F.BODY,
            color=C.TEXT,
            halign="left",
            valign="middle",
            size_hint_y=0.5,
        )
        top_line.bind(size=top_line.setter("text_size"))
        bottom_line = Label(
            text=f"Shamatha: {avg_sh:.0f}",
            font_size=F.SMALL,
            color=C.TEXT_SECONDARY,
            halign="left",
            valign="middle",
            size_hint_y=0.5,
        )
        bottom_line.bind(size=bottom_line.setter("text_size"))
        info.add_widget(top_line)
        info.add_widget(bottom_line)
        row.add_widget(info)

        # Tap handler
        row._session_id = sid
        row.bind(on_touch_down=lambda w, t: self._row_tapped(w, t))

        return row

    def _row_tapped(self, widget, touch) -> bool:
        if not widget.collide_point(*touch.pos):
            return False
        sid = getattr(widget, "_session_id", None)
        if sid and self._on_session_select:
            self._on_session_select(sid)
        return True
