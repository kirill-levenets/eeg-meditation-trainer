"""First-run wizard: create profile + select device in 2 steps."""

import sys
from collections.abc import Callable
from typing import Optional

from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen

from app.ui.theme import (
    ICONS_AVAILABLE,
    C,
    CenteredTextInput,
    F,
    Icons,
    S,
    StyledButton,
)
from app.ui.widgets.user_picker import UserPickerForm

_IS_ANDROID = hasattr(sys, "getandroidapilevel")


class WizardScreen(Screen):
    """Two-step first-run wizard: profile name → device selection."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "wizard"
        self._on_complete: Optional[Callable] = None
        self._on_scan: Optional[Callable] = None
        self._on_pick_existing: Optional[Callable] = None
        self._user_name: str = ""
        self._step = 1
        self._build_ui()

    def _build_ui(self) -> None:
        root = BoxLayout(orientation="vertical", padding=dp(24), spacing=S.GAP_LG)
        with root.canvas.before:
            Color(*C.BG)
            self._bg = Rectangle(size=root.size, pos=root.pos)
        root.bind(
            size=lambda w, v: setattr(self._bg, "size", v),
            pos=lambda w, v: setattr(self._bg, "pos", v),
        )

        root.add_widget(BoxLayout(size_hint_y=0.15))  # top spacer

        # Welcome header
        self._title = Label(
            text="Welcome",
            font_size=dp(28),
            bold=True,
            color=C.PRIMARY,
            size_hint_y=None,
            height=dp(40),
        )
        root.add_widget(self._title)

        self._subtitle = Label(
            text="Let's set up your meditation trainer",
            font_size=F.BODY,
            color=C.TEXT_SECONDARY,
            size_hint_y=None,
            height=dp(24),
        )
        root.add_widget(self._subtitle)

        root.add_widget(BoxLayout(size_hint_y=0.05))

        # Step indicator
        self._step_label = Label(
            text="Step 1 of 2",
            font_size=F.SMALL,
            color=C.TEXT_MUTED,
            size_hint_y=None,
            height=dp(20),
        )
        root.add_widget(self._step_label)

        # --- Step 1: Name input via shared UserPickerForm ---
        self._step1 = BoxLayout(orientation="vertical", spacing=S.GAP)

        name_label = Label(
            text="What's your name?",
            font_size=F.H2,
            color=C.TEXT,
            size_hint_y=None,
            height=dp(30),
            halign="left",
        )
        name_label.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        self._step1.add_widget(name_label)

        self._user_form = UserPickerForm(
            on_create=self._on_form_create,
            on_pick_existing=self._on_form_pick_existing,
        )
        self._step1.add_widget(self._user_form)

        # Android: inline TextInput inside a Screen often loses keyboard
        # focus. Re-route the form's TextInput to a Popup TextInput on
        # Android, then write the result back into the form.
        if _IS_ANDROID:
            self._user_form._name_input.bind(focus=self._open_name_popup_if_focused)

        name_hint = Label(
            text="This creates your profile to track sessions and settings",
            font_size=F.SMALL,
            color=C.TEXT_MUTED,
            size_hint_y=None,
            height=dp(20),
            halign="left",
        )
        name_hint.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        self._step1.add_widget(name_hint)

        root.add_widget(self._step1)

        # --- Step 2: Device selection ---
        self._step2 = BoxLayout(orientation="vertical", spacing=S.GAP)

        device_label = Label(
            text="Connect your EEG device",
            font_size=F.H2,
            color=C.TEXT,
            size_hint_y=None,
            height=dp(30),
            halign="left",
        )
        device_label.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        self._step2.add_widget(device_label)

        device_hint = Label(
            text="Make sure your MindWave is paired in\nsystem Bluetooth settings first",
            font_size=F.SMALL,
            color=C.TEXT_MUTED,
            size_hint_y=None,
            height=dp(34),
            halign="left",
        )
        device_hint.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        self._step2.add_widget(device_hint)

        self._scan_btn = StyledButton(
            text="Scan for Devices",
            icon=Icons.BLUETOOTH if ICONS_AVAILABLE else "",
            bg_color=C.PRIMARY, bg_pressed=C.PRIMARY_DIM,
        )
        self._scan_btn.bind(on_release=self._on_scan_pressed)
        self._step2.add_widget(self._scan_btn)

        self._device_list = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=S.GAP_SM,
        )
        self._device_list.bind(minimum_height=self._device_list.setter("height"))
        self._step2.add_widget(self._device_list)

        self._scan_status = Label(
            text="",
            font_size=F.SMALL,
            color=C.TEXT_SECONDARY,
            size_hint_y=None,
            height=dp(20),
        )
        self._step2.add_widget(self._scan_status)

        skip_btn = StyledButton(
            text="Skip (use demo mode)",
            bg_color=C.BG_CARD, text_color=C.TEXT_MUTED,
            font_size=F.BODY,
            bold=False,
        )
        skip_btn.bind(on_release=self._on_skip)
        self._step2.add_widget(skip_btn)

        # Hidden and disabled initially
        self._step2.opacity = 0
        self._step2.disabled = True
        self._step2.size_hint_y = 0
        self._step2.height = 0
        root.add_widget(self._step2)

        root.add_widget(BoxLayout(size_hint_y=0.2))  # bottom spacer

        self.add_widget(root)

    def set_complete_callback(self, cb: Callable) -> None:
        """Called with (user_name, device_address, device_name) or (user_name, None, None)."""
        self._on_complete = cb

    def set_scan_callback(self, cb: Callable) -> None:
        """Called to trigger BT scan. Should call populate_devices() with results."""
        self._on_scan = cb

    def set_pick_existing_callback(self, cb: Callable) -> None:
        """Called with the existing user_id when picked from the form."""
        self._on_pick_existing = cb

    def populate_existing_users(self, users: list[dict]) -> None:
        """Refresh the form's existing-profiles panel."""
        if self._user_form is not None:
            self._user_form.populate_users(users)

    def _on_form_create(self, name: str) -> None:
        """User typed a new name and pressed Create — advance to step 2."""
        self._user_name = name
        self._advance_to_step2()

    def _on_form_pick_existing(self, user_id: int) -> None:
        if self._on_pick_existing:
            self._on_pick_existing(user_id)

    def _advance_to_step2(self) -> None:
        self._step = 2
        self._step_label.text = "Step 2 of 2"
        self._title.text = f"Hi, {self._user_name}!"
        self._subtitle.text = "Now let's connect your device"

        self._step1.opacity = 0
        self._step1.size_hint_y = 0
        self._step1.height = 0

        self._step2.opacity = 1
        self._step2.disabled = False
        self._step2.size_hint_y = 1

    def _open_name_popup_if_focused(self, instance, focused: bool) -> None:
        """Android-only: hijack focus on the form's TextInput → open Popup TextInput."""
        if not focused:
            return
        instance.focus = False
        self._open_name_popup_for_form(instance)

    def _open_name_popup_for_form(self, target_input) -> None:
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        text_input = CenteredTextInput(
            hint_text="Enter your name...",
            text=target_input.text,
            multiline=False,
            font_size=F.H2,
            size_hint_y=None, height=dp(48),
            foreground_color=C.TEXT,
            background_color=list(C.BG_INPUT),
            cursor_color=C.PRIMARY,
        )
        content.add_widget(text_input)
        btn_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        ok_btn = StyledButton(text="OK", bg_color=C.ACCENT, bg_pressed=C.ACCENT_DIM)
        cancel_btn = StyledButton(
            text="Cancel", bg_color=C.BG_CARD, text_color=C.TEXT_MUTED,
        )
        btn_row.add_widget(ok_btn)
        btn_row.add_widget(cancel_btn)
        content.add_widget(btn_row)
        popup = Popup(
            title="Your name",
            content=content,
            size_hint=(0.85, 0.35),
            auto_dismiss=False,
        )

        def _on_ok(*_a):
            target_input.text = text_input.text.strip()
            popup.dismiss()

        def _on_cancel(*_a):
            popup.dismiss()

        ok_btn.bind(on_release=_on_ok)
        cancel_btn.bind(on_release=_on_cancel)
        text_input.bind(on_text_validate=_on_ok)
        popup.open()

    def _on_scan_pressed(self, *args) -> None:
        self._scan_status.text = "Scanning..."
        self._device_list.clear_widgets()
        if self._on_scan:
            self._on_scan()

    def populate_devices(self, devices: list[dict[str, str]]) -> None:
        """Show scan results."""
        self._device_list.clear_widgets()
        if not devices:
            self._scan_status.text = "No paired devices found"
            return

        self._scan_status.text = f"Found {len(devices)} device(s)"
        for dev in devices:
            name = dev.get("name", "Unknown")
            addr = dev.get("address", "")
            btn = StyledButton(
                text=name,
                bg_color=C.BG_CARD,
                text_color=C.TEXT,
                font_size=F.BODY,
                height=dp(40),
                bold=False,
            )
            btn._dev_addr = addr
            btn._dev_name = name
            btn.bind(on_release=self._on_device_pick)
            self._device_list.add_widget(btn)

    def _on_device_pick(self, btn) -> None:
        if self._on_complete and self._user_name:
            self._on_complete(self._user_name, btn._dev_addr, btn._dev_name)

    def _on_skip(self, *args) -> None:
        if self._on_complete and self._user_name:
            self._on_complete(self._user_name, None, None)
