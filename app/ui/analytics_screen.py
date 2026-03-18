from typing import Dict, List

from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget


class TrendGraphWidget(Widget):
    """Simple bar/line chart for analytics trends."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._data: List[Dict] = []
        self._metric_key: str = "avg_shamatha"
        self._title: str = "Shamatha Trend"
        self.bind(size=self._redraw, pos=self._redraw)

    def set_data(self, data: List[Dict], metric_key: str, title: str) -> None:
        self._data = data
        self._metric_key = metric_key
        self._title = title
        self._redraw()

    @staticmethod
    def _make_text_texture(text: str, font_size: int = 10,
                           color: tuple = (0.5, 0.5, 0.5, 1)):
        kw = {"font_size": font_size, "color": color}
        lbl = CoreLabel(text=text, **kw)
        lbl.refresh()
        return lbl.texture

    def _redraw(self, *args) -> None:
        self.canvas.after.clear()
        if self.width < 10 or self.height < 10 or not self._data:
            return

        pad_left = dp(40)
        pad_bottom = dp(36)
        pad_top = dp(10)
        pad_right = dp(10)
        graph_x = self.x + pad_left
        graph_y = self.y + pad_bottom
        graph_w = self.width - pad_left - pad_right
        graph_h = self.height - pad_bottom - pad_top

        if graph_w < 10 or graph_h < 10:
            return

        values = [d.get(self._metric_key, 0) for d in self._data]
        periods = [d.get("period", "") for d in self._data]
        max_val = max(values) if values else 1
        if max_val == 0:
            max_val = 1

        n = len(values)
        bar_w = max(dp(4), graph_w / max(n, 1) * 0.7)
        gap = graph_w / max(n, 1)

        with self.canvas.after:
            # Border
            Color(0.3, 0.3, 0.3, 1.0)
            Line(rectangle=(graph_x, graph_y, graph_w, graph_h), width=1)

            # Y-axis labels (counts/values)
            num_y_labels = 4
            for i in range(num_y_labels + 1):
                frac = i / num_y_labels
                y_pos = graph_y + graph_h * frac
                Color(0.25, 0.25, 0.3, 1.0)
                Line(points=[graph_x, y_pos, graph_x + graph_w, y_pos], width=0.5)
                val = max_val * frac
                tex = self._make_text_texture(
                    f"{val:.0f}", font_size=9, color=(0.5, 0.5, 0.5, 1),
                )
                Color(1, 1, 1, 1)
                Rectangle(
                    texture=tex,
                    pos=(graph_x - tex.width - dp(4), y_pos - tex.height / 2),
                    size=tex.size,
                )

            # Bars
            Color(0.2, 0.6, 1.0, 0.8)
            for i, val in enumerate(values):
                bx = graph_x + i * gap + (gap - bar_w) / 2
                bh = (val / max_val) * graph_h
                Rectangle(pos=(bx, graph_y), size=(bar_w, bh))

            # X-axis labels (time periods)
            max_x_labels = max(1, int(graph_w / dp(50)))
            step = max(1, n // max_x_labels)
            for i in range(0, n, step):
                bx = graph_x + i * gap + gap / 2
                period_text = periods[i]
                if len(period_text) > 10:
                    period_text = period_text[-8:]
                tex = self._make_text_texture(
                    period_text, font_size=8, color=(0.5, 0.5, 0.5, 1),
                )
                Color(1, 1, 1, 1)
                Rectangle(
                    texture=tex,
                    pos=(bx - tex.width / 2, graph_y - tex.height - dp(3)),
                    size=tex.size,
                )


class AnalyticsScreen(Screen):
    """Analytics screen with long-term trends and summary stats."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "analytics"
        self._build_ui()

    def _build_ui(self) -> None:
        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))

        title = Label(
            text="Analytics",
            font_size=dp(20),
            bold=True,
            size_hint_y=None,
            height=dp(36),
        )
        root.add_widget(title)

        # --- Summary cards ---
        summary_row = BoxLayout(size_hint_y=None, height=dp(60), spacing=dp(4))
        self._summary_labels: Dict[str, Label] = {}
        cards = [
            ("total_sessions", "Sessions"),
            ("total_minutes", "Total Min"),
            ("avg_shamatha", "Avg Shamatha"),
            ("current_streak", "Streak"),
        ]
        for key, display in cards:
            card = BoxLayout(orientation="vertical")
            t = Label(
                text=display,
                font_size=dp(10),
                color=(0.6, 0.6, 0.6, 1.0),
                size_hint_y=0.4,
            )
            v = Label(text="0", font_size=dp(18), bold=True, size_hint_y=0.6)
            card.add_widget(t)
            card.add_widget(v)
            self._summary_labels[key] = v
            summary_row.add_widget(card)
        root.add_widget(summary_row)

        # --- Period buttons ---
        period_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(4))
        self._btn_daily = Button(text="Daily", font_size=dp(13))
        self._btn_weekly = Button(text="Weekly", font_size=dp(13))
        self._btn_monthly = Button(text="Monthly", font_size=dp(13))
        period_row.add_widget(self._btn_daily)
        period_row.add_widget(self._btn_weekly)
        period_row.add_widget(self._btn_monthly)
        root.add_widget(period_row)

        # --- Trend graph ---
        self._trend_graph = TrendGraphWidget(size_hint_y=0.5)
        root.add_widget(self._trend_graph)

        # --- Period detail list ---
        self._period_list = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(2),
        )
        self._period_list.bind(
            minimum_height=self._period_list.setter("height")
        )
        period_scroll = ScrollView(size_hint_y=0.25)
        period_scroll.add_widget(self._period_list)
        root.add_widget(period_scroll)

        # Storage info
        self._storage_label = Label(
            text="Storage: —",
            font_size=dp(12),
            color=(0.5, 0.5, 0.5, 1.0),
            size_hint_y=None,
            height=dp(24),
            halign="left",
        )
        self._storage_label.bind(size=self._storage_label.setter("text_size"))
        root.add_widget(self._storage_label)

        self.add_widget(root)

    @property
    def btn_daily(self) -> Button:
        return self._btn_daily

    @property
    def btn_weekly(self) -> Button:
        return self._btn_weekly

    @property
    def btn_monthly(self) -> Button:
        return self._btn_monthly

    def update_storage_info(self, size_bytes: int, counts: Dict[str, int]) -> None:
        """Update the storage info label with DB size and record counts."""
        if size_bytes < 1024:
            size_str = f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            size_str = f"{size_bytes / 1024:.1f} KB"
        else:
            size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
        self._storage_label.text = (
            f"Storage: {size_str}  |  "
            f"{counts.get('sessions', 0)} sessions  |  "
            f"{counts.get('metrics', 0)} data points  |  "
            f"{counts.get('users', 0)} users"
        )

    def update_summary(self, summary: Dict) -> None:
        for key, label in self._summary_labels.items():
            label.text = str(summary.get(key, 0))

    def show_trend(self, data: List[Dict], metric_key: str, title: str) -> None:
        self._trend_graph.set_data(data, metric_key, title)
        self._period_list.clear_widgets()

        for d in data:
            row = Label(
                text=(
                    f"{d.get('period', '?')}:  "
                    f"{d.get('session_count', 0)} sessions  |  "
                    f"Shamatha: {d.get('avg_shamatha', 0):.0f}  |  "
                    f"Duration: {d.get('total_duration', 0) // 60}min"
                ),
                font_size=dp(11),
                size_hint_y=None,
                height=dp(24),
                color=(0.7, 0.7, 0.7, 1.0),
            )
            self._period_list.add_widget(row)
