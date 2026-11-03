"""Profiles: the gate that keeps the app unusable without an active profile, and Settings → Profile's list, switch,
create and delete. The active profile is the app's (`_current_user_id`); every pick goes through its `_activate_user`."""
import sqlite3
from collections.abc import Callable

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app.crash_handler import report_soft_error
from app.logger import logger
from app.storage.database import UserExistsError
from app.ui.app_context import AppContext
from app.ui.theme import C, F, ThemedLabel, ThemedPopup
from app.ui.widgets.user_picker import UserPickerForm


class ProfileGate:
    """The blocking profile picker, open while there is no active profile: at first run, after the active profile's
    delete, or when the process resumes with none."""

    def __init__(self, ctx: AppContext, bottom_nav, *, refresh_profiles: Callable[[], None],
                 scan_for_new_profile: Callable[[], None], offer_power_exemption: Callable[[], None]) -> None:
        self._ctx = ctx
        self._bottom_nav = bottom_nav
        self._refresh_profiles = refresh_profiles
        self._scan_for_new_profile = scan_for_new_profile
        self._offer_power_exemption = offer_power_exemption
        self._gate_popup = None  # the open gate popup
        self._gate_event = None  # its open, scheduled

    def open(self, delay: float = 0.0) -> None:
        """Enter the hard user gate: disable the bottom nav and open the blocking
        selection modal. Single source for build() / on_resume / self-delete so
        the 'app unusable without a user' enforcement can't drift between them."""
        # Disable nav BEFORE any dedupe return — the gate state must be enforced
        # even when a popup is already open/scheduled.
        self._bottom_nav.disabled = True
        if self._gate_popup is not None:
            return  # a gate popup is already open — don't stack another
        if self._gate_event is not None:
            return  # one is already scheduled (pre-popup window) — don't stack
        self._gate_event = Clock.schedule_once(self._show, delay)

    def active(self) -> bool:
        """True while the app is gated on user selection — nav disabled, no concrete
        user. Covers both the popup-open state and the schedule window before the
        popup exists, so the gate is un-escapable throughout."""
        return bool(self._bottom_nav.disabled and not self._ctx.user_id())

    def shown(self) -> bool:
        return self._gate_popup is not None

    def _reopen_if_unresolved(self) -> None:
        """After a gate create/pick attempt, re-open the gate if no concrete user
        ended up set (invalid name, or a stale/deleted profile row) — otherwise the
        popup is gone, nav stays disabled, and the app is stranded with no user."""
        if not self._ctx.user_id():
            self._refresh_profiles()  # drop any stale row from the picker list
            self.open(0)

    def _show(self, dt) -> None:
        """Show a name-entry popup on first run (no users in DB).

        After uninstall→reinstall on Android, the DB may persist with
        existing profiles — UserPickerForm surfaces them so the user can
        adopt instead of creating a duplicate name.
        """
        self._gate_event = None  # the scheduled open is now firing
        if self._gate_popup is not None:
            return  # a gate popup is already open — never stack a second modal

        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))

        welcome = ThemedLabel(
            text="Welcome! Create a profile or pick an existing one:",
            font_size=F.BODY, color=C.TEXT,
            size_hint_y=None, height=dp(48),
            halign="center",
        )
        welcome.bind(size=welcome.setter("text_size"))
        content.add_widget(welcome)

        popup = ThemedPopup(
            title="Select Profile",
            content=content,
            size_hint=(0.9, None),
            auto_dismiss=False,
        )
        # Tracked so _on_keyboard can make the gate un-escapable (back/Esc must
        # not dismiss it or exit the app out from under an unresolved user).
        self._gate_popup = popup
        # A dismissal from ANY path clears the handle, so a stale non-None
        # _gate_popup can never block re-gating forever.
        popup.bind(on_dismiss=lambda *_a: setattr(self, "_gate_popup", None))

        def _on_create(name: str) -> None:
            self._gate_popup = None
            popup.dismiss()
            self.complete_first_run(name)
            self._reopen_if_unresolved()

        def _on_pick(user_id: int) -> None:
            self._gate_popup = None
            popup.dismiss()
            self.pick_existing(user_id)
            self._reopen_if_unresolved()

        form = UserPickerForm(
            on_create=_on_create,
            on_pick_existing=_on_pick,
        )
        existing_users = self._ctx.db.get_all_users()
        form.populate_users(existing_users)
        content.add_widget(form)
        popup.open()

    def complete_first_run(self, user_name: str) -> None:
        """First-run popup: a typed name creates that profile, in mock mode until a headset is picked; a name that
        exists picks that profile instead."""
        if not user_name or len(user_name.strip()) < 2:
            logger.warning(f"First run with invalid name: '{user_name}', ignoring")
            return
        try:
            uid = self._ctx.db.create_user(user_name)
        except UserExistsError as e:
            logger.info(f"First run: '{e.name}' exists, picking it (id={e.user_id})")
            self.pick_existing(e.user_id)
            return
        except sqlite3.Error as e:  # the popup's caller reopens the gate: no profile was made
            report_soft_error("user_create_failed", f"The profile '{user_name}' could not be created: {e}")
            return
        self._ctx.db.set_user_setting(uid, "use_mock", "True")  # before its load, which applies it
        self._ctx.activate_user(uid)
        self._scan_for_new_profile()
        logger.info("First run: using mock device until a MindWave is found")
        self._finish_first_run(f"user '{user_name}' created")

    def pick_existing(self, user_id: int) -> None:
        """First-run popup: an existing profile picked, activated as it is (its own headset and mode)."""
        if not self._ctx.db.get_user(user_id):
            logger.warning(f"pick_existing: user {user_id} not found")
            return
        self._ctx.activate_user(user_id)
        self._finish_first_run(f"user {user_id} picked")

    def _finish_first_run(self, what: str) -> None:
        """Leave the first-run popup for the Session screen, the nav usable again."""
        self._bottom_nav.opacity = 1
        self._bottom_nav.disabled = False
        self._refresh_profiles()
        self._ctx.switch_screen("live_session")  # its tab marked too
        self._offer_power_exemption()
        logger.info(f"First run complete: {what}")


