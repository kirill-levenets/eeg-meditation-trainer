from typing import Callable, Dict, List, Optional

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput

from app.ui.raw_eeg_screen import ScrollableGraphWidget

METRICS_PREVIEW_COLORS = {
    "meditation_score": (0.2, 0.6, 1.0, 1.0),
    "shamatha_score": (0.0, 0.9, 0.4, 1.0),
    "distraction": (1.0, 0.3, 0.3, 1.0),
    "sinking": (0.8, 0.5, 0.0, 1.0),
}

METRICS_PREVIEW_SCALES = {
    "meditation_score": 200.0,
    "shamatha_score": 100.0,
    "distraction": 100.0,
    "sinking": 100.0,
}

RAW_EEG_PREVIEW_COLORS = {
    "eeg": (0.3, 0.8, 1.0, 1.0),
}

RAW_EEG_PREVIEW_SCALES = {
    "eeg": 3000.0,
}

FREQ_PREVIEW_COLORS = {
    "alpha": (0.1, 0.8, 0.4, 1.0),
    "beta": (0.9, 0.7, 0.1, 1.0),
    "gamma": (1.0, 0.3, 0.3, 1.0),
    "theta": (0.2, 0.5, 0.9, 1.0),
    "delta": (0.4, 0.2, 0.8, 1.0),
}

FREQ_PREVIEW_SCALES = {
    "alpha": 1600.0,
    "beta": 800.0,
    "gamma": 400.0,
    "theta": 600.0,
    "delta": 800.0,
}


class SessionListItem(BoxLayout):
    """Single row in the session list."""
    pass


