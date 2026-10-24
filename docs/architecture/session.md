# Session lifecycle

The session state machine, the tick thread, persistence through checkpoints (#30), the timer, and running through a screen lock.
Hard rules are summarized under **Invariants** in [CLAUDE.md](../../CLAUDE.md); this file holds how the subsystem works and why.

## State machine and tick

- **Session lifecycle** (`app/session/manager.py`): the Start/Pause/Resume/Stop state machine.
  `SessionManager` holds the elapsed time, scores each tick (`add_metric`) and computes the end stats (`compute_statistics`); the app wires it to the stream, engine, audio and recorder.
  `live_score()` is the score so far from running totals (the last tick's value and target, the streaks, the time above, the average since the program's segment began or the session started), for the stats bar every tick.
  It tracks `time_shamatha_90` (time with the shamatha score >= 90, independent of the user's threshold).
  `SessionManager.stop(reason)` plays a short warble alert only for **failure** terminations (`stale_data`, `bt_lost`, `error`); `user` and `timer` are planned stops and stay silent (`timer` plays its own gong).
- The session tick runs on a Python daemon thread (`SessionTick`) instead of Kivy `Clock`, so EEG compute, audio volume updates and DB flushes continue while the Android screen is locked.
  UI work goes through `_on_main` (`Clock.schedule_once`), which queues while the app is paused and drains on resume;
  the per-tick graph and stats update is skipped while paused (`_is_paused`) instead ([below](#screen-lock-and-android)).
  **At most one tick thread**:
  two process every tick twice (the timer counts down at double speed, `add_metric`'s fixed 0.5 s per call inflates time above threshold, streak and time ≥90, every metric row is saved twice and the live graph runs ahead of the clock).
  `TickThread.start` (`app/session/tick_thread.py`, the app's `_ticker`) is a no-op while a tick thread is alive, and each thread gets its **own** stop event (`_loop(stop)`; the ticker holds the current one):
  a shared event cleared on restart would revive a thread whose `TickThread.stop` join (1 s) had timed out.
  `_cancel_stop` (Cancel in the Stop dialog) restarts the tick only for a RUNNING session; a paused one gets it back on Resume.
- Session names are generated as `"YYYY-MM-DD HH:MM - DeviceName"` (`_make_session_name`: `start_stamp` of `SessionManager.started_at`, then the headset's name or `Mock`); older sessions carry `"HH:MM - DeviceName"`.
  Neither is shown raw: `app/ui/session_labels.py` (#49) composes what a session is called on screen, for History's rows, the session detail and the end card.
  `start_stamp` is the one `YYYY-MM-DD HH:MM` format: the default name is written with it and the title recognises it.
  `session_title` is `"YYYY-MM-DD HH:MM - <label>"`, the date and time parsed from `date_time` (never sliced); an unnamed session gets just the date and time.
  `session_label` is the name without the session's **own** start time (`start_stamp(date_time)` + `" - "`, or `HH:MM - ` in older names, both made with the row's `date_time`), which is what the rename editor edits:
  a time the user typed into a name is part of the name, and saving the editor unchanged writes nothing, so a default name keeps its date.
  `session_stats_line` is `recorded_score`'s metric name and average, the duration and `Streak` (no average for a program or a session with no scored tick, no streak when 0);
  a session that saved no metric (from before #51) shows `Shamatha <avg_shamatha> · <duration>`, with no streak.
  `session_score_rows` gives the `(label, value)` rows above Time Above Threshold and Longest Streak:
  `Metric` + the metric's name, `Average` + its average (left out when no tick was scored) and `Threshold` + the targets in force.
  Those are `_targets_text`: `score_targets` joined by ` › ` (Roboto has no `→` glyph), more than three as first › … › last, or `threshold_used` for a row from before #83.
  A program gets `Metric` + `<program> (program)` (just `Program` when it was unsaved) and `Threshold` + `Per segment`, with no average (one metric per segment);
  a session that saved no metric gets `Avg Shamatha` + `<avg_shamatha>` and `Threshold Used` + `<threshold_used>`.
  An average reads the same everywhere, through `average_text` (the Session screen's stats bar too).
  `session_notes_line` is the notes' first non-blank line.
  The session detail's Metrics legend marks the recorded series with `»` (`_scored_key`; a program's key matches no series, and a session with no saved metric marks nothing).

## Persistence

- **A session reaches the DB only through checkpoints** (#30):
  `SessionRecorder.checkpoint(stats=None)` (`app/session/recorder.py`, the app's `_recorder`, which owns the buffered ticks and the session's row id) → `DatabaseManager.checkpoint_session(sid, stats, ticks, …)`:
  it inserts or updates the session row **and** inserts the buffered tick rows in one transaction, so a process killed at any point leaves the row and the data of one checkpoint, which agree.
  `checkpoint_session` reuses `_insert_session` / `_update_session_row` / `_insert_metrics`, the same SQL `save_session` / `update_session` / `save_metrics_batch` use.
  A checkpoint runs at every snapshot point: the 60 s tick flush (`flush_tick`), the final save (`_persist_session_data`, with the stop's stats), `_flush_on_leave` (on_pause / on_stop, while a session is running or paused) and both backup workers.
  `on_stop` then also stops and saves a running or paused session.
  Ticks since the last checkpoint (≤ 60 s) are lost on a kill.
  While PAUSED, `SessionManager.elapsed_seconds` is frozen at the pause, so a paused session's checkpoint writes its duration so far.
  `record` (the tick's `add_metric` + buffer append) and a checkpoint's snapshot of both run under the recorder's lock, so a checkpoint from the main or backup thread neither loses a tick nor writes stats that don't match its rows;
  a failed checkpoint puts its ticks back for the next one.
  Leaving the app and both backups go through `_checkpoint_or_report()`, which logs and reports a failure (`session_checkpoint_failed`) and carries on: the settings flush, the stop-and-save of `on_stop` and the rest of the backup still run.
  A pending marker is set on the tick's row before it is recorded.
  The row is dated and named by the session's start (`SessionManager.started_at`, 0.0 before a start and after `reset()` → `checkpoint_session(started_at=…)` and `_make_session_name`), not by its first save a minute later.
  Session persistence is split: `_persist_session_data(reason)` (tick-thread-safe DB write, no Kivy) + `_finalize_stop_ui(stats, id)` (main-thread UI teardown).
  `_stop_and_save` runs both on the main thread; the timer-expiry path runs `_persist_session_data` on the tick thread and defers `_finalize_stop_ui` via `_on_main`.
  **Every ending saves through this one path** (#39):
  user Stop pauses the tick and asks `_confirm_action("Stop session?", ..., on_cancel=_cancel_stop)`, whose OK is `_stop_and_save(reason="user")`.
  There is no discard path; deleting is the end card's confirmed action.
  A Stop handled late, after another ending (e.g. the headset-off stale-data stop) has saved the session, must not lose it:
  a confirm that arrives after the session has ended writes nothing (`tests/test_session_ending.py::test_a_stop_confirmed_after_the_session_ended_another_way_keeps_it`).
  `_confirm_action`'s `on_cancel` fires on any close that isn't OK (Cancel, tap outside, Android back), so the tick that Stop paused is always resumed, and it decides **once**:
  Kivy keeps delivering taps to a `ModalView` during its 0.1 s fade-out, so a second OK (or OK right after Cancel) would run the action again.
  That logic is `theme.confirm_popup`, the one confirm (OK left, Cancel right); `_confirm_action` and History's delete confirm both call it.
  The session-end card ("Session saved") offers **Save notes** (`_on_summary_save_notes`; the card stays open), **OK** and a low-emphasis **Delete session** behind a confirm.
  OK is `_close_summary`: it saves the notes only if they changed since the last save (`_flush_summary_notes`, against `_summary_saved_notes`, the last written text), so an untouched card writes nothing and clearing saved notes clears them;
  then it stops the gong and closes.
  Delete is `_on_summary_delete` → `_delete_sessions`, which closes the card once the session is gone; a failed delete leaves the card and its typed notes.
  `on_pause` and `on_stop` both flush the card's notes with the settings through `_flush_on_leave`, skipped while `_restoring`.
  Notes go through the one `_save_session_notes(sid, notes=, tags=, mood=)` (also the diary's Save and its leave-flush):
  `DatabaseManager.update_session_notes` writes only the fields given and returns whether a row changed; a failure goes to `report_soft_error`.
  Success shows `_toast("Notes saved")` and calls `HistoryScreen.update_session(sid, ...)`, which updates the History model's session in place (a reload would start the list from the top);
  `_update_item` re-derives that row's item, so its notes line appears, changes or goes (and the row's height with it) at once.
  `_toast` is the one toast (also the double-back "Press back again to exit"): `C.TEXT` on `paint_panel`, added to the `Window` so it shows above any open popup, on every platform;
  only while the app is leaving (`_leaving`, set by `_flush_on_leave`, when nothing the app draws is seen) is it the native Android toast.
  `_delete_sessions(ids)` is the one delete (a History row, the History selection, the end card):
  one `DatabaseManager.delete_sessions(ids)` transaction over metrics and rows, so an error deletes none of them (`delete_session(sid)` is a selection of one).
  A `wal_checkpoint(TRUNCATE)` follows: one big transaction parks every deleted page in the WAL (40–100 MB for a few hundred long sessions), which keeps that size until a clean close;
  a failed checkpoint (e.g. "database table is locked" while another thread's read is open on the shared connection) is only logged, since the delete has committed.
  The delete runs on a worker thread (a large selection takes 0.3–0.8 s on desktop) behind the loading overlay, and reports `on_done(ok)`;
  the overlay is modal at once and painted only past 0.15 s (`show_loading(text, delay=0.15)`), so a tap can't reach the rows or the end card being deleted.
  A `sqlite3.Error` is reported as `session_delete_failed`.
  On success the Session screen drops a deleted session it shows (`_drop_shown_session`: the end card, whose notes would have no session to save to, closes with its gong, and the display clears).
  `HistoryScreen.remove_sessions(ids)` removes those rows and model entries in place (see the session list in [history.md](history.md)): no rebuild, no spinner, wherever the user is.
  History never lists the running session: its row exists from the first checkpoint, with that checkpoint's stats, and a History reload during the session would list it with them, frozen there until the next reload.
  `_running_session_id()` (`_recorder.session_id` while `_session_pipeline_live()`) is left out of History's list (`_finished_sessions`) and Settings' profile counts, and `_finalize_stop_ui` marks History dirty, so the session appears once it ends.
  `_delete_sessions` also refuses it (`_recorder.session_id` among the ids while live): its next checkpoints would write ticks for no session.

## Timer

- The meditation timer is split: a headless `TimerState` (`app/session/timer_state.py`) drives the tick-loop countdown;
  the user-visible controls (enable, duration, the end-sound picker: Default bell or Custom file..., through the shared source picker, and Test) live in Settings → Timer (`TimerSection`, `app/ui/settings_sections/timer.py`).
  When the timer expires (on the tick thread, `_end_by_timer`), the order is:
  persist the session via `_persist_session_data(reason="timer")`;
  `AudioEngine.mute()` the noise (non-blocking);
  `TickThread.stop()` (safe from the tick thread, which it doesn't join), which also ends `running`, so `_session_pipeline_live()` is False once idle and Restore and the profile switch aren't refused after a timed session;
  `_on_main(_finish_on_main)` to defer `_audio.stop()` + `_finalize_stop_ui` to the main thread;
  then `play_timer_sound()` **last** (a one-shot `MediaPlayer` gong, which rings through the lock).
  Persisting first and ringing last means a hung audio call can never cost the session or the summary.
  The gong plays until the file ends or the end card closes (every close goes through `_close_summary`), which calls `AudioEngine.stop_timer_bell()` (releases the gong `MediaPlayer` on the main thread);
  `_start_session_common` also calls it, to stop a long custom gong still ringing from the previous session.

## Screen lock and Android

- Android sessions hold a `PARTIAL_WAKE_LOCK` and run a foreground service for multi-hour locked-screen operation:
  `SessionForegroundService` (`android_src/`, Java), declared through p4a's `--native-service` (`p4a.extra_args` in buildozer.spec), which leaves out `android:process`, so it runs in the app's own process (#104).
  A foreground service raises the priority of the process that hosts it, and that has to be the process running the session:
  p4a's own Python services (`services =`) always run in a process of their own, which leaves the session's process at background priority (oom_score_adj 700) whenever another app is in front.
  Its notification channel is low importance, so the session shows an icon in the status bar;
  on Android 13+ only if the user allows the app's notifications, since the app declares `POST_NOTIFICATIONS` but never asks for it (the service runs either way).
  It doesn't stop on its own: in the app's process it can't outlive the app, and every session ending stops it after the save, `on_stop` whatever the state (a start still connecting is no session).
  That includes swiping the app away mid-session:
  Android kills a swiped-away process at once only if it has no foreground service, so the service keeps the process alive while `on_stop` saves the session (a `stopSelf` in `onTaskRemoved` would drop that protection before the save).
  A stop that arrives before `onStartCommand` has called `startForeground` (a start refused or cancelled at once) is only noted: stopping it earlier makes Android crash the hosting process, which is the app's.
  `onStartCommand` stops the service right after going foreground, with `stopSelf(startId)` so a start queued behind it keeps the service.
  `ServiceStartState` (`android_src/`, no Android imports) holds that state:
  a start → starting; going foreground → foreground, or stopped with `stopSelf(startId)` when a stop was noted;
  a stop → `stopService` in the foreground, noted while starting, nothing when stopped (so a second stop does nothing);
  a noted stop belongs to the latest start, so with two starts pending only the last one's going foreground acts on it; a start that throws puts back what it found.
  `tests/test_service_start_state.py` compiles it with `javac` and runs its transition table (`tests/java/`); without a JDK the test is skipped.
  `START_NOT_STICKY` keeps the system from restarting it alone.
  A maker's power manager can still close the app at this priority ([app-platform](app-platform.md#background-running-android)).
  `_start_session_keep_alive_service`/`_stop_session_keep_alive_service` call its static `start`/`stop`.
- While the app is paused (screen locked) the tick skips its per-tick UI update: N minutes locked would queue ~120·N full graph redraws, which froze the screen on resume.
  The tick thread records every tick into the session-lifetime mirror instead (`LiveMirror` in `app/ui/live_mirror.py`, the app's `_mirror`, no Kivy).
  `LiveMirror.reload_into` reloads the live graphs from it in one batch on resume (while the session runs) and at the session's end (`_finalize_stop_ui`):
  without it, after a session that ended during a lock, the graph would show only the pre-lock seconds while History shows the real duration.
