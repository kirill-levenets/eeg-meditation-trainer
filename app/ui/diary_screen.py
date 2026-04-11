import math
import os
from collections.abc import Callable
from typing import Optional

from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput

from app.ui.raw_eeg_screen import ScrollableGraphWidget
from app.ui.theme import C, F, Icons, S, StyledButton


class _GraphAwareScrollView(ScrollView):
    """ScrollView that yields mouse scroll to graph widgets inside it."""

    def on_scroll_start(self, touch, check_children=True):
        if hasattr(touch, "button") and touch.button in ("scrollup", "scrolldown"):
            # If scroll is over a graph widget, let the graph handle zoom
            for child in self._walk_children():
                if isinstance(child, ScrollableGraphWidget) and child.collide_point(*touch.pos):
                    return False
        return super().on_scroll_start(touch, check_children)

    def _walk_children(self):
        """Yield all descendants recursively."""
        stack = list(self.children)
        while stack:
            child = stack.pop()
            yield child
            if hasattr(child, "children"):
                stack.extend(child.children)

METRICS_PREVIEW_COLORS = {
    "meditation_score": (0.2, 0.6, 1.0, 1.0),
    "shamatha_score": (0.0, 0.9, 0.4, 1.0),
    "distraction": (1.0, 0.3, 0.3, 1.0),
    "sinking": (0.8, 0.5, 0.0, 1.0),
    "subtle_distraction": (0.9, 0.9, 0.2, 1.0),
    "native_attention": (0.6, 0.3, 0.9, 1.0),
    "native_meditation": (0.3, 0.9, 0.9, 1.0),
    "custom_formula": (1.0, 0.4, 0.8, 1.0),
}

METRICS_PREVIEW_SCALES = {
    "meditation_score": 100.0,
    "shamatha_score": 100.0,
    "distraction": 100.0,
    "sinking": 100.0,
    "subtle_distraction": 100.0,
    "native_attention": 100.0,
    "native_meditation": 100.0,
    "custom_formula": 200.0,
}

RAW_EEG_PREVIEW_COLORS = {
    "eeg": (0.3, 0.8, 1.0, 1.0),
}

RAW_EEG_PREVIEW_SCALES = {
    "eeg": 500.0,
}

_SYNTH_RATE: float = 512.0
_TICK_DURATION: float = 0.5
_SAMPLES_PER_TICK: int = int(_SYNTH_RATE * _TICK_DURATION)

_BAND_FREQS = {
    "delta": 2.5,
    "theta": 6.0,
    "alpha1": 9.0,
    "alpha2": 11.0,
    "beta1": 15.0,
    "beta2": 24.0,
    "gamma1": 35.0,
    "gamma2": 45.0,
}

_AMPLITUDE_SCALE: float = 0.0004


def _synthesize_waveform(rows: list[dict]) -> list[float]:
    """Synthesize an approximate EEG waveform from stored band powers.

    For each 2Hz tick, generates ~256 samples (0.5s at 512Hz) by
    combining sine waves at characteristic band frequencies with
    amplitudes proportional to sqrt of the stored band power.
    """
    waveform: list[float] = []
    sample_idx = 0
    for row in rows:
        raw_keys = {
            "delta": "delta_raw", "theta": "theta_raw",
            "alpha1": "alpha1_raw", "alpha2": "alpha2_raw",
            "beta1": "beta1_raw", "beta2": "beta2_raw",
            "gamma1": "gamma1_raw", "gamma2": "gamma2_raw",
        }
        amps = {}
        for band, db_key in raw_keys.items():
            power = max(row.get(db_key, 0.0), 0.0)
            amps[band] = math.sqrt(power) * _AMPLITUDE_SCALE

        for _i in range(_SAMPLES_PER_TICK):
            t = sample_idx / _SYNTH_RATE
            val = 0.0
            for band, freq in _BAND_FREQS.items():
                val += amps.get(band, 0.0) * math.sin(2.0 * math.pi * freq * t)
            waveform.append(val)
            sample_idx += 1

    if not waveform:
        return waveform
    peak = max(abs(v) for v in waveform) or 1.0
    target = 500.0 * 0.8
    scale_factor = target / peak
    return [v * scale_factor for v in waveform]

