"""Settings → Timer: simple or program mode, the program a profile edits and its saved programs, and the Session
screen's duration picker, which shows what the next Start runs."""
from collections.abc import Callable

from app.logger import logger
from app.session.manager import SessionState
from app.session.session_program import SessionProgram, runnable_plan
from app.ui.program_run import show_program_series
from app.ui.settings_sections.common import saved_program_label
from app.ui.theme import C


class ProgramSettings:
    """The profile's timer mode and the program it edits, with that program's name. A session runs a snapshot of it
    (ProgramRun), so an edit made during a session waits for the next one."""

    def __init__(self, db, timer_section, live_screen, session_manager, *, user_id: Callable[[], int | None],
                 require_user: Callable[[str], int | None], confirm: Callable[..., None],
                 info: Callable[[str, str], None], confirm_saved_delete: Callable[..., None],
                 show_saved_series: Callable[[int], None], save_settings: Callable[[], None]) -> None:
        self._db = db
        self._timer_section = timer_section
        self._live_screen = live_screen
        self._session_manager = session_manager
        self._user_id = user_id
        self._require_user = require_user
        self._confirm = confirm
        self._info = info
        self._confirm_saved_delete = confirm_saved_delete
        self._show_saved_series = show_saved_series
        self._save_settings = save_settings
        self.mode = "simple"
        self.segments: list[dict] = []
        self.name = ""  # the loaded or saved program's name

    def persist(self, uid: int | None) -> None:
        """Persist the active editable program + its name + timer mode for a user."""
        if not uid:
            return  # silent-ok: persistence helper; no active user = nothing to persist
        self._db.set_user_json_setting(uid, "session_program", self.segments)
        self._db.set_user_setting(uid, "timer_mode", self.mode)
        self._db.set_user_setting(uid, "session_program_name", self.name)

    def load(self, uid: int) -> None:
        """Restore the active editable program + its name + timer mode for a user, and show them in Settings."""
        self.segments = self._db.get_user_json_setting(uid, "session_program", default=[]) or []
        self.mode = self._db.get_user_setting(uid, "timer_mode") or "simple"
        self.name = self._db.get_user_setting(uid, "session_program_name") or ""
        self._show_in_settings()

    def _show_in_settings(self) -> None:
        self._timer_section.load_program(self.segments, self.mode)
        self._timer_section.set_program_name(self.name)

    def program(self) -> SessionProgram:
        return SessionProgram(self.segments)

    def for_session(self) -> SessionProgram | None:
        """The program the next Start runs; None for a simple session."""
        prog = self.program()
        return prog if self.mode == "program" and prog else None

    def governs_live_series(self) -> bool:
        """True when the live metrics graph's visibility is program-driven (program mode
        with a loaded program) — so it must not be persisted as the manual selection."""
        return self.mode == "program" and bool(self.segments)

    def refresh_live_series(self) -> None:
        """Idle preview: in program mode with a loaded program, show the program's metric
        set on the live graph (legend + lines) before Start; otherwise restore the user's
        saved selection. No-op while a session runs (the session owns the graph then)."""
        if self._session_manager.state in (SessionState.RUNNING, SessionState.PAUSED):
            return
        uid = self._user_id()
        if not uid:
            return  # silent-ok: idle live-graph preview; nothing to show without a user
        if self.governs_live_series():
            show_program_series(self._live_screen.graph, runnable_plan(self.program()))
            self._live_screen.set_training_series(None)  # no active segment in idle
        else:
            self._show_saved_series(uid)

    def sync_picker(self) -> None:
        """Refresh the live duration picker: a large 'P' in program mode, else the duration."""
        self._live_screen.refresh_duration_preset(
            self._timer_section.timer_enabled,
            self._timer_section.timer_minutes,
            program_active=self.governs_live_series(),
        )
        self.refresh_live_series()  # idle preview of the program's metric set

    def on_duration_preset(self, value) -> None:
        """Handle Live Session duration tap: a fixed duration is a simple-timer
        choice, so it also leaves program mode."""
        if value is None:
            self._timer_section.timer_enabled = False
        else:
            self._timer_section.timer_enabled = True
            self._timer_section.timer_minutes = value
        self.mode = "simple"
        self._timer_section.set_program_mode("simple")
        self.persist(self._user_id())
        self._save_settings()
        self.sync_picker()

    def on_mode_change(self, mode: str) -> None:
        self.mode = mode
        self.persist(self._user_id())
        self.sync_picker()

    def on_changed(self, segments: list) -> None:
        self.segments = segments
        self.persist(self._user_id())

    def on_save(self, name: str) -> None:
        """Save the active program under `name`. Unique names: an existing name
        overwrites (after confirm); a new name is added directly."""
        name = name.strip()
        if not name:
            self._info("Name required", "Enter a name for the program before saving.")
            return
        uid = self._require_user("save a program")
        if uid is None:
            return
        progs = self._db.get_saved_programs(uid)
        existing = next((i for i, p in enumerate(progs) if p.get("name") == name), None)
        if existing is not None:
            self._confirm(
                "Overwrite program",
                f"A program named '{name}' already exists.\n"
                f"Overwrite it with the current segments?",
                "Overwrite",
                lambda: self._save(existing, name),
                ok_color=C.WARM,
            )
        else:
            self._save(None, name)

    def _save(self, index, name: str) -> None:
        """Add (index=None) or overwrite (index set) a saved program by name."""
        uid = self._user_id()
        if index is None:
            if not self._db.add_saved_program(uid, name, self.segments):
                self._info(
                    "Program library full",
                    f"You can keep up to {self._db._MAX_SAVED_PROGRAMS} saved "
                    f"programs. Delete one before saving another.",
                )
                return
            logger.info(f"Saved new program '{name}'")
        else:
            if not self._db.update_saved_program(uid, index, name, self.segments):
                logger.warning(f"Overwrite skipped: program index {index} out of range")
                return  # no write happened — don't flash a false 'Saved' confirmation
            logger.info(f"Overwrote program '{name}'")
        self.name = name  # the active program now carries this name
        self.persist(uid)
        self.refresh_saved()
        self._timer_section.confirm_program_saved()  # issue #33 E: visible save confirmation

    def has_unsaved_changes(self) -> bool:
        """True when the active program differs from its saved namesake (or is unnamed but
        non-empty) — i.e. loading another program would actually discard edits."""
        if not self.segments:
            return False
        if not self.name:
            return True
        saved = next((p for p in self._db.get_saved_programs(self._user_id()) if p.get("name") == self.name), None)
        if saved is None:
            return True
        return saved.get("segments") != self.segments

    def on_load(self, index: int) -> None:
        """Load a saved program from Settings or the Session screen's 'Programs…' pick, and switch to program mode."""
        uid = self._require_user("load a program")
        if uid is None:
            return
        progs = self._db.get_saved_programs(uid)
        if not (0 <= index < len(progs)):
            return
        name = progs[index].get("name", "")
        # Only warn when there's something to lose; otherwise load straight away.
        if not self.has_unsaved_changes():
            self._load(index, name)
            return
        self._confirm(
            "Load program",
            f"Load '{name}'?\nUnsaved changes to the current program will be lost.",
            "Load",
            lambda i=index, n=name: self._load(i, n),
        )

    def _load(self, index: int, name: str) -> None:
        uid = self._user_id()
        progs = self._db.get_saved_programs(uid)
        if not (0 <= index < len(progs)):
            return
        self.segments = progs[index]["segments"]
        self.name = name
        self.mode = "program"
        self.persist(uid)
        self._show_in_settings()
        self.sync_picker()
        self.refresh_saved()  # re-highlight the now-current program in the picker
        logger.info(f"Loaded program '{name}'")

    def on_delete(self, index: int) -> None:
        uid = self._require_user("delete a program")
        if uid is None:
            return
        self._confirm_saved_delete("program", self._db.get_saved_programs(uid), index, saved_program_label,
                                   self._delete)

    def _delete(self, index: int) -> None:
        self._db.remove_saved_program(self._user_id(), index)
        logger.info(f"Deleted saved program #{index}")
        self.refresh_saved()

    def refresh_saved(self) -> None:
        """Push the current saved-programs list to the settings + session UIs."""
        uid = self._user_id()
        progs = self._db.get_saved_programs(uid) if uid else []
        self._timer_section.set_saved_programs(progs)
        self._live_screen.set_session_programs(progs, self.name)
