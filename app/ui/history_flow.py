"""History: the list of recorded sessions and what is done with one (save its notes, rename, delete, export)."""
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import datetime as _dt

from app.crash_handler import report_soft_error
from app.logger import logger, timed
from app.storage.android_share import copy_to_documents
from app.storage.csv_export import build_sessions_zip
from app.ui.app_context import AppContext
from app.ui.theme import format_count


def sessions_for_view(db, current_uid: int | None) -> list:
    """The active profile's sessions; none while no profile is active."""
    return db.get_all_sessions(user_id=current_uid) if current_uid else []


class HistoryFlow:
    """The app's History list. A session's row is edited only here: its notes (`save_notes`, for the end card too), its
    name and its deletion (`delete_sessions`, the one delete path, which tells the app through on_sessions_deleted)."""

    def __init__(self, ctx: AppContext, history_screen, formulas, loading, *,
                 on_sessions_deleted: Callable[[list[int]], None]) -> None:
        self._ctx = ctx
        self._history_screen = history_screen
        self._formulas = formulas
        self._loading = loading  # the app's modal overlay, painted only once a delay has passed
        self._on_sessions_deleted = on_sessions_deleted
        self._history_dirty = True
        self._history_view: int | None = None  # the profile History last loaded; a day filter survives only that

    # ---- the History list ----

    def refresh(self, force: bool = False) -> None:
        if not force and not self._history_dirty:
            return
        uid = self._ctx.user_id()
        with timed("history.get_all_sessions"):
            sessions = self.finished_sessions(uid)
        self._history_screen.load_sessions(sessions, keep_filter=uid == self._history_view)
        self._history_view = uid
        self._history_dirty = False

    def mark_dirty(self) -> None:
        self._history_dirty = True

    def finished_sessions(self, uid: int | None) -> list:
        running = self._ctx.session.running_id()
        return [s for s in sessions_for_view(self._ctx.db, uid) if running is None or s.get("id") != running]

    def on_view_mode_change(self, mode: str) -> None:
        """Persist the user's preferred History view layout."""
        uid = self._ctx.user_id()
        if not uid:
            return  # silent-ok: pref persistence; view already changed, no user to save to
        self._ctx.db.set_user_setting(uid, "history_view_mode", mode)

    # ---- a session's row ----

    def save_notes(self, session_id: int, notes: str | None = None,
                   tags: str | None = None, mood: int | None = None) -> bool:
        """The one notes-save path (session-end card, diary): writes only the given fields; failures are reported."""
        try:
            saved = self._ctx.db.update_session_notes(session_id, notes=notes, tags=tags, mood_rating=mood)
        except sqlite3.Error as exc:
            report_soft_error("notes_save_failed", f"Notes for session {session_id} were not saved: {exc}")
            return False
        if not saved:
            report_soft_error("notes_save_failed", f"Notes for session {session_id} were not saved: no such session")
            return False
        # In place: a reload would start the History list from the top.
        self._history_screen.update_session(session_id, notes=notes, tags=tags, mood_rating=mood)
        self._ctx.toast("Notes saved")
        logger.info(f"Notes saved for session {session_id}")
        return True

    def delete_sessions(self, session_ids: list[int], on_done: Callable[[bool], None] | None = None) -> None:
        """The one session-delete path (a History row, the selection, the session-end card): one transaction on a worker
        thread, then History drops the rows in place and the end card closes if it shows one of them. on_done(True)
        once deleted; on_done(False) when refused or failed, with nothing deleted."""
        ids = list(session_ids)
        done = on_done or (lambda _ok: None)
        if self._ctx.session.running_id() in ids:
            # Its row is in History after the first checkpoint; its next checkpoints would write data for no session.
            self._ctx.info("Session in progress",
                           "Stop the session first: a running session can't be deleted. Nothing was deleted.")
            done(False)
            return
        # Modal at once, so a tap can't reach the rows or the end card being deleted; painted only if it takes a while.
        self._loading.show(f"Deleting {format_count(len(ids), 'session')}…", delay=0.15)
        t0 = time.monotonic()

        def _finish(error) -> None:
            self._loading.hide()
            if error is not None:
                report_soft_error("session_delete_failed",
                                  f"{format_count(len(ids), 'session')} could not be deleted: {error}")
                done(False)
                return
            logger.info(f"Deleted {format_count(len(ids), 'session')} {ids} in {(time.monotonic() - t0) * 1000:.0f} ms")
            self._on_sessions_deleted(ids)
            self._history_screen.remove_sessions(ids)
            done(True)

        def _worker() -> None:
            try:
                self._ctx.db.delete_sessions(ids)
            except sqlite3.Error as e:
                logger.exception(f"Deleting sessions {ids} failed")
                self._ctx.on_main(lambda err=e: _finish(err))
                return
            self._ctx.on_main(lambda: _finish(None))

        threading.Thread(target=_worker, daemon=True, name="SessionDelete").start()

    def on_rename_session(self, session_id: int, new_name: str) -> None:
        """Rename a session; its History row already shows the new name."""
        self._ctx.db.rename_session(session_id, new_name)
        logger.info(f"Session {session_id} renamed to '{new_name}'")

    # ---- export ----

    def on_export_csv(self, session_id: int, path: str | None = None) -> str | None:
        """Export session data as CSV file. Returns file path or None."""
        csv_data = self._ctx.db.export_session_csv(
            session_id, custom_formula=self._formulas.evaluators[0]
        )
        if not csv_data:
            return None
        if not path:
            export_dir = os.path.dirname(self._ctx.db._db_path)
            path = os.path.join(export_dir, f"session_{session_id}.csv")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(csv_data)
        logger.info(f"Session {session_id} exported to {path}")
        return path

    def on_export_sessions_csv(self, session_ids: list) -> None:
        """Bulk-export selected sessions as one ZIP of per-session CSVs (issue #7).
        Runs off the main thread behind the loading spinner; delivers via the shared
        copy_to_documents path (Documents on Android, a Documents folder on desktop)."""
        if not session_ids:
            return
        self._loading.show(f"Exporting {format_count(len(session_ids), 'session')}…")

        def _worker():
            try:
                mapping = {}
                for sid in session_ids:
                    csv = self._ctx.db.export_session_csv(sid, custom_formula=self._formulas.evaluators[0])
                    if csv:
                        mapping[sid] = csv
                ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                fname = f"sessions_{ts}.zip"
                tmp_zip = os.path.join(os.path.dirname(self._ctx.db._db_path), fname)
                n = build_sessions_zip(tmp_zip, mapping)
                if n == 0:
                    self._ctx.on_main(lambda: (self._loading.hide(), report_soft_error(
                        "export_empty", "No data to export in the selected sessions.")))
                    return
                dest = tmp_zip
                try:
                    shared = copy_to_documents(tmp_zip, display_name=fname)
                    if shared:
                        dest = shared
                except Exception:  # noqa: BLE001 - the ZIP stays in app storage, and the message names where; logged
                    logger.exception("copy_to_documents failed for bulk export")
                self._ctx.on_main(lambda: self._finish_bulk_export(n, dest))
            except Exception:  # noqa: BLE001 - a worker's failure: the spinner goes and the message says so; logged
                logger.exception("Bulk CSV export failed")
                self._ctx.on_main(lambda: (self._loading.hide(), report_soft_error(
                    "export_failed", "Bulk CSV export failed — see logs.")))

        threading.Thread(target=_worker, daemon=True, name="BulkCSVExport").start()

    def _finish_bulk_export(self, count: int, dest: str) -> None:
        self._loading.hide()
        self._history_screen.set_select_mode(False)
        self._ctx.info("Export complete", f"Exported {format_count(count, 'session')} to:\n{dest}")