FREQ_PREVIEW_COLORS = {
    "alpha": (0.1, 0.8, 0.4, 1.0),
    "beta": (0.9, 0.7, 0.1, 1.0),
    "gamma": (1.0, 0.3, 0.3, 1.0),
    "theta": (0.2, 0.5, 0.9, 1.0),
    "delta": (0.4, 0.2, 0.8, 1.0),
}

FREQ_PREVIEW_SCALES = {
    "alpha": 200000.0,
    "beta": 100000.0,
    "gamma": 50000.0,
    "theta": 200000.0,
    "delta": 1500000.0,
}


class SessionListItem(BoxLayout):
    """Single row in the session list."""


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
        self._on_back: Optional[Callable] = None
        self._selected_session_id: Optional[int] = None
        self._sessions_data: list[dict] = []
        self._build_ui()

    def _build_ui(self) -> None:
        self._theme_C = C

        root = BoxLayout(orientation="vertical", padding=S.PAGE_PAD, spacing=S.GAP)
        with root.canvas.before:
            Color(*C.BG)
            self._root_bg = Rectangle(size=root.size, pos=root.pos)
        root.bind(
            size=lambda w, v: setattr(self._root_bg, "size", v),
            pos=lambda w, v: setattr(self._root_bg, "pos", v),
        )

        self._title_label = Label(
            text="Session Diary",
            font_size=F.H1,
            bold=True,
            color=C.TEXT,
            size_hint_y=None,
            height=dp(36),
        )
        root.add_widget(self._title_label)

        # --- Session list (hidden when coming from History) ---
        self._session_list_layout = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(4),
        )
        self._session_list_layout.bind(
            minimum_height=self._session_list_layout.setter("height")
        )
        self._session_scroll = ScrollView(size_hint_y=0.4)
        self._session_scroll.add_widget(self._session_list_layout)
        root.add_widget(self._session_scroll)

        # --- Detail panel ---
        detail_scroll = _GraphAwareScrollView(size_hint_y=0.6)
        self._detail_layout = BoxLayout(
            orientation="vertical",
            padding=dp(8),
            spacing=dp(8),
            size_hint_y=None,
        )
        self._detail_layout.bind(
            minimum_height=self._detail_layout.setter("height")
        )

        # Back button (shown when navigated from History)
        self._back_btn = StyledButton(
            text="Back", icon=Icons.CHEVRON_LEFT,
            font_size=F.BODY,
            size_hint=(None, None),
            width=dp(90),
            height=dp(32),
            bg_color=C.BG_CARD,
            text_color=C.PRIMARY,
            bold=False,
        )
        self._back_btn.bind(on_release=self._on_back_pressed)
        self._detail_layout.add_widget(self._back_btn)

        self._detail_title = Label(
            text="Select a session",
            font_size=F.H2,
            bold=True,
            color=C.TEXT,
            size_hint_y=None,
            height=dp(30),
        )
        self._detail_layout.add_widget(self._detail_title)

        # Stats grid
        self._stats_grid = GridLayout(
            cols=2,
            size_hint_y=None,
            height=dp(180),
            spacing=dp(4),
            padding=dp(4),
        )
        self._detail_stats: dict[str, Label] = {}
        stat_keys = [
            ("duration", "Duration (s)"),
            ("avg_meditation", "Avg Meditation"),
            ("avg_shamatha", "Avg Shamatha"),
            ("time_above_threshold", "Time Above Threshold (s)"),
            ("longest_streak", "Longest Meditation Streak (s)"),
            ("threshold_used", "Threshold Used"),
            ("mood_rating", "Mood Rating"),
        ]
        for key, display in stat_keys:
            lbl_title = Label(
                text=display,
                font_size=F.SMALL,
                color=C.TEXT_SECONDARY,
                halign="left",
                size_hint_y=None,
                height=dp(20),
            )
            lbl_title.bind(size=lbl_title.setter("text_size"))
            lbl_value = Label(
                text="-",
                font_size=F.H3,
                bold=True,
                color=C.TEXT,
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
            font_size=F.BODY,
            color=C.TEXT_SECONDARY,
            size_hint_y=None,
            height=dp(26),
            halign="left",
            valign="bottom",
            padding=[0, dp(4)],
        )
        notes_label.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        self._detail_layout.add_widget(notes_label)

        self._notes_input = TextInput(
            hint_text="Enter session notes...",
            multiline=True,
            size_hint_y=None,
            height=dp(80),
            font_size=F.BODY,
            foreground_color=C.TEXT,
            background_color=list(C.BG_INPUT),
            cursor_color=C.PRIMARY,
        )
        self._detail_layout.add_widget(self._notes_input)

        # Tags
        tags_label = Label(
            text="Tags (comma-separated):",
            font_size=F.BODY,
            color=C.TEXT_SECONDARY,
            size_hint_y=None,
            height=dp(26),
            halign="left",
            valign="bottom",
            padding=[0, dp(4)],
        )
        tags_label.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        self._detail_layout.add_widget(tags_label)

        self._tags_input = TextInput(
            hint_text="morning, calm, focused...",
            multiline=False,
            size_hint_y=None,
            height=dp(34),
            font_size=F.BODY,
            foreground_color=C.TEXT,
            background_color=list(C.BG_INPUT),
            cursor_color=C.PRIMARY,
        )
        self._detail_layout.add_widget(self._tags_input)

        # Mood slider
        mood_row = BoxLayout(size_hint_y=None, height=dp(34), spacing=S.GAP)
        mood_label = Label(
            text="Mood:", font_size=F.BODY, color=C.TEXT_SECONDARY, size_hint_x=0.2,
        )
        self._mood_slider = Slider(min=1, max=5, value=3, step=1, size_hint_x=0.6)
        self._mood_value = Label(
            text="3", font_size=F.H3, bold=True, color=C.TEXT, size_hint_x=0.2,
        )
        self._mood_slider.bind(
            value=lambda inst, val: setattr(self._mood_value, "text", str(int(val)))
        )
        mood_row.add_widget(mood_label)
        mood_row.add_widget(self._mood_slider)
        mood_row.add_widget(self._mood_value)
        self._detail_layout.add_widget(mood_row)

        # Save + Export row
        btn_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=S.GAP)
        self._save_btn = StyledButton(
            text="Save Notes",
            bg_color=C.PRIMARY,
            bg_pressed=C.PRIMARY_DIM,
            height=dp(38),
        )
        self._save_btn.bind(on_release=self._on_save_pressed)
        self._export_btn = StyledButton(
            text="Export CSV",
            bg_color=C.ACCENT,
            bg_pressed=C.ACCENT_DIM,
            height=dp(38),
        )
        self._export_btn.bind(on_release=self._on_export_pressed)
        btn_row.add_widget(self._save_btn)
        btn_row.add_widget(self._export_btn)
        self._detail_layout.add_widget(btn_row)

        self._export_status = Label(
            text="",
            font_size=F.TINY,
            color=C.ACCENT,
            size_hint_y=None,
            height=dp(18),
        )
        self._detail_layout.add_widget(self._export_status)

        # --- Graph tab buttons ---
        graph_tabs = BoxLayout(size_hint_y=None, height=dp(30), spacing=S.GAP_SM)
        self._tab_metrics_btn = StyledButton(
            text="Metrics", font_size=F.SMALL, height=dp(30),
            bg_color=C.PRIMARY, text_color=C.TEXT,
        )
        self._tab_raw_btn = StyledButton(
            text="Raw EEG", font_size=F.SMALL, height=dp(30),
            bg_color=C.BG_CARD, text_color=C.TEXT_SECONDARY,
        )
        self._tab_freq_btn = StyledButton(
            text="Frequencies", font_size=F.SMALL, height=dp(30),
            bg_color=C.BG_CARD, text_color=C.TEXT_SECONDARY,
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
            viewport_seconds=60,
            show_value_labels=True,
            show_timestamps=True,
            size_hint_y=1,
        )
        self._raw_eeg_graph = ScrollableGraphWidget(
            colors=RAW_EEG_PREVIEW_COLORS,
            scales=RAW_EEG_PREVIEW_SCALES,
            viewport_seconds=10,
            show_value_labels=True,
            show_timestamps=True,
            sample_rate=_SYNTH_RATE,
            max_points=int(_SYNTH_RATE * 60),
            bipolar=True,
            size_hint_y=1,
        )
        self._freq_graph = ScrollableGraphWidget(
            colors=FREQ_PREVIEW_COLORS,
            scales=FREQ_PREVIEW_SCALES,
            viewport_seconds=60,
            show_value_labels=True,
            show_timestamps=True,
            auto_scale=True,
            size_hint_y=1,
        )

        # Legend container
        self._legend_container = BoxLayout(
            size_hint_y=None, height=dp(18), spacing=dp(4),
        )
        self._detail_layout.add_widget(self._legend_container)

        self._active_graph_tab: str = "metrics"
        self._cached_metrics_rows: list[dict] = []
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

    def set_back_callback(self, callback: Callable) -> None:
        self._on_back = callback

    def _on_back_pressed(self, *args) -> None:
        # Restore session list when going back
        self._show_list_section(True)
        if self._on_back:
            self._on_back()

    def _show_list_section(self, show: bool) -> None:
        """Show or hide the session list + title, expanding detail to full height."""
        if show:
            self._title_label.height = dp(36)
            self._title_label.opacity = 1
            self._session_scroll.size_hint_y = 0.4
            self._session_scroll.opacity = 1
        else:
            self._title_label.height = 0
            self._title_label.opacity = 0
            self._session_scroll.size_hint_y = 0
            self._session_scroll.opacity = 0

    def populate_sessions(self, sessions: list[dict]) -> None:
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

        C = self._theme_C
        for s in sessions:
            btn = StyledButton(
                text=(
                    f"#{s['id']}  {s.get('date_time', '')[:16]}  "
                    f"{s.get('duration', 0) // 60}min  "
                    f"Shamatha: {s.get('avg_shamatha', 0):.0f}"
                ),
                height=dp(36),
                font_size=F.SMALL,
                bg_color=C.BG_CARD,
                text_color=C.TEXT_SECONDARY,
                bold=False,
            )
            btn.session_id = s["id"]
            btn.bind(on_release=self._on_session_btn)
            self._session_list_layout.add_widget(btn)

    def _on_session_btn(self, btn) -> None:
        C = self._theme_C
        sid = getattr(btn, "session_id", None)
        if sid is not None and self._on_session_select:
            for child in self._session_list_layout.children:
                if hasattr(child, "session_id") and isinstance(child, StyledButton):
                    child.bg_color = C.BG_CARD
                    child.text_color = C.TEXT_SECONDARY
            btn.bg_color = C.PRIMARY_DIM
            btn.text_color = C.TEXT
            self._on_session_select(sid)

    def show_session_detail(self, session: dict, from_history: bool = True) -> None:
        """Display detail for a selected session."""
        if from_history:
            self._show_list_section(False)
        self._selected_session_id = session.get("id")
        self._detail_title.text = f"Session #{session.get('id', '?')} — {session.get('date_time', '')[:16]}"

        for key, label in self._detail_stats.items():
            val = session.get(key, "-")
            label.text = str(val)

        self._notes_input.text = session.get("notes", "")
        self._tags_input.text = session.get("tags", "")
        self._mood_slider.value = session.get("mood_rating", 3) or 3
        session_name = session.get("notes", "").strip()
        if not session_name:
            dt = session.get("date_time", "")[:16]
            dur = session.get("duration", 0) or 0
            session_name = f"Session {dt} ({dur // 60}min)"
        # session_name used for title display only (rename moved to History)
        self._metrics_graph.clear_data()
        self._raw_eeg_graph.clear_data()
        self._freq_graph.clear_data()
        self._cached_metrics_rows = []
        self._switch_graph_tab("metrics")

    def load_metrics_preview(self, metrics_rows: list[dict]) -> None:
        """Load session metrics into all three preview graphs."""
        self._cached_metrics_rows = metrics_rows
        if not metrics_rows:
            return
        self._load_graph_data(metrics_rows)

    def _load_graph_data(self, rows: list[dict]) -> None:
        """Populate all three graphs from metrics rows."""
        # Metrics graph
        metrics_series: dict[str, list[float]] = {k: [] for k in METRICS_PREVIEW_COLORS}
        for row in rows:
            for key in metrics_series:
                metrics_series[key].append(row.get(key, 0.0))
        self._metrics_graph.load_static_data(metrics_series)

        # Raw EEG synthesized waveform from band powers
        synth = _synthesize_waveform(rows)
        eeg_series: dict[str, list[float]] = {"eeg": synth}
        self._raw_eeg_graph.load_static_data(eeg_series)

        # Frequency bands
        freq_series: dict[str, list[float]] = {k: [] for k in FREQ_PREVIEW_COLORS}
        for row in rows:
            freq_series["alpha"].append(row.get("alpha1_raw", 0.0) + row.get("alpha2_raw", 0.0))
            freq_series["beta"].append(row.get("beta1_raw", 0.0) + row.get("beta2_raw", 0.0))
            freq_series["gamma"].append(row.get("gamma1_raw", 0.0) + row.get("gamma2_raw", 0.0))
            freq_series["theta"].append(row.get("theta_raw", 0.0))
            freq_series["delta"].append(row.get("delta_raw", 0.0))
        self._freq_graph.load_static_data(freq_series)

        # Load marker positions
        marker_indices = [i for i, row in enumerate(rows) if row.get("marker", 0)]
        self._metrics_graph.set_markers(marker_indices)
        raw_marker_indices = [i * _SAMPLES_PER_TICK for i in marker_indices]
        self._raw_eeg_graph.set_markers(raw_marker_indices)
        self._freq_graph.set_markers(marker_indices)

        # Scroll to end so user sees latest data and can drag back
        self._metrics_graph.set_scroll_offset(0)
        self._raw_eeg_graph.set_scroll_offset(0)
        self._freq_graph.set_scroll_offset(0)

    def set_metrics_threshold(self, value: float) -> None:
        """Set threshold line on the metrics preview graph."""
        self._metrics_graph.set_threshold(value, "meditation_score")

    def _switch_graph_tab(self, tab: str) -> None:
        """Switch the visible graph in the preview area."""
        self._active_graph_tab = tab
        self._graph_container.clear_widgets()

        C = self._theme_C
        for btn, key in [
            (self._tab_metrics_btn, "metrics"),
            (self._tab_raw_btn, "raw"),
            (self._tab_freq_btn, "freq"),
        ]:
            if key == tab:
                btn.bg_color = C.PRIMARY
                btn.text_color = C.TEXT
            else:
                btn.bg_color = C.BG_CARD
                btn.text_color = C.TEXT_SECONDARY

        if tab == "metrics":
            self._graph_container.add_widget(self._metrics_graph)
            self._metrics_graph._redraw()
        elif tab == "raw":
            self._graph_container.add_widget(self._raw_eeg_graph)
            self._raw_eeg_graph._redraw()
        else:
            self._graph_container.add_widget(self._freq_graph)
            self._freq_graph._redraw()
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

    @staticmethod
    def _get_android_export_dir() -> str:
        """Get writable export directory on Android.

        Uses the same base dir as the DB (tested for write access at startup).
        Falls back to app-private storage if /sdcard isn't writable.
        """
        from app.config import APP
        export_dir = os.path.join(os.path.dirname(APP.DB_PATH), "exports")
        os.makedirs(export_dir, exist_ok=True)
        return export_dir

    def _on_export_pressed(self, *args) -> None:
        if not self._selected_session_id or not self._on_export_csv:
            return

        import sys
        is_android = hasattr(sys, "getandroidapilevel")

        content = BoxLayout(orientation="vertical", spacing=S.GAP, padding=S.GAP)

        if is_android:
            # Android: save directly to app's writable dir (no FileChooser —
            # it can't browse /sdcard on Android 11+ without special permission)
            self._file_chooser = None
            export_dir = self._get_android_export_dir()

            loc_label = Label(
                text="Will appear in:\nDocuments/EEGMeditation/",
                font_size=F.SMALL,
                color=C.TEXT_SECONDARY,
                size_hint_y=None,
                height=dp(40),
                halign="left",
                valign="middle",
            )
            loc_label.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
            content.add_widget(loc_label)
        else:
            # Desktop: FileChooser
            self._file_chooser = FileChooserListView(
                path=os.path.expanduser("~"),
                dirselect=True,
                filters=["!.*"],
            )
            content.add_widget(self._file_chooser)

        # Filename row
        name_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=S.GAP)
        name_label = Label(text="File name:", font_size=F.BODY, size_hint_x=0.25,
                           color=C.TEXT_SECONDARY)
        self._export_filename = TextInput(
            text=f"session_{self._selected_session_id}.csv",
            multiline=False,
            font_size=F.BODY,
            size_hint_x=0.75,
            foreground_color=C.TEXT,
            background_color=list(C.BG_INPUT),
        )
        name_row.add_widget(name_label)
        name_row.add_widget(self._export_filename)
        content.add_widget(name_row)

        btn_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=S.GAP)
        btn_cancel = StyledButton(
            text="Cancel", bg_color=C.BG_CARD, text_color=C.TEXT_SECONDARY, height=dp(40),
        )
        btn_save = StyledButton(
            text="Save", icon=Icons.CHECK, bg_color=C.ACCENT, bg_pressed=C.ACCENT_DIM,
            height=dp(40),
        )
        btn_row.add_widget(btn_cancel)
        btn_row.add_widget(btn_save)
        content.add_widget(btn_row)

        popup = Popup(
            title="Export CSV",
            content=content,
            size_hint=(0.9, 0.4) if is_android else (0.95, 0.85),
        )
        self._export_popup = popup
        btn_cancel.bind(on_release=popup.dismiss)
        btn_save.bind(on_release=lambda x: self._do_export(popup))
        popup.open()

    def _do_export(self, popup) -> None:
        """Perform export and show result popup."""
        try:
            if self._file_chooser is not None:
                # Desktop
                selection = self._file_chooser.selection
                if selection:
                    folder = selection[0]
                    if not os.path.isdir(folder):
                        folder = os.path.dirname(folder)
                else:
                    folder = self._file_chooser.path
            else:
                # Android
                folder = self._get_android_export_dir()

            filename = self._export_filename.text.strip()
            if not filename:
                filename = f"session_{self._selected_session_id}.csv"
            if not filename.endswith(".csv"):
                filename += ".csv"

            # Create folder if needed
            os.makedirs(folder, exist_ok=True)

            full_path = os.path.join(folder, filename)
            popup.dismiss()

            if self._selected_session_id and self._on_export_csv:
                result = self._on_export_csv(self._selected_session_id, full_path)
                if not result:
                    self._show_export_result("No data to export", success=False)
                    return

                # On Android: copy from private storage to shared Documents
                import sys
                if hasattr(sys, "getandroidapilevel"):
                    from app.storage.android_share import copy_to_documents
                    shared = copy_to_documents(result, display_name=filename)
                    if shared:
                        self._show_export_result(
                            f"Saved to:\n{shared}\n\nVisible in file browser",
                            success=True,
                        )
                    else:
                        # MediaStore failed — still saved to private, offer share
                        self._show_export_result(
                            f"Saved to app storage:\n{result}\n\n"
                            "Use Share to send the file",
                            success=True,
                        )
                else:
                    self._show_export_result(
                        f"File saved:\n{result}", success=True,
                    )
        except PermissionError:
            popup.dismiss()
            self._show_export_result(
                f"Permission denied for:\n{folder}\n\n"
                "Try a different folder.",
                success=False,
            )
        except Exception as e:
            popup.dismiss()
            self._show_export_result(f"Export error:\n{e}", success=False)
            from app.logger import logger
            logger.error(f"Export failed: {e}", exc_info=True)

    def _show_export_result(self, message: str, success: bool = True) -> None:
        """Show a result popup after export attempt."""
        content = BoxLayout(orientation="vertical", spacing=S.GAP, padding=S.GAP)
        msg = Label(
            text=message,
            font_size=F.BODY,
            color=C.ACCENT if success else C.DANGER,
            halign="center",
            valign="middle",
            size_hint_y=0.6,
        )
        msg.bind(size=msg.setter("text_size"))
        content.add_widget(msg)

        btn_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=S.GAP)

        btn_ok = StyledButton(
            text="OK",
            bg_color=C.ACCENT if success else C.DANGER,
            height=dp(40),
        )
        btn_row.add_widget(btn_ok)
        content.add_widget(btn_row)

        popup = Popup(
            title="Export Complete" if success else "Export Failed",
            content=content,
            size_hint=(0.8, 0.4),
            auto_dismiss=True,
        )
        btn_ok.bind(on_release=popup.dismiss)
        self._export_result_popup = popup
        popup.open()


