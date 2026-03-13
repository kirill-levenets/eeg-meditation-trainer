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

        detail_scroll.add_widget(self._detail_layout)
        root.add_widget(detail_scroll)

        self.add_widget(root)

    def set_session_select_callback(self, callback: Callable) -> None:
        self._on_session_select = callback

    def set_save_notes_callback(self, callback: Callable) -> None:
        self._on_save_notes = callback

    def set_export_csv_callback(self, callback: Callable) -> None:
        self._on_export_csv = callback

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
