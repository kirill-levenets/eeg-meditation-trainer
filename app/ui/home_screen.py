from collections.abc import Callable
from typing import Optional

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput


class HomeScreen(Screen):
    """Main home screen with user selection and navigation."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "home"
        self._on_user_switch: Optional[Callable] = None
        self._on_user_create: Optional[Callable] = None
        self._on_navigate: Optional[Callable] = None
        self._users: list[dict] = []
        self._user_map: dict[str, int] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = BoxLayout(orientation="vertical", padding=dp(24), spacing=dp(16))

        title = Label(
            text="EEG Meditation Trainer",
            font_size=dp(24),
            bold=True,
            size_hint_y=None,
            height=dp(48),
            color=(0.3, 0.8, 1.0, 1.0),
        )
        root.add_widget(title)

        # User selection section
        user_section = BoxLayout(
            orientation="vertical", size_hint_y=None, height=dp(130), spacing=dp(8)
        )

        user_label = Label(
            text="Select User",
            font_size=dp(16),
            size_hint_y=None,
            height=dp(28),
            color=(0.7, 0.7, 0.7, 1.0),
        )
        user_section.add_widget(user_label)

        self._user_spinner = Spinner(
            text="-- Select User --",
            values=[],
            size_hint_y=None,
            height=dp(44),
            font_size=dp(16),
            background_color=(0.2, 0.2, 0.3, 1.0),
        )
        self._user_spinner.bind(text=self._on_spinner_select)
        user_section.add_widget(self._user_spinner)

        create_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        self._name_input = TextInput(
            hint_text="New user name...",
            multiline=False,
            font_size=dp(14),
            size_hint_x=0.65,
        )
        self._create_btn = Button(
            text="Create",
            background_color=(0.2, 0.7, 0.3, 1.0),
            font_size=dp(14),
            bold=True,
            size_hint_x=0.35,
        )
        self._create_btn.bind(on_release=self._on_create_pressed)
        create_row.add_widget(self._name_input)
        create_row.add_widget(self._create_btn)
        user_section.add_widget(create_row)

        root.add_widget(user_section)

        self._status_label = Label(
            text="",
            font_size=dp(12),
            color=(0.8, 0.4, 0.4, 1.0),
            size_hint_y=None,
            height=dp(24),
        )
        root.add_widget(self._status_label)

        # Navigation buttons
        nav_grid = GridLayout(cols=2, spacing=dp(12), padding=dp(8))

        self._btn_practice = Button(
            text="Practice",
            font_size=dp(20),
            bold=True,
            background_color=(0.2, 0.6, 0.3, 1.0),
            disabled=True,
        )
        self._btn_practice.bind(on_release=lambda x: self._navigate("live_session"))

        self._btn_settings = Button(
            text="Settings",
            font_size=dp(20),
            bold=True,
            background_color=(0.3, 0.4, 0.6, 1.0),
            disabled=True,
        )
        self._btn_settings.bind(on_release=lambda x: self._navigate("settings"))

        self._btn_diary = Button(
            text="Diary",
            font_size=dp(20),
            bold=True,
            background_color=(0.5, 0.3, 0.6, 1.0),
            disabled=True,
        )
        self._btn_diary.bind(on_release=lambda x: self._navigate("diary"))

        self._btn_analytics = Button(
            text="Analytics",
            font_size=dp(20),
            bold=True,
            background_color=(0.2, 0.5, 0.7, 1.0),
            disabled=True,
        )
        self._btn_analytics.bind(on_release=lambda x: self._navigate("analytics"))

        self._btn_timer = Button(
            text="Timer",
            font_size=dp(20),
            bold=True,
            background_color=(0.5, 0.5, 0.3, 1.0),
            disabled=True,
        )
        self._btn_timer.bind(on_release=lambda x: self._navigate("timer"))

        nav_grid.add_widget(self._btn_practice)
        nav_grid.add_widget(self._btn_settings)
        nav_grid.add_widget(self._btn_diary)
        nav_grid.add_widget(self._btn_analytics)
        nav_grid.add_widget(self._btn_timer)

        root.add_widget(nav_grid)
        self.add_widget(root)

    def _navigate(self, screen_name: str) -> None:
        if self._on_navigate:
            self._on_navigate(screen_name)

    def _on_spinner_select(self, spinner, text) -> None:
        if text == "-- Select User --":
            return
        user_id = self._user_map.get(text)
        if user_id is not None and self._on_user_switch:
            self._on_user_switch(user_id)

    def _on_create_pressed(self, *args) -> None:
        name = self._name_input.text.strip()
        if not name:
            self._status_label.text = "Please enter a name"
            return
        if self._on_user_create:
            self._on_user_create(name)
        self._name_input.text = ""
        self._status_label.text = ""

    def set_navigate_callback(self, callback: Callable) -> None:
        self._on_navigate = callback

    def set_user_switch_callback(self, callback: Callable) -> None:
        self._on_user_switch = callback

    def set_user_create_callback(self, callback: Callable) -> None:
        self._on_user_create = callback

    def populate_users(self, users: list[dict], current_user_id: Optional[int]) -> None:
        self._users = users
        self._user_map = {}
        names = []
        selected_text = "-- Select User --"
        for u in users:
            display = u["name"]
            self._user_map[display] = u["id"]
            names.append(display)
            if u["id"] == current_user_id:
                selected_text = display
        self._user_spinner.values = names
        self._user_spinner.text = selected_text
        self._update_buttons(current_user_id is not None)

    def _update_buttons(self, has_user: bool) -> None:
        self._btn_practice.disabled = not has_user
        self._btn_settings.disabled = not has_user
        self._btn_diary.disabled = not has_user
        self._btn_analytics.disabled = not has_user
        self._btn_timer.disabled = not has_user

    def set_status(self, text: str) -> None:
        self._status_label.text = text
