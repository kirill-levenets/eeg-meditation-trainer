"""Settings → Data Backup: back the database up to a file the user picks, or restore one and hand the app over to a
relaunch."""
import os
import sqlite3
import sys
import threading
from collections.abc import Callable
from datetime import datetime as _dt

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from app.config import APP
from app.crash_handler import report_soft_error
from app.logger import logger
from app.storage import android_saf as _saf
from app.storage import backup as _backup
from app.storage.backup import restore_backup, validate_backup
from app.storage.fileops import discard_file
from app.ui.theme import (
    C,
    CenteredTextInput,
    StyledButton,
    ThemedFileChooser,
    ThemedPopup,
    cancel_button,
    format_count,
)

BACKUP_SOUND_NOTE = "Custom sound files are not included in a backup."


def _on_android() -> bool:
    return hasattr(sys, "getandroidapilevel")


class BackupFlow:
    """Backup and Restore: the file pickers, the copy on a worker thread, the restore's confirmation and replace.
    It reaches the app only through what it is given."""

    def __init__(self, db, settings_screen, *, user_name: Callable[[], str | None], save_settings: Callable[[], None],
                 checkpoint: Callable[[], None], refused_while_session_runs: Callable[[str], bool],
                 confirm: Callable[..., None], info: Callable[[str, str], None],
                 on_db_replaced: Callable[[], None]) -> None:
        self._db = db
        self._settings_screen = settings_screen
        self._user_name = user_name
        self._save_settings = save_settings
        self._checkpoint = checkpoint
        self._refused = refused_while_session_runs
        self._confirm = confirm
        self._info = info
        self._on_db_replaced = on_db_replaced


    def on_backup_pressed(self) -> None:
        """Backup the live DB to a user-visible location."""
        # Flush first so a mid-session backup holds current settings, not the last pause snapshot.
        self._save_settings()
        filename = _backup.backup_filename(self._user_name(), _dt.now())

        if _on_android():
            self._run_backup_saf(filename)
        else:
            self._open_backup_save_picker(filename)

    def _run_backup_saf(self, filename: str) -> None:
        """Android: let the user pick the destination via the SAF save dialog.

        Scoped storage forbids direct /sdcard writes, so the bytes go through the
        content:// URI the picker returns.
        """
        def _on_uri(uri_str):
            if not uri_str:
                Clock.schedule_once(lambda dt: self._settings_screen.show_backup_status(
                    "Backup canceled"))
                return
            Clock.schedule_once(lambda dt: self._settings_screen.show_backup_status(
                "Backing up…"))
            threading.Thread(
                target=self._backup_to_uri_worker, args=(uri_str,), daemon=True,
            ).start()

        _saf.create_document(filename, _on_uri)

    def _backup_to_uri_worker(self, uri_str: str) -> None:
        tmp_path = None
        try:
            self._checkpoint()  # a running session is in the backup as of now
            tmp_path = _backup.online_backup_to_tempfile(self._db)
            if _saf.write_file_to_uri(uri_str, tmp_path):
                Clock.schedule_once(lambda dt: self._report_backup_saved(uri_str, show_location=False))
            else:
                Clock.schedule_once(lambda dt: report_soft_error(
                    "backup_failed", "Could not write backup to that location"))
        except Exception as exc:
            logger.exception("SAF backup failed")
            Clock.schedule_once(
                lambda dt, _m=str(exc): report_soft_error("backup_failed", f"Backup failed: {_m}"),
            )
        finally:
            if tmp_path:
                discard_file(tmp_path)

    def _run_backup_async(self, target_path: str) -> None:
        self._settings_screen.show_backup_status("Backing up…")

        def _worker():
            try:
                self._checkpoint()  # a running session is in the backup as of now
                _backup.make_backup(self._db, target_path)
            except (OSError, sqlite3.Error) as exc:
                err_msg = f"Backup to {target_path} failed: {exc}"
                Clock.schedule_once(
                    lambda dt, _msg=err_msg: report_soft_error("backup_failed", _msg),
                )
                return
            Clock.schedule_once(lambda dt: self._report_backup_saved(target_path))

        threading.Thread(target=_worker, daemon=True).start()

    def _report_backup_saved(self, location: str, *, show_location: bool = True) -> None:
        """Success also pops up: the status line is small and sits at the bottom of a collapsed section."""
        logger.info(f"Backup saved to {location}")
        self._settings_screen.show_backup_status("Backup saved")
        body = f"Saved to:\n{location}\n\n{BACKUP_SOUND_NOTE}" if show_location else BACKUP_SOUND_NOTE
        self._info("Backup saved", body)

    def on_restore_pressed(self) -> None:
        """Pick a backup file and restore it."""
        # A restore closes the DB and force-relaunches: a running (or connecting) session would be silently dropped.
        if self._refused("restoring a backup"):
            return
        if _on_android():
            self._run_restore_saf()
        else:
            self._open_restore_picker_desktop()

    def _run_restore_saf(self) -> None:
        """Android: pick a backup via the SAF open dialog, stream it to an internal
        temp file (SQLite can't open a content:// URI), then run the normal restore."""
        def _on_uri(uri_str):
            if not uri_str:
                return
            threading.Thread(
                target=self._restore_from_uri_worker, args=(uri_str,), daemon=True,
            ).start()

        _saf.open_document(_on_uri)

    def _restore_from_uri_worker(self, uri_str: str) -> None:
        candidate = os.path.join(os.path.dirname(APP.DB_PATH), "_restore_candidate.db")
        try:
            ok = _saf.read_uri_to_file(uri_str, candidate)
        except Exception:
            logger.exception("SAF restore read failed")
            ok = False
        if not ok:
            discard_file(candidate)
            Clock.schedule_once(
                lambda dt: report_soft_error(
                    "restore_failed", "Could not read the selected file", force=True),
            )
            return
        Clock.schedule_once(lambda dt: self._confirm_restore(candidate, discard_after=True))

    def _open_restore_picker_desktop(self) -> None:
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        chooser = ThemedFileChooser(
            path=os.path.dirname(APP.DB_PATH),
            filters=["*.db"],
            size_hint_y=0.85,
        )
        btn_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        ok = StyledButton(text="Restore", bg_color=C.PRIMARY)
        cancel = cancel_button()
        btn_row.add_widget(ok)
        btn_row.add_widget(cancel)
        content.add_widget(chooser)
        content.add_widget(btn_row)
        popup = ThemedPopup(title="Pick a backup", content=content, size_hint=(0.9, 0.9))

        def _do_pick(*_a):
            if not chooser.selection:
                return
            popup.dismiss()
            self._confirm_restore(chooser.selection[0])

        ok.bind(on_release=_do_pick)
        cancel.bind(on_release=popup.dismiss)
        popup.open()

    def _confirm_restore(self, source_path: str, discard_after: bool = False) -> None:
        """Validate, then show confirm dialog → on OK, replace + restart. `discard_after`: source is our temp copy."""
        def _done():
            if discard_after:
                discard_file(source_path)

        ok, msg = validate_backup(source_path)
        if not ok:
            _done()
            report_soft_error(
                "restore_invalid",
                f"Selected file is not a valid backup: {msg}",
                force=True,
            )
            return

        def _restore():
            try:
                self._do_restore_and_restart(source_path)
            finally:
                _done()

        counts = self._db.get_record_counts()
        self._confirm(
            "Restore database",
            f"Replace the ENTIRE database with this backup?\n\n"
            f"Everything on this device ({format_count(counts['users'], 'profile')}, "
            f"{format_count(counts['sessions'], 'session')}, settings, programs and formulas) "
            f"will be replaced by the backup's.\n"
            f"{BACKUP_SOUND_NOTE}\n"
            f"This cannot be undone.",
            "Restore",
            _restore,
            ok_color=C.DANGER,
            on_cancel=_done,
        )

    def _do_restore_and_restart(self, source_path: str) -> None:
        # Defense for the async picker flow: a session may have started, or begun connecting, since _on_restore_pressed.
        if self._refused("restoring a backup"):
            return
        try:
            # No-op every DB access during the restore + relaunch window so nothing
            # reopens the connection and clobbers the freshly-imported file. Error
            # paths below reopen the same manager, so every holder (the settings
            # store, …) is live again; a replaced manager left them on the null connection.
            self._db.mark_shutting_down()
            self._db.close()
        except Exception as e:
            logger.exception("DB close before restore failed")
            report_soft_error("restore_failed", f"Could not close the database to restore: {e}")
            self._db.reopen()
            return

        try:
            restore_backup(source_path, APP.DB_PATH)
        except Exception as e:
            # restore_backup replaces the file atomically, so a failure means the live DB is untouched.
            report_soft_error("restore_failed", f"Restore from {source_path} failed: {e}")
            self._db.reopen()
            return

        # DB is now closed and the file replaced: the app must not flush its settings over it.
        self._on_db_replaced()

    def _open_backup_save_picker(self, default_filename: str) -> None:
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        chooser = ThemedFileChooser(
            path=os.path.dirname(APP.DB_PATH),
            filters=["*.db"],
            size_hint_y=0.7,
        )
        name_input = CenteredTextInput(
            text=default_filename,
            multiline=False,
            size_hint_y=None,
            height=dp(40),
        )
        btn_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        ok = StyledButton(text="Save", bg_color=C.ACCENT)
        cancel = cancel_button()
        btn_row.add_widget(ok)
        btn_row.add_widget(cancel)
        content.add_widget(chooser)
        content.add_widget(name_input)
        content.add_widget(btn_row)
        popup = ThemedPopup(title="Save backup", content=content, size_hint=(0.9, 0.9))

        def _do_save(*_a):
            target = os.path.join(chooser.path, name_input.text.strip())
            popup.dismiss()
            self._run_backup_async(target)

        ok.bind(on_release=_do_save)
        cancel.bind(on_release=popup.dismiss)
        popup.open()