class Profiles:
    """Settings → Profile: the profile list, a switch, a create, a delete. A session's part in a switch or a delete is
    the app's, through the callables given; a delete that leaves no active profile opens the gate."""

    def __init__(self, ctx: AppContext, settings_screen, gate: ProfileGate, *, deactivate: Callable[[], None],
                 on_deleted: Callable[[int], None]) -> None:
        self._ctx = ctx
        self._settings_screen = settings_screen
        self._gate = gate
        self._deactivate = deactivate
        self._on_deleted = on_deleted

    def refresh(self) -> None:
        self._settings_screen.populate_users(self._ctx.db.get_all_users(), self._ctx.user_id())

    def on_switch(self, user_id: int) -> None:
        """Switch the active user profile."""
        # The running session owns the loaded settings and saves under its own profile.
        if user_id != self._ctx.user_id() and self._ctx.session.refused("switching profiles"):
            self.refresh()  # snap the picker back to the active profile
            return
        # Save current user's settings before switching
        self._ctx.save_settings()
        user = self._ctx.db.get_user(user_id)
        name = user["name"] if user else "Unknown"
        self._ctx.activate_user(user_id)
        logger.info(f"Switched to user: {name} (id={user_id})")
        self.refresh()

    def on_create(self, name: str) -> None:
        """Create a new user and refresh the profile list.

        Routes UserExistsError to the active picker form (Settings) for
        inline duplicate handling.
        """

        try:
            self._ctx.db.create_user(name)
        except UserExistsError as e:
            form = getattr(self._settings_screen, "_user_picker_form", None)
            if form is not None:
                form.show_duplicate_error(user_id=e.user_id, name=e.name)
            return
        except Exception as e:  # noqa: BLE001 - any failure is reported and creates nothing
            report_soft_error(
                "user_create_failed", f"Could not create user '{name}': {e}",
            )
            return
        self.refresh()

    def on_delete(self, user_id: int) -> None:
        """Delete a user profile. Deleting the ACTIVE profile drops the app into
        the no-user state, so re-enter the hard gate instead of leaving the app
        usable with nothing selected."""
        deleted_active = self._ctx.user_id() == user_id
        if deleted_active and self._ctx.session.live():
            # Discard the running (or connecting) session — otherwise the tick
            # thread keeps running and writes an orphaned session, and saving it
            # under a profile that's about to be deleted just orphans it anyway.
            self._ctx.session.discard()
        self._ctx.db.delete_user(user_id)
        self._on_deleted(user_id)
        remaining = self._ctx.db.get_all_users()
        # Re-enter the gate when no usable active user is left: the active profile was deleted, or no profile is left
        # at all (the app is never usable with zero users).
        if deleted_active or not remaining:
            self._deactivate()
            self.refresh()
            self._gate.open(0)
        else:
            self.refresh()

    def count_sessions(self, user_id: int) -> int | None:
        """The sessions History lists for the profile, or None (a row without its count) when the read fails."""
        try:
            return self._ctx.db.count_sessions(user_id, self._ctx.session.running_id())
        except sqlite3.Error:
            logger.exception(f"Profile {user_id}'s sessions couldn't be counted")
            return None

    def current_name(self) -> str | None:
        uid = self._ctx.user_id()
        user = self._ctx.db.get_user(uid) if uid else None
        return user["name"] if user else None
