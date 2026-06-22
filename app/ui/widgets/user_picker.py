"""Shared user-picker form: existing-profiles panel + name input + duplicate-error UI."""

from collections.abc import Callable
from typing import Optional

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from app.logger import logger
from app.ui.theme import C, F, S, StyledButton


class UserPickerForm(BoxLayout):
    """Pick an existing user or create a new one. Used in wizard, first-run popup, and Settings."""

    def __init__(
        self,
        on_create: Callable[[str], None],
        on_pick_existing: Callable[[int], None],
        on_count: Optional[Callable[[int], int]] = None,
        on_delete: Optional[Callable[[int], None]] = None,
        **kwargs,
    ) -> None:
        # size_hint_y=None + minimum_height is required so the form sizes
        # correctly inside an accordion section's ScrollView (which sets
        # _scroll.height from _content.minimum_height). Without this the
        # section snapshots a height that excludes the existing-profiles
        # list and the form gets clipped.
        super().__init__(
            orientation="vertical",
            spacing=S.GAP_SM,
            size_hint_y=None,
            **kwargs,
        )
        self.bind(minimum_height=self.setter("height"))
        self._on_create = on_create
        self._on_pick_existing = on_pick_existing
        self._on_count = on_count
        self._on_delete = on_delete
        self._users: list[dict] = []
        self._duplicate_user_id: Optional[int] = None
        self._build_ui()

    def _build_ui(self) -> None:
        # --- (1) Existing users panel ---
        # Height is set explicitly in populate_users so the empty-state
        # collapse to 0 sticks (a minimum_height bind would auto-restore
        # it to the header's height = ~22dp).
        self._existing_panel = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=0,
            spacing=dp(2),
            opacity=0,
            disabled=True,
        )

        self._existing_header = Label(
            text="Existing profiles (0)",
            font_size=F.SMALL,
            color=C.TEXT_SECONDARY,
            size_hint_y=None,
            height=dp(22),
            halign="left",
            valign="middle",
        )
        self._existing_header.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        self._existing_panel.add_widget(self._existing_header)

        self._existing_scroll = ScrollView(size_hint_y=None, height=dp(0))
        self._existing_list = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(2),
        )
        self._existing_list.bind(minimum_height=self._existing_list.setter("height"))
        self._existing_scroll.add_widget(self._existing_list)
        self._existing_panel.add_widget(self._existing_scroll)
        self.add_widget(self._existing_panel)

        # --- (2) Name input + Create ---
        input_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=S.GAP_SM)
        self._name_input = TextInput(
            hint_text="New profile name…",
            multiline=False,
            font_size=F.BODY,
            foreground_color=C.TEXT,
            background_color=list(C.BG_INPUT),
            cursor_color=C.PRIMARY,
            size_hint_x=0.65,
        )
        self._create_btn = StyledButton(
            text="Create",
            bg_color=C.ACCENT,
            bg_pressed=C.ACCENT_DIM,
            font_size=F.BODY,
            size_hint_x=0.35,
        )
        # Don't bind Create on_release — ButtonBehavior's on_release fires
        # via Kivy's deferred ScrollView dispatch chain, which on this
        # platform sometimes drops the event entirely (same root cause as
        # the input focus issue). We route the click through our own
        # on_touch_up override below, which is reliable.
        self._name_input.bind(on_text_validate=lambda *a: self._on_create_pressed())
        self._name_input.bind(focus=self._on_input_focus_change)
        self._name_input.bind(text=self._on_input_text_change)
        # Defensive: explicitly enable so any stray `disabled=True` from
        # parent state changes (the existing-panel toggling, etc.) can't
        # leave the input in a non-interactive state.
        self._name_input.disabled = False
        self._create_btn.disabled = False
        input_row.disabled = False
        input_row.add_widget(self._name_input)
        input_row.add_widget(self._create_btn)
        self.add_widget(input_row)

        # --- (3) Inline duplicate-error region ---
        self._error_row = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=0,
            spacing=dp(4),
            opacity=0,
            disabled=True,
        )
        self._error_label = Label(
            text="",
            font_size=F.SMALL,
            color=C.DANGER,
            size_hint_y=None,
            height=dp(22),
            halign="left",
            valign="middle",
        )
        self._error_label.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        self._error_row.add_widget(self._error_label)

        btn_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=S.GAP_SM)
        self._btn_use_existing = StyledButton(
            text="Use existing",
            bg_color=C.PRIMARY,
            font_size=F.SMALL,
        )
        self._btn_change_name = StyledButton(
            text="Change name",
            bg_color=C.BG_CARD,
            text_color=C.TEXT_SECONDARY,
            font_size=F.SMALL,
            bold=False,
        )
        self._btn_use_existing.bind(on_release=lambda *a: self._on_use_existing_pressed())
        self._btn_change_name.bind(on_release=lambda *a: self._on_change_name_pressed())
        btn_row.add_widget(self._btn_use_existing)
        btn_row.add_widget(self._btn_change_name)
        self._error_row.add_widget(btn_row)
        self.add_widget(self._error_row)

    def _on_input_focus_change(self, instance, focused):
        logger.debug(f"[user_picker] _name_input focus={focused}")

    def _on_input_text_change(self, instance, text):
        """Filter the existing-profiles dropdown as the user types."""
        self._render_filtered_list(text)

    # ---- Population ----

    def populate_users(self, users: list[dict]) -> None:
        """Set the full user list. The visible dropdown is then derived
        from this list and the current input text."""
        self._users = users
        self._render_filtered_list(self._name_input.text)

    def _render_filtered_list(self, query: str) -> None:
        """Re-render the existing-profiles dropdown with users whose name
        contains `query` (case-insensitive). Empty query shows all."""
        self._existing_list.clear_widgets()
        q = query.strip().lower()
        if q:
            filtered = [u for u in self._users if q in u["name"].lower()]
        else:
            filtered = list(self._users)

        n = len(filtered)
        if n == 0:
            self._existing_panel.opacity = 0
            self._existing_panel.disabled = True
            self._existing_panel.height = 0
            return

        self._existing_panel.opacity = 1
        self._existing_panel.disabled = False
        if q:
            self._existing_header.text = f"Matches ({n})"
        else:
            self._existing_header.text = f"Existing profiles ({n})"

        max_visible = 5
        row_h = dp(40)
        scroll_h = min(n, max_visible) * (row_h + dp(2))
        self._existing_scroll.height = scroll_h
        self._existing_panel.height = dp(22) + scroll_h + dp(4)

        for u in filtered:
            row = self._make_user_row(u, row_h)
            self._existing_list.add_widget(row)

    def _make_user_row(self, user: dict, height: float) -> BoxLayout:
        uid = user["id"]
        name = user["name"]
        count = self._on_count(uid) if self._on_count else None
        label_text = f"{name} ({count} sessions)" if count is not None else name

        row = BoxLayout(size_hint_y=None, height=height, spacing=dp(4))
        btn = StyledButton(
            text=label_text,
            bg_color=C.BG_CARD,
            text_color=C.TEXT,
            font_size=F.BODY,
            bold=False,
        )
        btn.bind(on_release=lambda *a, _uid=uid: self._on_existing_row_tap(_uid))
        row.add_widget(btn)

        if self._on_delete is not None:
            del_btn = StyledButton(
                text="X",
                bg_color=C.DANGER,
                text_color=C.DANGER,
                font_size=F.SMALL,
                size_hint_x=None,
                width=dp(36),
                bold=False,
                outline=True,
            )
            del_cb = self._on_delete
            del_btn.bind(on_release=lambda *a, _uid=uid: del_cb(_uid))
            row.add_widget(del_btn)

        return row

    # ---- User actions ----

    def on_touch_up(self, touch):
        # Touch-up router for input focus + Create button.
        # Touch-down propagation through nested ScrollView + accordion
        # races with Kivy's FocusBehavior and ButtonBehavior chains: the
        # input briefly gets focus before losing it, and the Create
        # button's on_release sometimes never fires. We claim both events
        # explicitly here on touch-up (after dispatch settles), via a
        # Clock.schedule_once so the action runs on the next idle tick.
        handled = super().on_touch_up(touch)
        pos = touch.pos
        if (not self._name_input.disabled
                and self._name_input.collide_point(*pos)):
            Clock.schedule_once(
                lambda dt: setattr(self._name_input, "focus", True), 0,
            )
        elif (not self._create_btn.disabled
                and self._create_btn.collide_point(*pos)):
            Clock.schedule_once(lambda dt: self._on_create_pressed(), 0)
        return handled

    def _on_create_pressed(self) -> None:
        name = self._name_input.text.strip()
        if len(name) < 2:
            self._error_label.color = C.DANGER
            self._error_label.text = "Name must be at least 2 characters"
            self._error_row.opacity = 1
            self._error_row.disabled = False
            self._error_row.height = dp(22)
            return
        # Hide buttons (this isn't the duplicate case)
        self._error_row.opacity = 0
        self._error_row.disabled = True
        self._error_row.height = 0
        self._on_create(name)

    def _on_existing_row_tap(self, user_id: int) -> None:
        self._on_pick_existing(user_id)

    def _on_use_existing_pressed(self) -> None:
        if self._duplicate_user_id is None:
            return
        uid = self._duplicate_user_id
        # Hide the inline error region — user is picking the existing
        # profile, the duplicate prompt no longer applies.
        self._error_row.opacity = 0
        self._error_row.disabled = True
        self._error_row.height = 0
        self._duplicate_user_id = None
        self._on_pick_existing(uid)

    def _on_change_name_pressed(self) -> None:
        self._error_row.opacity = 0
        self._error_row.disabled = True
        self._error_row.height = 0
        self._duplicate_user_id = None
        self._name_input.focus = True

    # ---- Externally driven ----

    def show_duplicate_error(self, user_id: int, name: str) -> None:
        self._duplicate_user_id = user_id
        self._error_label.text = f"User '{name}' already exists"
        self._btn_use_existing.text = f"Use existing '{name}'"
        self._error_row.opacity = 1
        self._error_row.disabled = False
        self._error_row.height = dp(22) + dp(38) + dp(4)

    def clear(self) -> None:
        self._name_input.text = ""
        self._error_label.text = ""
        self._error_row.opacity = 0
        self._error_row.disabled = True
        self._error_row.height = 0
        self._duplicate_user_id = None
