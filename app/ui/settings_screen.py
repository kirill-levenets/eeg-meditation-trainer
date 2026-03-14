from typing import Callable, Dict, Optional

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider

from app.config import METRICS


class SettingsScreen(Screen):
    """Settings screen with threshold slider, graph toggles, and audio config."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "settings"
        self._on_threshold_change: Optional[Callable] = None
        self._on_toggle_change: Optional[Callable] = None
        self._graph_toggles: Dict[str, bool] = {
            "meditation_score": True,
            "shamatha_score": True,
            "distraction": True,
            "sinking": True,
            "subtle_distraction": True,
        }
        self._build_ui()

    def _build_ui(self) -> None:
        scroll = ScrollView()
        layout = BoxLayout(
            orientation="vertical",
            padding=dp(16),
            spacing=dp(12),
            size_hint_y=None,
        )
        layout.bind(minimum_height=layout.setter("height"))

        title = Label(
            text="Settings",
            font_size=dp(22),
            bold=True,
            size_hint_y=None,
            height=dp(40),
        )
        layout.add_widget(title)

        # --- Threshold section ---
        threshold_title = Label(
            text="Meditation Threshold",
            font_size=dp(16),
            size_hint_y=None,
            height=dp(30),
            halign="left",
        )
        threshold_title.bind(size=threshold_title.setter("text_size"))
        layout.add_widget(threshold_title)

        slider_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self._threshold_slider = Slider(
            min=20,
            max=200,
            value=METRICS.MEDITATION_THRESHOLD_DEFAULT,
            step=1,
            size_hint_x=0.8,
        )
        self._threshold_value_label = Label(
            text=str(METRICS.MEDITATION_THRESHOLD_DEFAULT),
            font_size=dp(16),
            bold=True,
            size_hint_x=0.2,
        )
        self._threshold_slider.bind(value=self._on_slider_value)
        slider_row.add_widget(self._threshold_slider)
        slider_row.add_widget(self._threshold_value_label)
        layout.add_widget(slider_row)

        # --- Audio section ---
        audio_title = Label(
            text="Audio Feedback",
            font_size=dp(16),
            size_hint_y=None,
            height=dp(30),
            halign="left",
        )
        audio_title.bind(size=audio_title.setter("text_size"))
        layout.add_widget(audio_title)

        audio_desc = Label(
            text=(
                "White noise plays continuously.\n"
                "Volume decreases as meditation deepens.\n"
                "Silence when score >= threshold."
            ),
            font_size=dp(12),
            size_hint_y=None,
            height=dp(60),
            color=(0.6, 0.6, 0.6, 1.0),
            halign="left",
        )
        audio_desc.bind(size=audio_desc.setter("text_size"))
        layout.add_widget(audio_desc)

        # --- Graph toggles ---
        graph_title = Label(
            text="Graph Metrics",
            font_size=dp(16),
            size_hint_y=None,
            height=dp(30),
            halign="left",
        )
        graph_title.bind(size=graph_title.setter("text_size"))
        layout.add_widget(graph_title)

        toggle_names = {
            "meditation_score": "Meditation Score",
            "shamatha_score": "Shamatha Score",
            "distraction": "Distraction",
            "sinking": "Sinking",
            "subtle_distraction": "Subtle Distraction",
        }
        self._checkboxes: Dict[str, CheckBox] = {}
        for key, display_name in toggle_names.items():
            row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
            cb = CheckBox(active=True, size_hint_x=0.15)
            cb.metric_key = key
            cb.bind(active=self._on_toggle)
            lbl = Label(
                text=display_name,
                font_size=dp(14),
                size_hint_x=0.85,
                halign="left",
            )
            lbl.bind(size=lbl.setter("text_size"))
            row.add_widget(cb)
            row.add_widget(lbl)
            layout.add_widget(row)
            self._checkboxes[key] = cb

        # --- Info section ---
        spacer = Label(size_hint_y=None, height=dp(20))
        layout.add_widget(spacer)

        info = Label(
            text=(
                "EEG Meditation Trainer v1.0\n"
                "Shamatha meditation with neurofeedback"
            ),
            font_size=dp(11),
            color=(0.5, 0.5, 0.5, 1.0),
            size_hint_y=None,
            height=dp(40),
            halign="center",
        )
        layout.add_widget(info)

        scroll.add_widget(layout)
        self.add_widget(scroll)

    def _on_slider_value(self, instance, value) -> None:
        val = int(value)
        self._threshold_value_label.text = str(val)
        if self._on_threshold_change:
            self._on_threshold_change(val)

    def _on_toggle(self, checkbox, active) -> None:
        key = getattr(checkbox, "metric_key", None)
        if key:
            self._graph_toggles[key] = active
            if self._on_toggle_change:
                self._on_toggle_change(key, active)

    @property
    def threshold(self) -> int:
        return int(self._threshold_slider.value)

    def set_threshold_callback(self, callback: Callable) -> None:
        self._on_threshold_change = callback

    def set_toggle_callback(self, callback: Callable) -> None:
        self._on_toggle_change = callback

    @property
    def graph_toggles(self) -> Dict[str, bool]:
        return dict(self._graph_toggles)
