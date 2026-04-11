from collections.abc import Callable
from typing import Optional

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput


class ProfileScreen(Screen):
    """User profile management screen with user creation and switching."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = "profile"
        self._on_user_switch: Optional[Callable] = None
        self._on_user_create: Optional[Callable] = None
        self._on_user_delete: Optional[Callable] = None
        self._selected_user_id: Optional[int] = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))

        title = Label(
            text="User Profiles",
            font_size=dp(20),
            bold=True,
            size_hint_y=None,
            height=dp(36),
        )
        root.add_widget(title)

        # --- Current user indicator ---
        self._current_user_label = Label(
            text="Current: All Users",
            font_size=dp(14),
            color=(0.3, 0.8, 1.0, 1.0),
            size_hint_y=None,
            height=dp(28),
            bold=True,
        )
        root.add_widget(self._current_user_label)

        # --- Create user row ---
        create_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self._name_input = TextInput(
            hint_text="Enter user name...",
            multiline=False,
            font_size=dp(14),
            size_hint_x=0.6,
        )
        self._create_btn = Button(
            text="Create User",
            background_color=(0.2, 0.7, 0.3, 1.0),
            font_size=dp(14),
            bold=True,
            size_hint_x=0.4,
        )
        self._create_btn.bind(on_release=self._on_create_pressed)
        create_row.add_widget(self._name_input)
        create_row.add_widget(self._create_btn)
        root.add_widget(create_row)

        self._status_label = Label(
            text="",
            font_size=dp(11),
            color=(0.8, 0.4, 0.4, 1.0),
            size_hint_y=None,
            height=dp(20),
        )
        root.add_widget(self._status_label)

        # --- "All Users" button ---
        all_btn = Button(
            text="Show All Users (no filter)",
            size_hint_y=None,
            height=dp(36),
            font_size=dp(13),
            background_color=(0.3, 0.3, 0.5, 1.0),
            bold=True,
        )
        all_btn.bind(on_release=self._on_all_users)
        root.add_widget(all_btn)

        # --- User list ---
        list_label = Label(
            text="Select user to switch:",
            font_size=dp(13),
            size_hint_y=None,
            height=dp(24),
            color=(0.6, 0.6, 0.6, 1.0),
        )
        root.add_widget(list_label)

        self._user_list_layout = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(4),
        )
        self._user_list_layout.bind(
            minimum_height=self._user_list_layout.setter("height")
        )
        user_scroll = ScrollView()
        user_scroll.add_widget(self._user_list_layout)
        root.add_widget(user_scroll)

        self.add_widget(root)

    def set_user_switch_callback(self, callback: Callable) -> None:
        self._on_user_switch = callback

    def set_user_create_callback(self, callback: Callable) -> None:
        self._on_user_create = callback

    def set_user_delete_callback(self, callback: Callable) -> None:
        self._on_user_delete = callback

    def populate_users(self, users: list[dict], current_user_id: Optional[int]) -> None:
        """Fill the user list."""
        self._user_list_layout.clear_widgets()
        self._selected_user_id = current_user_id

        if current_user_id is None:
            self._current_user_label.text = "Current: All Users"
        else:
            for u in users:
                if u["id"] == current_user_id:
                    self._current_user_label.text = f"Current: {u['name']}"
                    break

        if not users:
            lbl = Label(
                text="No users yet. Create one above.",
                font_size=dp(13),
                color=(0.5, 0.5, 0.5, 1.0),
                size_hint_y=None,
                height=dp(40),
            )
            self._user_list_layout.add_widget(lbl)
            return

        for u in users:
            row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(4))
            is_active = u["id"] == current_user_id
            bg = (0.2, 0.5, 0.3, 1.0) if is_active else (0.15, 0.15, 0.2, 1.0)
            btn = Button(
                text=f"{u['name']}  {'(active)' if is_active else ''}",
                font_size=dp(13),
                background_color=bg,
                size_hint_x=0.75,
            )
            btn.user_id = u["id"]
            btn.bind(on_release=self._on_user_btn)

            del_btn = Button(
                text="X",
                font_size=dp(13),
                background_color=(0.7, 0.2, 0.2, 1.0),
                size_hint_x=0.25,
            )
            del_btn.user_id = u["id"]
            del_btn.bind(on_release=self._on_delete_btn)

            row.add_widget(btn)
            row.add_widget(del_btn)
            self._user_list_layout.add_widget(row)

    def _on_create_pressed(self, *args) -> None:
        name = self._name_input.text.strip()
        if not name:
            self._status_label.text = "Please enter a name"
            return
        if self._on_user_create:
            self._on_user_create(name)
        self._name_input.text = ""
        self._status_label.text = ""

    def _on_user_btn(self, btn) -> None:
        uid = getattr(btn, "user_id", None)
        if uid is not None and self._on_user_switch:
            self._on_user_switch(uid)

    def _on_all_users(self, *args) -> None:
        if self._on_user_switch:
            self._on_user_switch(None)

    def _on_delete_btn(self, btn) -> None:
        uid = getattr(btn, "user_id", None)
        if uid is not None and self._on_user_delete:
            self._on_user_delete(uid)