class DiaryScreen(Screen):
    """Diary & Analytics screen with session list, details, and notes."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "diary"
        self._on_session_select: Optional[Callable] = None
        self._on_save_notes: Optional[Callable] = None
        self._on_export_csv: Optional[Callable] = None
        self._on_delete_session: Optional[Callable] = None
        self._on_rename_session: Optional[Callable] = None
        self._selected_session_id: Optional[int] = None
        self._sessions_data: List[Dict] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))

        title = Label(
            text="Session Diary",
            font_size=dp(20),
            bold=True,
            size_hint_y=None,
            height=dp(36),
        )
        root.add_widget(title)

        # --- Session list ---
        self._session_list_layout = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(4),
        )
        self._session_list_layout.bind(
            minimum_height=self._session_list_layout.setter("height")
        )
        session_scroll = ScrollView(size_hint_y=0.4)
        session_scroll.add_widget(self._session_list_layout)
        root.add_widget(session_scroll)

        # --- Detail panel ---
        detail_scroll = ScrollView(size_hint_y=0.6)
        self._detail_layout = BoxLayout(
            orientation="vertical",
            padding=dp(8),
            spacing=dp(8),
            size_hint_y=None,
        )
        self._detail_layout.bind(
            minimum_height=self._detail_layout.setter("height")
        )

        self._detail_title = Label(
            text="Select a session",
            font_size=dp(16),
            bold=True,
            size_hint_y=None,
            height=dp(30),
        )
        self._detail_layout.add_widget(self._detail_title)

        # Stats grid
        self._stats_grid = GridLayout(
            cols=2,
            size_hint_y=None,
            height=dp(120),
            spacing=dp(4),
            padding=dp(4),
        )
        self._detail_stats: Dict[str, Label] = {}
        stat_keys = [
            ("duration", "Duration (s)"),
            ("avg_meditation", "Avg Meditation"),
            ("avg_shamatha", "Avg Shamatha"),
            ("time_above_threshold", "Time Above Threshold"),
            ("threshold_used", "Threshold Used"),
            ("mood_rating", "Mood Rating"),
        ]
        for key, display in stat_keys:
            lbl_title = Label(
                text=display,
                font_size=dp(12),
                color=(0.6, 0.6, 0.6, 1.0),
                halign="left",
                size_hint_y=None,
                height=dp(20),
            )
            lbl_title.bind(size=lbl_title.setter("text_size"))
            lbl_value = Label(
                text="-",
                font_size=dp(14),
                bold=True,
                halign="left",
                size_hint_y=None,
                height=dp(20),
            )
            lbl_value.bind(size=lbl_value.setter("text_size"))
            self._stats_grid.add_widget(lbl_title)
            self._stats_grid.add_widget(lbl_value)
            self._detail_stats[key] = lbl_value
        self._detail_layout.add_widget(self._stats_grid)

        # Notes
        notes_label = Label(
            text="Notes:",
            font_size=dp(14),
            size_hint_y=None,
            height=dp(24),
            halign="left",
        )
        notes_label.bind(size=notes_label.setter("text_size"))
        self._detail_layout.add_widget(notes_label)

        self._notes_input = TextInput(
            hint_text="Enter session notes...",
            multiline=True,
            size_hint_y=None,
            height=dp(80),
            font_size=dp(13),
        )
        self._detail_layout.add_widget(self._notes_input)

        # Tags
        tags_label = Label(
            text="Tags (comma-separated):",
            font_size=dp(14),
            size_hint_y=None,
            height=dp(24),
            halign="left",
        )
        tags_label.bind(size=tags_label.setter("text_size"))
        self._detail_layout.add_widget(tags_label)

        self._tags_input = TextInput(
            hint_text="morning, calm, focused...",
            multiline=False,
            size_hint_y=None,
            height=dp(36),
            font_size=dp(13),
        )
        self._detail_layout.add_widget(self._tags_input)

        # Mood slider
        mood_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        mood_label = Label(text="Mood:", font_size=dp(14), size_hint_x=0.2)
        self._mood_slider = Slider(min=1, max=5, value=3, step=1, size_hint_x=0.6)
        self._mood_value = Label(text="3", font_size=dp(14), bold=True, size_hint_x=0.2)
        self._mood_slider.bind(
            value=lambda inst, val: setattr(self._mood_value, "text", str(int(val)))
        )
        mood_row.add_widget(mood_label)
        mood_row.add_widget(self._mood_slider)
        mood_row.add_widget(self._mood_value)
        self._detail_layout.add_widget(mood_row)

        # Save + Export row
        btn_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self._save_btn = Button(
            text="Save Notes",
            background_color=(0.2, 0.6, 0.9, 1.0),
            font_size=dp(14),
            bold=True,
        )
        self._save_btn.bind(on_release=self._on_save_pressed)
        self._export_btn = Button(
            text="Export CSV",
            background_color=(0.3, 0.7, 0.3, 1.0),
            font_size=dp(14),
            bold=True,
        )
        self._export_btn.bind(on_release=self._on_export_pressed)
        btn_row.add_widget(self._save_btn)
        btn_row.add_widget(self._export_btn)
        self._detail_layout.add_widget(btn_row)

        self._export_status = Label(
            text="",
            font_size=dp(11),
            color=(0.5, 0.8, 0.5, 1.0),
            size_hint_y=None,
            height=dp(20),
        )
        self._detail_layout.add_widget(self._export_status)

        # Rename row
        rename_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self._rename_input = TextInput(
            hint_text="New session name...",
            multiline=False,
            size_hint_x=0.65,
            font_size=dp(13),
        )
        self._rename_btn = Button(
            text="Rename",
            background_color=(0.5, 0.5, 0.2, 1.0),
            font_size=dp(14),
            bold=True,
            size_hint_x=0.35,
        )
        self._rename_btn.bind(on_release=self._on_rename_pressed)
        rename_row.add_widget(self._rename_input)
        rename_row.add_widget(self._rename_btn)
        self._detail_layout.add_widget(rename_row)

        # Delete button
        self._delete_btn = Button(
            text="Delete Session",
            background_color=(0.8, 0.2, 0.2, 1.0),
            font_size=dp(14),
            bold=True,
            size_hint_y=None,
            height=dp(40),
        )
        self._delete_btn.bind(on_release=self._on_delete_pressed)
        self._detail_layout.add_widget(self._delete_btn)

        # --- Graph tab buttons ---
        graph_tabs = BoxLayout(size_hint_y=None, height=dp(32), spacing=dp(4))
        self._tab_metrics_btn = Button(
            text="Metrics", font_size=dp(12), bold=True,
            background_color=(0.3, 0.5, 0.8, 1.0),
        )
        self._tab_raw_btn = Button(
            text="Raw EEG", font_size=dp(12), bold=True,
            background_color=(0.2, 0.2, 0.3, 1.0),
        )
        self._tab_freq_btn = Button(
            text="Frequencies", font_size=dp(12), bold=True,
            background_color=(0.2, 0.2, 0.3, 1.0),
        )
        self._tab_metrics_btn.bind(on_release=lambda x: self._switch_graph_tab("metrics"))
        self._tab_raw_btn.bind(on_release=lambda x: self._switch_graph_tab("raw"))
        self._tab_freq_btn.bind(on_release=lambda x: self._switch_graph_tab("freq"))
        graph_tabs.add_widget(self._tab_metrics_btn)
        graph_tabs.add_widget(self._tab_raw_btn)
        graph_tabs.add_widget(self._tab_freq_btn)
        self._detail_layout.add_widget(graph_tabs)

        # --- Graph container (holds one graph at a time) ---
        self._graph_container = BoxLayout(
            orientation="vertical", size_hint_y=None, height=dp(200),
        )
        self._detail_layout.add_widget(self._graph_container)

        # Create all three graphs
        self._metrics_graph = ScrollableGraphWidget(
            colors=METRICS_PREVIEW_COLORS,
            scales=METRICS_PREVIEW_SCALES,
            viewport_seconds=300,
            show_value_labels=True,
            show_timestamps=True,
            size_hint_y=1,
        )
        self._raw_eeg_graph = ScrollableGraphWidget(
            colors=RAW_EEG_PREVIEW_COLORS,
            scales=RAW_EEG_PREVIEW_SCALES,
            viewport_seconds=300,
            show_value_labels=True,
            show_timestamps=True,
            size_hint_y=1,
        )
        self._freq_graph = ScrollableGraphWidget(
            colors=FREQ_PREVIEW_COLORS,
            scales=FREQ_PREVIEW_SCALES,
            viewport_seconds=300,
            show_value_labels=True,
            show_timestamps=True,
            size_hint_y=1,
        )

        # Legend container
        self._legend_container = BoxLayout(
            size_hint_y=None, height=dp(18), spacing=dp(4),
        )
        self._detail_layout.add_widget(self._legend_container)

        self._active_graph_tab: str = "metrics"
        self._cached_metrics_rows: List[Dict] = []
        self._graph_container.add_widget(self._metrics_graph)
        self._rebuild_legend("metrics")

        detail_scroll.add_widget(self._detail_layout)
        root.add_widget(detail_scroll)

        self.add_widget(root)

    def set_session_select_callback(self, callback: Callable) -> None:
        self._on_session_select = callback

    def set_save_notes_callback(self, callback: Callable) -> None:
        self._on_save_notes = callback

    def set_export_csv_callback(self, callback: Callable) -> None:
        self._on_export_csv = callback

    def set_delete_session_callback(self, callback: Callable) -> None:
        self._on_delete_session = callback

    def set_rename_session_callback(self, callback: Callable) -> None:
        self._on_rename_session = callback

    def populate_sessions(self, sessions: List[Dict]) -> None:
        """Fill the session list from DB data."""
        self._sessions_data = sessions
        self._session_list_layout.clear_widgets()

        if not sessions:
            lbl = Label(
                text="No sessions yet",
                font_size=dp(14),
                color=(0.5, 0.5, 0.5, 1.0),
                size_hint_y=None,
                height=dp(40),
            )
            self._session_list_layout.add_widget(lbl)
            return

        for s in sessions:
            btn = Button(
                text=(
                    f"#{s['id']}  {s.get('date_time', '')[:16]}  "
                    f"{s.get('duration', 0) // 60}min  "
                    f"Shamatha: {s.get('avg_shamatha', 0):.0f}"
                ),
                size_hint_y=None,
                height=dp(36),
                font_size=dp(12),
                background_color=(0.15, 0.15, 0.2, 1.0),
            )
            btn.session_id = s["id"]
            btn.bind(on_release=self._on_session_btn)
            self._session_list_layout.add_widget(btn)

    def _on_session_btn(self, btn) -> None:
        sid = getattr(btn, "session_id", None)
        if sid is not None and self._on_session_select:
            self._on_session_select(sid)

    def show_session_detail(self, session: Dict) -> None:
        """Display detail for a selected session."""
        self._selected_session_id = session.get("id")
        self._detail_title.text = f"Session #{session.get('id', '?')} — {session.get('date_time', '')[:16]}"

        for key, label in self._detail_stats.items():
            val = session.get(key, "-")
            label.text = str(val)

        self._notes_input.text = session.get("notes", "")
        self._tags_input.text = session.get("tags", "")
        self._mood_slider.value = session.get("mood_rating", 3) or 3
        self._metrics_graph.clear_data()
        self._raw_eeg_graph.clear_data()
        self._freq_graph.clear_data()
        self._cached_metrics_rows = []
        self._switch_graph_tab("metrics")

    def load_metrics_preview(self, metrics_rows: List[Dict]) -> None:
        """Load session metrics into all three preview graphs."""
        self._cached_metrics_rows = metrics_rows
        if not metrics_rows:
            return
        self._load_graph_data(metrics_rows)

    def _load_graph_data(self, rows: List[Dict]) -> None:
        """Populate all three graphs from metrics rows."""
        # Metrics graph
        metrics_series: Dict[str, List[float]] = {k: [] for k in METRICS_PREVIEW_COLORS}
        for row in rows:
            for key in metrics_series:
                metrics_series[key].append(row.get(key, 0.0))
        self._metrics_graph.load_static_data(metrics_series)

        # Raw EEG composite signal
        eeg_series: Dict[str, List[float]] = {"eeg": []}
        raw_keys = ("delta_raw", "theta_raw", "alpha1_raw", "alpha2_raw",
                     "beta1_raw", "beta2_raw", "gamma1_raw", "gamma2_raw")
        for row in rows:
            eeg_sum = sum(row.get(k, 0.0) for k in raw_keys)
            eeg_series["eeg"].append(eeg_sum)
        self._raw_eeg_graph.load_static_data(eeg_series)

        # Frequency bands
        freq_series: Dict[str, List[float]] = {k: [] for k in FREQ_PREVIEW_COLORS}
        for row in rows:
            freq_series["alpha"].append(row.get("alpha1_raw", 0.0) + row.get("alpha2_raw", 0.0))
            freq_series["beta"].append(row.get("beta1_raw", 0.0) + row.get("beta2_raw", 0.0))
            freq_series["gamma"].append(row.get("gamma1_raw", 0.0) + row.get("gamma2_raw", 0.0))
            freq_series["theta"].append(row.get("theta_raw", 0.0))
            freq_series["delta"].append(row.get("delta_raw", 0.0))
        self._freq_graph.load_static_data(freq_series)

    def _switch_graph_tab(self, tab: str) -> None:
        """Switch the visible graph in the preview area."""
        self._active_graph_tab = tab
        self._graph_container.clear_widgets()

        active_color = (0.3, 0.5, 0.8, 1.0)
        inactive_color = (0.2, 0.2, 0.3, 1.0)
        self._tab_metrics_btn.background_color = active_color if tab == "metrics" else inactive_color
        self._tab_raw_btn.background_color = active_color if tab == "raw" else inactive_color
        self._tab_freq_btn.background_color = active_color if tab == "freq" else inactive_color

        if tab == "metrics":
            self._graph_container.add_widget(self._metrics_graph)
        elif tab == "raw":
            self._graph_container.add_widget(self._raw_eeg_graph)
        else:
            self._graph_container.add_widget(self._freq_graph)
        self._rebuild_legend(tab)

    def _rebuild_legend(self, tab: str) -> None:
        """Rebuild legend labels for the active graph tab."""
        self._legend_container.clear_widgets()
        if tab == "metrics":
            colors = METRICS_PREVIEW_COLORS
        elif tab == "raw":
            colors = RAW_EEG_PREVIEW_COLORS
        else:
            colors = FREQ_PREVIEW_COLORS
        for name, color in colors.items():
            short = name.replace("_score", "").replace("_", " ").title()
            lbl = Label(text=short, font_size=dp(9), color=color)
            self._legend_container.add_widget(lbl)

    def _on_save_pressed(self, *args) -> None:
        if self._selected_session_id and self._on_save_notes:
            self._on_save_notes(
                self._selected_session_id,
                self._notes_input.text,
                self._tags_input.text,
                int(self._mood_slider.value),
            )

    def _on_export_pressed(self, *args) -> None:
        if self._selected_session_id and self._on_export_csv:
            path = self._on_export_csv(self._selected_session_id)
            if path:
                self._export_status.text = f"Exported: {path}"
            else:
                self._export_status.text = "No data to export"

    def _on_delete_pressed(self, *args) -> None:
        if self._selected_session_id and self._on_delete_session:
            self._on_delete_session(self._selected_session_id)
            self._selected_session_id = None
            self._detail_title.text = "Select a session"
            self._export_status.text = "Session deleted"
            self._rename_input.text = ""

    def _on_rename_pressed(self, *args) -> None:
        new_name = self._rename_input.text.strip()
        if self._selected_session_id and new_name and self._on_rename_session:
            self._on_rename_session(self._selected_session_id, new_name)
            self._notes_input.text = new_name
            self._export_status.text = f"Renamed to: {new_name}"
