from typing import Callable, Optional

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.slider import Slider

from app.config import APP


class TimerScreen(Screen):
    """Meditation timer with configurable duration and enable/disable toggle.

    When enabled and a session is running, the timer counts down from the
    selected duration. When it reaches zero, the session auto-stops.
    By default the timer is disabled.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "timer"
        self._enabled: bool = APP.TIMER_ENABLED
        self._duration_minutes: int = APP.TIMER_DEFAULT_MINUTES
        self._remaining_seconds: float = 0.0
        self._on_timer_finished: Optional[Callable] = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))

        title = Label(
            text="Meditation Timer",
            font_size=dp(22),
            bold=True,
            size_hint_y=None,
            height=dp(40),
        )
        root.add_widget(title)

        # Enable/disable toggle
        toggle_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self._enable_cb = CheckBox(active=self._enabled, size_hint_x=0.15)
        self._enable_cb.bind(active=self._on_enable_toggle)
        enable_lbl = Label(
            text="Enable Timer",
            font_size=dp(16),
            size_hint_x=0.85,
            halign="left",
        )
        enable_lbl.bind(size=enable_lbl.setter("text_size"))
        toggle_row.add_widget(self._enable_cb)
        toggle_row.add_widget(enable_lbl)
        root.add_widget(toggle_row)

        # Duration slider
        dur_label = Label(
            text="Duration (minutes)",
            font_size=dp(14),
            size_hint_y=None,
            height=dp(24),
            halign="left",
        )
        dur_label.bind(size=dur_label.setter("text_size"))
        root.add_widget(dur_label)

        slider_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self._duration_slider = Slider(
            min=1,
            max=120,
            value=self._duration_minutes,
            step=1,
            size_hint_x=0.75,
        )
        self._duration_value_label = Label(
            text=f"{self._duration_minutes} min",
            font_size=dp(16),
            bold=True,
            size_hint_x=0.25,
        )
        self._duration_slider.bind(value=self._on_duration_change)
        slider_row.add_widget(self._duration_slider)
        slider_row.add_widget(self._duration_value_label)
        root.add_widget(slider_row)

        # Preset buttons
        preset_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        for minutes in [5, 10, 15, 20, 30, 45, 60]:
            btn = Button(
                text=f"{minutes}",
                font_size=dp(13),
                background_color=(0.25, 0.35, 0.5, 1.0),
            )
            btn.bind(on_release=lambda x, m=minutes: self._set_duration(m))
            preset_row.add_widget(btn)
        root.add_widget(preset_row)

        # Big countdown display
        self._countdown_label = Label(
            text="--:--",
            font_size=dp(64),
            bold=True,
            size_hint_y=0.4,
            color=(0.3, 0.8, 1.0, 1.0),
        )
        root.add_widget(self._countdown_label)

        # Status label
        self._status_label = Label(
            text="Timer disabled" if not self._enabled else "Ready",
            font_size=dp(14),
            size_hint_y=None,
            height=dp(30),
            color=(0.6, 0.6, 0.6, 1.0),
        )
        root.add_widget(self._status_label)

        self.add_widget(root)
        self._update_display()

    def _on_enable_toggle(self, checkbox, active) -> None:
        self._enabled = active
        if active:
            self._status_label.text = "Ready"
            self._status_label.color = (0.3, 0.8, 0.5, 1.0)
        else:
            self._status_label.text = "Timer disabled"
            self._status_label.color = (0.6, 0.6, 0.6, 1.0)
            self._countdown_label.text = "--:--"

    def _on_duration_change(self, instance, value) -> None:
        self._duration_minutes = int(value)
        self._duration_value_label.text = f"{self._duration_minutes} min"
        self._update_display()

    def _set_duration(self, minutes: int) -> None:
        self._duration_minutes = minutes
        self._duration_slider.value = minutes
        self._duration_value_label.text = f"{minutes} min"
        self._update_display()

    def _update_display(self) -> None:
        if not self._enabled:
            self._countdown_label.text = "--:--"
            return
        mins = self._duration_minutes
        self._countdown_label.text = f"{mins:02d}:00"

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def duration_seconds(self) -> float:
        return self._duration_minutes * 60.0

    def start_countdown(self) -> None:
        """Called when a session starts. Initializes remaining time."""
        if not self._enabled:
            return
        self._remaining_seconds = self._duration_minutes * 60.0
        self._status_label.text = "Running"
        self._status_label.color = (0.3, 0.8, 1.0, 1.0)

    def tick(self, dt: float) -> bool:
        """Called each update tick. Returns True if timer has expired."""
        if not self._enabled:
            return False
        self._remaining_seconds -= dt
        if self._remaining_seconds <= 0:
            self._remaining_seconds = 0.0
            self._countdown_label.text = "00:00"
            self._countdown_label.color = (1.0, 0.3, 0.3, 1.0)
            self._status_label.text = "Time's up!"
            self._status_label.color = (1.0, 0.5, 0.2, 1.0)
            return True
        mins = int(self._remaining_seconds) // 60
        secs = int(self._remaining_seconds) % 60
        self._countdown_label.text = f"{mins:02d}:{secs:02d}"
        self._countdown_label.color = (0.3, 0.8, 1.0, 1.0)
        return False

    def reset(self) -> None:
        """Reset timer to initial state."""
        self._remaining_seconds = 0.0
        self._countdown_label.color = (0.3, 0.8, 1.0, 1.0)
        if self._enabled:
            self._status_label.text = "Ready"
            self._status_label.color = (0.3, 0.8, 0.5, 1.0)
        else:
            self._status_label.text = "Timer disabled"
            self._status_label.color = (0.6, 0.6, 0.6, 1.0)
        self._update_display()

    def set_timer_finished_callback(self, callback: Callable) -> None:
        self._on_timer_finished = callback
