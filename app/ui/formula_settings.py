"""Settings → Custom Formula: the three formulas' names and expressions as the profile edits them, and its saved
formulas."""
import os
from collections.abc import Callable

from app.crash_handler import report_soft_error
from app.logger import logger
from app.metrics.custom_formula import compile_formula
from app.metrics.formula_slots import (
    FORMULA_KEYS,
    FormulaSlots,
    default_name,
    read_active,
)
from app.storage.android_share import copy_to_documents
from app.storage.fileops import discard_file
from app.ui.settings_sections.common import save_under_unique_name, saved_formula_label
from app.ui.theme import format_count


class FormulaSettings:
    """Edits the profile's FormulaSlots and plots them on the live metrics graph. The slot the sound is set to is what a
    running simple session is scored on, so `scoring_locked` refuses a change to it until the session ends."""

    def __init__(self, db, section, live_graph, formulas: FormulaSlots, *, user_id: Callable[[], int | None],
                 require_user: Callable[[str], int | None], scoring_locked: Callable[[str], bool],
                 audio_key: Callable[[], str], confirm: Callable[..., None], info: Callable[[str, str], None],
                 confirm_saved_delete: Callable[..., None]) -> None:
        self._db = db
        self._section = section  # Settings' FormulaSection
        self._graph = live_graph
        self._formulas = formulas
        self._user_id = user_id
        self._require_user = require_user
        self._scoring_locked = scoring_locked
        self._audio_key = audio_key
        self._confirm = confirm
        self._info = info
        self._confirm_saved_delete = confirm_saved_delete

    def persist(self, user_id: int) -> None:
        self._db.set_user_json_setting(user_id, "active_formulas", self._formulas.active())

    def load(self, user_id: int) -> None:
        """The profile's formulas into the slots, their names onto the live graph and both into the Settings inputs.
        Visibility is left to the graph's saved series selection."""
        self._formulas.load(read_active(self._db, user_id))
        for key, name in zip(FORMULA_KEYS, self._formulas.names):
            self._graph.set_series_name(key, name)
        for i, (name, ev) in enumerate(zip(self._formulas.names, self._formulas.evaluators)):
            self._section.set_formula_slot(i, name, ev.formula)

    def on_slot_change(self, idx: int, name: str, formula: str) -> str:
        """Apply a slot's name+formula; a valid one shows its line (you typed a formula, you want to see it), and one
        that doesn't compile leaves the slot as it was and returns why. A profile's load goes through `load`, which
        leaves visibility to the saved series selection."""
        ev = self._formulas.evaluators[idx]
        key = FORMULA_KEYS[idx]
        # The slot the sound is set to is what a running session is scored on (or its shamatha fallback, while empty).
        if (key == self._audio_key() and formula != ev.formula
                and self._scoring_locked("changing the formula it is scored on")):
            self._section.set_formula_slot(idx, self._formulas.names[idx], ev.formula)
            return ""  # the refusal says why itself
        if formula:
            _, error = compile_formula(formula)
            if error:
                logger.warning(f"Formula slot {idx} refused {formula!r}: {error}")
                self._section.set_formula_slot_status(idx, f"Error: {error}", is_error=True)
                return error
        self._formulas.names[idx] = name or default_name(idx)
        self._graph.set_series_name(key, self._formulas.names[idx])
        if not formula:
            ev.set_formula("")
            self._graph.set_visible(key, False)
            self._section.set_formula_slot_status(idx, "Formula cleared")
            logger.info(f"Custom formula slot {idx} cleared")
        else:
            ev.set_formula(formula)
            self._graph.set_visible(key, True)  # fires the graph's visibility callback → legend rebuilds
            self._section.set_formula_slot_status(idx, "Formula active")
            logger.info(f"Custom formula slot {idx} applied: {formula}")
        uid = self._user_id()
        if uid:
            self.persist(uid)
        return ""

    def on_save(self, idx: int, name: str, formula: str) -> None:
        """Save a slot's formula to the user's saved library, named by the slot. One that doesn't compile is refused:
        a program segment can pick any saved formula."""
        uid = self._require_user("save a formula")
        if uid is None:
            return
        if not formula:
            self._section.set_formula_slot_status(idx, "Nothing to save", is_error=True)
            return
        _, error = compile_formula(formula)
        if error:
            logger.warning(f"Formula not saved, {formula!r}: {error}")
            self._section.set_formula_slot_status(idx, f"Error: {error}", is_error=True)
            return
        # Fall back to a truncated formula as the display name when none is given.
        label = name or (formula[:40] + ("..." if len(formula) > 40 else ""))
        save_under_unique_name("formula", self._db.get_saved_formulas(uid), label, "this formula",
                               lambda index: self._save(idx, index, label, formula), self._confirm)

    def _save(self, idx: int, index: int | None, label: str, formula: str) -> None:
        """Add (index None) or overwrite a saved formula by its name, and say so under the slot."""
        uid = self._user_id()
        if index is None:
            if not self._db.add_saved_formula(uid, label, formula):
                self._section.set_formula_slot_status(idx, f"Limit reached ({self._db._MAX_SAVED_FORMULAS} max)",
                                                      is_error=True)
                return
        elif not self._db.update_saved_formula(uid, index, label, formula):
            logger.warning(f"Overwrite skipped: formula index {index} out of range")
            return
        self._section.set_formula_slot_status(idx, "Formula saved")
        self.refresh_saved()
        logger.info(f"Formula saved: {label} = {formula}")

    def on_load(self, index: int) -> None:
        """Load a saved formula into the first empty slot and apply it."""
        uid = self._require_user("load a formula")
        if uid is None:
            return
        formulas = self._db.get_saved_formulas(uid)
        if 0 <= index < len(formulas):
            self.assign_saved(self._formulas.first_empty(), formulas[index])

    def assign_saved(self, idx: int, entry: dict) -> None:
        """Assign a saved {name, formula} entry to slot idx (a tap in Saved Formulas or Choose…), show it, and persist.
        One that doesn't compile (saved before Save checked) leaves the slot as it was, its inputs showing what it
        runs, and a popup says why: neither list is near the slot's status line."""
        name = entry.get("name", "")
        error = self.on_slot_change(idx, name, entry.get("formula", ""))
        self._section.set_formula_slot(idx, self._formulas.names[idx], self._formulas.evaluators[idx].formula)
        if error:
            self._section.set_formula_slot_status(idx, "")  # the popup says it; the slot runs what it ran
            self._info("Can't use this formula", f'"{name}" can\'t run: {error}')

    def on_delete(self, index: int) -> None:
        """Delete a saved formula, after a confirmation as a saved program's delete asks."""
        uid = self._require_user("delete a formula")
        if uid is None:
            return
        self._confirm_saved_delete("formula", self._db.get_saved_formulas(uid), index, saved_formula_label,
                                   self._delete)

    def _delete(self, index: int) -> None:
        self._db.remove_saved_formula(self._user_id(), index)
        self.refresh_saved()
        self._section.set_formula_slot_status(0, "Formula deleted")
        logger.info(f"Saved formula #{index} deleted")

    def on_export(self) -> None:
        """Export the saved formulas to a text file where the user can open it, as the bulk session export delivers
        its ZIP: Documents/EEGMeditation on Android (through MediaStore), ~/Documents/EEGMeditation on desktop."""
        uid = self._require_user("export formulas")
        if uid is None:
            return
        formulas = self._db.get_saved_formulas(uid)
        if not formulas:
            self._info("Nothing to export", "There are no saved formulas to export.")
            return
        name = f"formulas_user_{uid}.txt"
        private = os.path.join(os.path.dirname(self._db._db_path), name)
        why = "the copy failed (see the log)"
        try:
            with open(private, "w", encoding="utf-8") as f:
                for entry in formulas:
                    f.write(f"{entry['formula']}\n")
            shared = copy_to_documents(private, display_name=name)
        except OSError as e:
            logger.exception("Formula export failed")
            shared, why = None, str(e)
        finally:
            discard_file(private)
        if shared is None:
            report_soft_error("formula_export_failed", f"Couldn't export the formulas to Documents: {why}", force=True)
            return
        self._info("Export complete", f"Exported {format_count(len(formulas), 'formula')} to:\n{shared}")
        logger.info(f"Exported {format_count(len(formulas), 'formula')} to {shared}")

    def refresh_saved(self) -> None:
        """Refresh the saved formulas list in settings UI."""
        uid = self._user_id()
        if not uid:
            self._section.populate_saved_formulas([])
            return  # silent-ok: renders empty library; no per-user formulas without a user
        self._section.populate_saved_formulas(self._db.get_saved_formulas(uid))
