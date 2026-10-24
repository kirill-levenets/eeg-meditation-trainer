# Storage, settings and backup

SQLite storage and its write lock, DB paths and migrations, the per-user settings registry, and backup/restore (desktop and Android SAF).
Hard rules are summarized under **Invariants** in [CLAUDE.md](../../CLAUDE.md); this file holds how the subsystem works and why.

## Database

- **Storage** (`app/storage/database.py`): SQLite with automatic schema migration.
  Stores sessions, per-tick metrics timeseries, user profiles and per-user settings.
  A session row carries `session_name`, `time_shamatha_90`, the metric it was scored on (`score_metric_key`/`score_metric_name`/`avg_score`, #51) and the targets in force, in order, as JSON (`score_targets`, #83);
  each metrics row carries what its tick was scored on (`score_key`/`score_value`/`score_target`, #83; NULL in older rows).
  CSV export support.
  `create_user` raises `UserExistsError` on duplicate name; `find_user_by_name` looks up by exact (case-sensitive) name.
  Per-user settings are a flat KV store (`set_user_setting`/`get_user_setting`, key = `user_{id}_{key}`);
  `set_user_json_setting`/`get_user_json_setting` wrap a value as JSON in one key (the pattern used by `saved_formulas`, and by per-graph series / active-formula lists).
  Every query goes through the self-healing `_conn` **property** (backing `_conn_obj`), so no read/write path can deref a `None` connection:
  a connection closed while the app still runs is reopened (lock-guarded);
  once `mark_shutting_down()` is set it returns a **null connection** (`_NULL_CONN`) that swallows writes and returns no rows, so late access from any path (reads, writes, the daemon tick thread) is a **benign no-op**
  — never a crash, never a reopen that resurrects a closed process or clobbers a freshly-restored DB.
  `on_stop` and `_do_restore_and_restart` both `mark_shutting_down()` before `close()`.
  `delete_user` **purges** the user's metrics, sessions and `user_{id}_*` settings explicitly, in order:
  FKs are declared but not enforced (no `PRAGMA foreign_keys`/cascade), and its sessions, metrics and settings rows would otherwise stay orphaned.
  The settings go by GLOB, not LIKE, so the literal `_` in the key prefix isn't a wildcard.
  The confirm (`SettingsScreen._confirm_user_delete`) states the profile's session count and that they are deleted with it.
- The DB opens with `check_same_thread=False` so the daemon tick thread can write metric batches — and that shared connection is why **every runtime write goes through `DatabaseManager._write()`**:
  one transaction at a time under `_write_lock` (RLock), commit on success, rollback on error.
  Without it the UI thread's commit could end the tick thread's `save_metrics_batch` transaction mid-batch, raise "cannot commit - no transaction is active" into a UI callback, or drop a batch.
  The null connection has a no-op `rollback`.
  `tests/test_database_write_lock.py` covers blocking, a two-thread race with exact row counts, and rollback.
- Android DB path always uses `app_storage_path()` (not `/sdcard`) for a stable path across launches; a DB left in `/sdcard/EEGMeditation/` is copied over when the new path has none yet.
- Desktop DB path resolves to platform user-data folder: Linux `${XDG_DATA_HOME:-~/.local/share}/EEGMeditation/`, Windows `%APPDATA%\EEGMeditation\`, macOS `~/Library/Application Support/EEGMeditation/`.
  One-time migration copies any pre-existing DB from next-to-binary or project root; the old file is left in place for manual rollback.
- DB migrations (Android `/sdcard → app_storage_path` and desktop legacy → user-folder) surface failures via `crash_handler.queue_pre_app_error(label, detail)`:
  `EEGMeditationApp.on_start()` replays them (`flush_pre_app_errors`) through `report_soft_error`.
  **Project policy:** never `except (PermissionError, OSError): pass` — surface a diagnostic instead.

## Per-user settings

- **Per-user settings registry** (`app/settings/registry.py`):
  each scalar per-user setting is declared once as a `Setting(key, default, parse, serialize, get, set)` descriptor,
  built in `_build_settings_store()` (in `build()`, after the screens exist and BEFORE any user load, so each default is snapshotted from the app's constructed initial state).
  They are the threshold, audio metric/index, feedback+reward source/path, alert toggles, timer enable/minutes/sound, line width and colours, rotation, graph zoom, marker hotkey, stats mode, device mock, the fold states (History chart, What-if, band power), **theme** and text size.
  `SettingsStore.load(uid)` applies each setting as its parsed stored value **or its default when absent/invalid**
  — it ALWAYS applies a value, so a fresh/partial user can never inherit the previously-active user's in-memory value.
  `save(uid)` serializes all in **one transaction** (`DatabaseManager.set_user_settings`, one `executemany` + commit, not one commit per key); `persist(uid, key)` writes one key immediately (change-callback path), suppressed while loading.
  `_persist_user_setting(key)` (key only — the store reads the live value) catches `sqlite3.Error` → soft error;
  the threshold slider and the timer sound go through `_persist_user_setting_later(key)`:
  a per-key Kivy `Clock` trigger (`_after_settle`) restarted on every change (`_PERSIST_SETTLE_S` = 0.5 s), so a drag is one write, not one fsync per step on the UI thread.
  `timer_sound`'s getter reads its widget (like `timer_enabled`/`timer_minutes`).
  `_load_user_settings`/`_save_user_settings`/`_persist_user_setting` are thin calls into the store;
  the **aggregates** (custom formulas, saved programs/formulas, the edited program, per-graph series) keep their own handling (`FormulaSettings`, `ProgramSettings`, `GraphSeries`).
  **Theme is per-user** (its descriptor, `get=C.theme_name`/`set=C.set_theme`);
  the global `theme` key (`theme_seed(db)`), left from before themes were per-user and no longer written, is only the default for a profile with no theme of its own;
  `build()` builds the UI in `startup_theme(db)` — the startup profile's theme, else that seed — so the profile load applies the theme already showing (a no-op);
  the text size starts the same way (`startup_text_size`).
  Both are `startup_value(db, setting)`: the startup profile's value read as `SettingsStore.load` reads it (`stored_value`: the stored value if present and valid, else the default).
  The theme setting (`theme_setting(seed)`) rejects an unknown stored name, so it loads the seed: `set_theme` ignores an unknown name, which would keep the previous profile's palette.
  Codecs: `BOOL/INT/FLOAT/STR` (parse, serialize) pairs.
  Values live in the `app_settings` KV table (via `get/set_user_setting`) — normalizing that table is a deliberate deferred follow-up.
- `_flush_on_leave`, from `on_pause()` (Android) and `on_stop()`, saves the settings and unsaved notes and checkpoints a running session, so they persist when the OS kills a backgrounded app; both skip it while `_restoring`.
  `on_pause()` always returns `True` — per Kivy docs, returning `False` stops the app rather than "refusing to pause".

## Backup and restore

- **DB backup/restore** (`app/storage/backup.py`):
  **`online_backup_to_tempfile(db)` writes SQLite's online `Connection.backup()` (transaction-safe) to a temp `.db` beside the live DB (internal storage) and returns its path;
  callers byte-copy or stream it out, then delete it**
  — SQLite returns `SQLITE_CANTOPEN` ("unable to open database file") if asked to open/lock a DB directly on Android FUSE storage (`/sdcard`) or a `content://` URI, so the destination is never opened by SQLite.
  `make_backup(db, path)` wraps it + `copy_file_atomic` (desktop / real filesystem paths), and refuses a target that resolves to the live DB (the desktop save picker opens in the DB folder;
  `os.replace` would leave the open connection writing to the swapped-out file).
  `validate_backup` checks for the `users` and `sessions` tables;
  `restore_backup` validates, `copy_file_atomic`s, then removes the replaced DB's `-wal`/`-shm` so SQLite can't replay them onto the restored file.
  A `backup()` on the shut-down DB raises `sqlite3.OperationalError` (a silent no-op would write an EMPTY backup the user later restores).
  **Every app file copy goes through `app/storage/fileops.copy_file_atomic(src, dst)`**
  — bytes and mode, no extended attributes, into a temp file beside `dst`, fsync, `os.replace` (so `dst` is untouched or complete) — never `shutil.copy2`:
  in Android app storage copying the SELinux label raises EACCES *after* the data is written, which the phone's Python 3.11 `shutil` doesn't ignore (3.12 does), so a copy that succeeded reports failure (#63).
  The same EACCES is the harmless Kivy `Error when copying logo directory` on the first launch after an install.
  `discard_file(path)` is the shared remove-and-log for temp/leftover files.
  Custom sound files come in through the Storage Access Framework too: `android_saf.import_document` copies a picked document into app storage ([audio](audio.md#engine)).
- The Settings → Data Backup flow around it (the pickers, the copy on a worker thread, the confirmation, the replace) is `BackupFlow` in `app/ui/backup_flow.py`, which reaches the app only through what `_bind_callbacks` gives it:
  the DB, the Settings screen, the profile name, the settings flush, the checkpoint, the session guard, the popups, and `on_db_replaced`, where the app sets `_restoring` and shows the relaunch popup.
  **Android uses the Storage Access Framework** (`app/storage/android_saf.py`), not a hardcoded path
  — scoped storage (targetSdk 30+) forbids direct `/sdcard` writes:
  `WRITE_EXTERNAL_STORAGE` no longer grants them, and `buildozer.spec` declares `MANAGE_EXTERNAL_STORAGE` ("All files access", API 30+) but the app never asks the user for it.
  Backup:
  `_run_backup_saf` → SAF `ACTION_CREATE_DOCUMENT` save dialog (user picks location) → `online_backup_to_tempfile` → `android_saf.write_file_to_uri` streams the temp through the returned `content://` URI via `ContentResolver.openOutputStream`.
  Restore: `_run_restore_saf` → SAF `ACTION_OPEN_DOCUMENT` → `android_saf.read_uri_to_file` streams the picked file to an internal temp `_restore_candidate.db` (`FileUtils.copy`, API 29+) → normal validate + restore;
  `_confirm_restore(path, discard_after=True)` deletes that temp on every exit (invalid file, Cancel, after the restore), a failed read deletes the partial one, and a desktop user's own picked file is never deleted.
  No storage permission, survives uninstall, works API 29→34+.
  `android_saf` routes results via a request-code registry bound once to `android.activity.on_activity_result`; all pyjnius imports are function-local so it imports cleanly off-Android.
  The desktop backup worker catches `(OSError, sqlite3.Error)`;
  the SAF workers catch broadly (pyjnius boundary); both `report_soft_error`.
  Desktop uses `ThemedFileChooser` (a Kivy `FileChooserListView`) save/open popups.
  Restore **refuses to run while a session is active**
  — running, paused, OR still in the BT-connect wait (`_session_pipeline_live()`: state RUNNING/PAUSED, `_waiting_for_bt`, or a live tick thread; the same window `_on_user_delete` discards on active-profile delete).
  Checked at `BackupFlow.on_restore_pressed` and again in `_do_restore_and_restart` (the DB shutdown would silently drop the session).
  `_confirm_restore` validates the file before its confirm;
  `_do_restore_and_restart` `mark_shutting_down()`s + closes the live DB, and `restore_backup` copies the file over `APP.DB_PATH`;
  then the app force-restarts via the "Please relaunch" popup (`_show_relaunch_popup`, re-shown from `on_resume` if Android resumes the process instead of killing it) → `App.stop()`:
  in-memory caches reference the old DB, so a restart is simpler.
  A close or copy failure there surfaces `report_soft_error` and calls `DatabaseManager.reopen()`, which clears the shutting-down latch and reconnects the **same** object:
  the settings store and every other holder keep a live reference, where a new manager would leave them on the null connection and silently drop every later settings write.
  **Mid-session backup freshness (#30):** `BackupFlow.on_backup_pressed` calls `_save_user_settings()` (main thread) before dispatching to the SAF/desktop worker, so a backup taken mid-session isn't a stale pause/stop snapshot;
  every scalar per-user setting also persists on change ([Per-user settings](#per-user-settings)), so they survive an Android force-kill too.
  `_save_user_settings` catches `sqlite3.Error` and reports a soft error: it runs from UI callbacks (backup, pause, profile switch), where an escaping error would open the fatal dialog, and a failed flush doesn't abort the backup.
  It **never touches `_timer_state`**:
  a running session — especially a program, which force-enables the timer and seeds its countdown from the program total — OWNS it, and re-applying the Settings timer widgets on a pause/backup flush would kill or shift its auto-stop.
  Session start re-applies enabled/duration, and `_on_timer_sound_change` keeps the gong path current, so nothing needs an idle sync.
  Both backup workers checkpoint a running session first (`_checkpoint_or_report` → `SessionRecorder.checkpoint`, see [session](session.md#persistence)), so a mid-session backup holds it as of the backup.
  The restore confirm (`_confirm_action`) states it replaces the **entire DB**, with the profile and session counts from `get_record_counts()`.
  Both backup paths end in `_report_backup_saved(location)`:
  a **Backup saved** `_info_popup` carrying `BACKUP_SOUND_NOTE` ("Custom sound files are not included in a backup.", in the restore confirm too; the SAF path omits the content:// URI), a short status line, and a log line;
  the status line alone is small and sits at the bottom of a collapsed section.
  The suggested file name is `backup.backup_filename(user_name, now)` → `eeg_backup_<profile>_<YYYY-MM-DD_HH-MM>.db` (profile first, so the narrow SAF name field still shows it;
  path separators, whitespace and FAT-illegal characters become `_`; no usable name → just the time).
  Missing custom sound files are reported by **one** `_warn_missing_sound_files(feedback_sources, timer_path)` report at session start and from both Test buttons:
  a second `report_soft_error` while the first's dialog is pending is dropped.
  The Test buttons pass `force=True` (user-initiated, like Copy Diagnostics):
  the label's 60 s cooldown after a session-start report can't hide the file the user just tested, so `play_timer_sound`'s fallback to the default gong is never silent.

## Exports to shared storage

- A file the user exports to open elsewhere (a session's CSV on Android, the bulk sessions ZIP, the saved formulas) goes through `android_share.copy_to_documents(private_path, display_name=…)`:
  on Android through MediaStore into `Documents/EEGMeditation/`, with no storage permission; on desktop a copy into `~/Documents/EEGMeditation/` that replaces a file of the same name.
  MediaStore keeps a file already there and stores a clashing name as "name (1)", so the helper reads the stored name back (`_stored_name`) and returns that path for the export's message;
  a failed read-back returns the requested name, since the file is written.
