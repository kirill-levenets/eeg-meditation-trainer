# Session lifecycle

The session state machine, its runner (the one writer of its state), persistence through checkpoints (#30), the timer, and running through a screen lock.
Hard rules are summarized under **Invariants** in [CLAUDE.md](../../CLAUDE.md); this file holds how the subsystem works and why.

## State machine and tick

- **The session's parts** (`app/ui/running_session.py`, the app's `_session`): `RunningSession` builds, once, what every Start runs on:
  `manager` (`SessionManager`), `recorder` (`SessionRecorder`), `engine` (`MetricsEngine`), `formulas` (its own `FormulaSlots`), `program_run` (`ProgramRun`), `timer` (`TimerState`), `watch` (`SessionWatch`), `mock_stream` and `keep_awake`.
  It answers what the running session is scored on (`drive_key`) and saved as (`with_score`, `row_fields`, `session_name`, `custom_formulas_json`); the recorder calls `with_score` and `row_fields` at each checkpoint.
  The real stream stays `Headset.stream` (the link outlives sessions).
- **A session runs on its config.** Start reads Settings once into a frozen `SessionConfig` (`app/session/session_config.py`, built by the app's `_session_config`):
  the metric that drives the sound, the Settings formulas' names and texts, the timer's minutes (a program's total, or none), its end sound, mock or headset (from the stream Start chose) and the device's name.
  `RunningSession.begin(config)` builds the session's own formula lines from it (so their `avg()` windows begin empty), arms its timer and resets the engine and the record.
  While the session runs, nothing reads a setting (`tests/test_session_config.py` fails a tick or a checkpoint that does), so a Settings edit or a profile's reload (re-picking the active profile is allowed mid-session) applies to the next session.
  Two changes reach a running session's state, each as an explicit call:
  the threshold of a simple session (`_put_threshold_in_force`; `SessionManager` owns it),
  and an edited formula line (`FormulaSettings.on_slot_change` → `SessionAccess.set_formula` → `RunningSession.set_formula`), which Settings allows for a slot the sound isn't set to.
  The alert toggles (sinking, distraction, disconnect) are the audio engine's own and apply at once.
- **Session lifecycle** (`app/session/manager.py`): the Start/Pause/Resume/Stop state machine.
  `SessionManager` holds the elapsed time, scores each tick (`add_metric`) and computes the end stats (`compute_statistics`); `RunningSession` wires it to the audio and the recorder.
  `live_score()` is the score so far from running totals (the last tick's value and target, the streaks, the time above, the average since the program's segment began or the session started), for the stats bar every tick.
  It tracks `time_shamatha_90` (time with the shamatha score >= 90, independent of the user's threshold).
  `SessionManager.stop(reason)` plays a short warble alert only for **failure** terminations (`stale_data`, `bt_lost`, `error`); `user` and `timer` are planned stops and stay silent (`timer` plays its own gong).
- **One writer: the run's runner.** Start sets the session up and connects on the main thread, then `RunningSession.start_running()` starts the run's runner, a Python daemon thread (`SessionRunner`) instead of a Kivy `Clock`, so EEG compute, audio volume updates and DB writes go on while the Android screen is locked.
  From then until the run ends the runner alone writes the session's state: every `UPDATE_FREQUENCY` (0.5 s) it runs a tick (a BT-wait step, or the session's tick), and in between the commands the main thread sends.
  The commands are `toggle_pause`, `stop`, `discard`, `abort` (a Cancel), `mark`, `set_threshold` and `set_formula`; each carries the run it was sent for and does nothing for another or for one that ended.
  What the screen must do comes back as events (`Connected`, `StartFailed`, `Paused`, `Resumed`, `Ended`), queued for the main thread for that run only (`on_main_for`), and handled by the app's `_on_session_event`.
  Before the runner starts and after it ends a command runs where it is sent, which is how a test drives a session by hand (`tests/_app.py`).
  Pause and Resume show when the runner has done them (normally within milliseconds): the screen follows the session's state, never ahead of it.
  `stop`, `discard` and `abort` wait until the runner takes them. `discard`, `abort` and the app's exit also wait until it has finished them (the row deleted, the reader's stop, the save; up to 15 s, then it is logged), so what follows on the main thread (a profile's delete, a Retry, the database's close) finds it done;
  a user's Stop doesn't wait for the save, which may wait on the write lock: the screen stays live and the `Ended` event tears it down.
  A runner that doesn't take the command within 1 s is stuck in a read on the link: the command runs where it was sent, its run ended by it, so the late runner, once its read returns, acts on nothing (`_outlived`).
  A runner takes commands only for the run it serves (`_served`): once that run is dropped or replaced a command runs where it is sent, and the late runner drops what was queued to it, so a threshold sent to it never reaches the next session.
  A tick that overruns drops the ticks it missed: two back to back would read one sample twice (a doubled row, half a second too many on the timer and the time above).
  One runner per run means each tick is processed once: two writers processed every tick twice (the timer at double speed, `add_metric`'s fixed 0.5 s per call inflating time above threshold, every metric row saved twice).
  UI work goes through `Clock.schedule_once`, which queues while the app is paused and drains on resume; the per-tick graph and stats update is skipped while paused (`RunningSession.ui_paused`) instead ([below](#screen-lock-and-android)).
- Session names are generated as `"YYYY-MM-DD HH:MM - DeviceName"` (`RunningSession.session_name`: `start_stamp` of `SessionManager.started_at`, then the config's device: the headset's name at Start, or `Mock`); older sessions carry `"HH:MM - DeviceName"`.
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
  `SessionRecorder.checkpoint(stats=None)` (`app/session/recorder.py`, `RunningSession.recorder`, which owns the buffered ticks and the session's row id) → `DatabaseManager.checkpoint_session(sid, stats, ticks, …)`:
  it inserts or updates the session row **and** inserts the buffered tick rows in one transaction, so a process killed at any point leaves the row and the data of one checkpoint, which agree.
  `checkpoint_session` reuses `_insert_session` / `_update_session_row` / `_insert_metrics`, the same SQL `save_session` / `update_session` / `save_metrics_batch` use.
  A checkpoint runs at every snapshot point: the 60 s tick flush (`flush_tick`), the final save (`RunningSession.persist`, with the stop's stats), `_flush_on_leave` (on_pause / on_stop, while a session is running or paused) and both backup workers.
  `on_stop` then also stops and saves a running or paused session.
  Ticks since the last checkpoint (≤ 60 s) are lost on a kill.
  While PAUSED, `SessionManager.elapsed_seconds` is frozen at the pause, so a paused session's checkpoint writes its duration so far.
  `record` (the tick's `add_metric` + buffer append) and a checkpoint's snapshot of both run under the recorder's lock, so a checkpoint from the main or backup thread neither loses a tick nor writes stats that don't match its rows;
  a failed checkpoint puts its ticks back for the next one.
  Leaving the app and both backups go through `RunningSession.checkpoint_or_report()`, which logs and reports a failure (`session_checkpoint_failed`) and carries on: the settings flush, the stop-and-save of `on_stop` and the rest of the backup still run.
  A pending marker is set on the tick's row before it is recorded.
  The row is dated and named by the session's start (`SessionManager.started_at`, 0.0 before a start and after `reset()` → `checkpoint_session(started_at=…)` and `session_name`), not by its first save a minute later.
  **Every ending saves through one path** (#39): `RunningSession._finish(run, reason, alert)` on the writer, then `_finalize_stop_ui(stats, id)` on the main thread (UI teardown).
  `_finish` claims its run (`run.mark_ended()`: one ending wins), silences the noise (`AudioEngine.mute()`, setVolume only, so nothing plays on while the save waits on the write lock), saves (`persist`: the stop's stats and the last ticks, no Kivy) and queues `Ended(stats, session_id, alert)` for its run;
  the app's handler closes a "Stop session?" still open, shows the alert if a check ended it, tears the players down (`AudioEngine.stop()`, on the main thread) and calls `_finalize_stop_ui`.
  A save that fails is reported (`session_save_failed`, past its cooldown) and the run still ends on screen, with no end card: its setup undone, the wake lock and service released.
  A user Stop asks `_confirm_action("Stop session?", ...)`, whose OK sends `stop("user")`; the session goes on recording while the dialog is open, so Cancel loses nothing and Stop saves up to then.
  There is no discard path; deleting is the end card's confirmed action.
  **A session ends once.** A check that ends it (`SessionWatch.check`: data gone stale, the recording limit; the timer) runs `_finish` on the runner at once:
  its duration ends at the detection, its ticks are saved before an unlock Android may never let happen, and with its run ended no later tick can end it again;
  the queued teardown runs only for its run, so an ending that ran first (a profile's delete) isn't followed by an end card for a deleted session (`tests/test_session_ends_once.py`).
  A Stop handled late, after another ending (e.g. the headset-off stale-data stop) has saved the session, must not lose it:
  a confirm that arrives after the session has ended writes nothing (`tests/test_session_ending.py::test_a_stop_confirmed_after_the_session_ended_another_way_keeps_it`).
  `_confirm_action`'s `on_cancel` fires on any close that isn't OK (Cancel, tap outside, Android back), and it decides **once**:
  Kivy keeps delivering taps to a `ModalView` during its 0.1 s fade-out, so a second OK (or OK right after Cancel) would run the action again.
  That logic is `theme.confirm_popup`, the one confirm (OK left, Cancel right); `_confirm_action` and History's delete confirm both call it.
  The session-end card ("Session saved") offers **Save notes** (`ShownSession.on_save_notes`; the card stays open), **OK** and a low-emphasis **Delete session** behind a confirm.
  OK is `ShownSession.close`: it saves the notes only if they changed since the last save (`flush_notes`, against the last written text), so an untouched card writes nothing and clearing saved notes clears them;
  then it stops the gong and closes.
  Delete is `ShownSession.on_delete` → `HistoryFlow.delete_sessions`, which closes the card once the session is gone; a failed delete leaves the card and its typed notes.
  `on_pause` and `on_stop` both flush the card's notes with the settings through `_flush_on_leave`, skipped while `_restoring`.
  Notes go through the one `HistoryFlow.save_notes(sid, notes=, tags=, mood=)` (also the diary's Save and its leave-flush):
  `DatabaseManager.update_session_notes` writes only the fields given and returns whether a row changed; a failure goes to `report_soft_error`.
  Success shows `_toast("Notes saved")` and calls `HistoryScreen.update_session(sid, ...)`, which updates the History model's session in place (a reload would start the list from the top);
  `_update_item` re-derives that row's item, so its notes line appears, changes or goes (and the row's height with it) at once.
  `_toast` is the one toast (also the double-back "Press back again to exit"; `show_toast` in `app/ui/toast.py`): `C.TEXT` on `paint_panel`, added to the `Window` so it shows above any open popup, on every platform;
  only while the app is leaving (`_leaving`, set by `_flush_on_leave`, when nothing the app draws is seen) is it the native Android toast.
  `HistoryFlow.delete_sessions(ids)` is the one delete (a History row, the History selection, the end card):
  one `DatabaseManager.delete_sessions(ids)` transaction over metrics and rows, so an error deletes none of them (`delete_session(sid)` is a selection of one).
  A `wal_checkpoint(TRUNCATE)` follows: one big transaction parks every deleted page in the WAL (40–100 MB for a few hundred long sessions), which keeps that size until a clean close;
  a failed checkpoint (e.g. "database table is locked" while another thread's read is open on the shared connection) is only logged, since the delete has committed.
  The delete runs on a worker thread (a large selection takes 0.3–0.8 s on desktop) behind the loading overlay, and reports `on_done(ok)`;
  the overlay is modal at once and painted only past 0.15 s (`HistoryFlow`'s overlay, `show(text, delay=0.15)`), so a tap can't reach the rows or the end card being deleted.
  A `sqlite3.Error` is reported as `session_delete_failed`.
  On success the Session screen drops a deleted session it shows (`ShownSession.on_sessions_deleted` → `drop`: the end card, whose notes would have no session to save to, closes with its gong, and the display clears).
  `HistoryScreen.remove_sessions(ids)` removes those rows and model entries in place (see the session list in [history.md](history.md)): no rebuild, no spinner, wherever the user is.
  History never lists the running session: its row exists from the first checkpoint, with that checkpoint's stats, and a History reload during the session would list it with them, frozen there until the next reload.
  `RunningSession.running_id()` (`recorder.session_id` while `live()`) is left out of History's list (`HistoryFlow.finished_sessions`) and Settings' profile counts.
  `_finalize_stop_ui` marks History dirty, so the session appears once it ends.
  `delete_sessions` also refuses it (`running_id()` among the ids): its next checkpoints would write ticks for no session.

## Timer

- The meditation timer is split: a headless `TimerState` (`app/session/timer_state.py`) drives the countdown on the session's ticks;
  the user-visible controls (enable, duration, the end-sound picker: Default bell or Custom file..., through the shared source picker, and Test) live in Settings → Timer (`TimerSection`, `app/ui/settings_sections/timer.py`).
  When the timer expires, the tick runs `_finish(run, "timer")` (as above: claim, mute, save, queue the teardown for the main thread);
  the save left the session FINISHED, so `RunningSession.live()` is False and Restore and the profile switch aren't refused after a timed session;
  then `play_timer_sound()` **last** (a one-shot `MediaPlayer` gong, which rings through the lock), with the end sound the session's config holds.
  Saving before the gong, and the players' teardown on the main thread, mean a hung audio call can never cost the session or the summary.
  The gong plays until the file ends or the end card closes (every close goes through `ShownSession.close`), which calls `AudioEngine.stop_timer_bell()` (releases the gong `MediaPlayer` on the main thread);
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
  `KeepAwake` (`app/keep_awake.py`, `RunningSession.keep_awake`) calls its static `start`/`stop`, together with the wake lock and the keep-screen-on flag:
  `hold()` at a session's setup, `release()` at its ending's teardown or an abandoned start, and at `on_stop`, where a session's ending can't tear down (the main thread is closing the app).
- While the app is paused (screen locked) the tick skips its per-tick UI update: N minutes locked would queue ~120·N full graph redraws, which froze the screen on resume.
  The runner records every tick into the session-lifetime mirror instead (`LiveMirror` in `app/ui/live_mirror.py`, `RunningSession.mirror`, which the shown session shows: `_shown.mirror`, no Kivy).
  `LiveMirror.reload_into` reloads the live graphs from it in one batch on resume (while the session runs) and at the session's end (`_finalize_stop_ui`):
  without it, after a session that ended during a lock, the graph would show only the pre-lock seconds while History shows the real duration.
  The mirror records each marked tick as (tick, raw sample) counts since the session's start, and the reload hands the markers to each graph's `load_static_data` with its data;
  counts, not indices, because a full buffer drops its oldest: a marker's index shifts with it, and one that fell off is gone.
  One lock covers `record`, `clear` and the reload's snapshot, so the counts a reload reads match the buffers it copies.
