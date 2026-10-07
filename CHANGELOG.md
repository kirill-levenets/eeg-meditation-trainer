# Changelog

All notable changes to the EEG Meditation Trainer are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Delete several sessions at once** (#57): History → **Select** → pick sessions (or **Select all**) → **Delete N**. One confirmation states how many sessions and over which days (and how many profiles, in the All Users view); they are deleted together in one step, so an error deletes none of them, and the list updates in place; a large selection shows "Deleting…" instead of freezing the screen. History no longer lists a session that is still running: after its first minute it could show up with that minute's stats, and deleting it there left its data still being written; it appears once it ends. Deleting the session whose Session saved card is still open closes the card. The History delete confirmation now ignores a Delete tapped while it closes after Cancel (it could delete anyway), and its buttons are in the same order as every other confirmation.
- **Crickets reward sound** (issue #11): a new reward-channel source that plays a soft ~0.1 s cricket chirp roughly once every 10 seconds while you hold above the threshold — a gentle "you're doing well / still here" cue instead of a continuous drone. The periodicity is baked into a looping ~10 s waveform (mostly silence + one short chirp), so it rides the existing lock-safe volume ramp with no extra timers. Settings → Audio → Reward sound → **Crickets**. The **Test Audio** button now also previews the reward source first, so you can hear Crickets (or Tone/Custom) before a session.
- **Feedback / reward sound source is now a picker** instead of a row of buttons: tapping **Feedback sound** or **Reward sound (above threshold)** opens a chooser list (Off / Rain / Tone / [Crickets] / Custom file…); choosing **Custom file…** opens the file browser directly and the button shows the chosen file. Removes the crowded button row and the separate custom-path row.
- **Visible button press feedback** (issue #33): pressing any button now raises an edge-visible ring that lingers as it fades on release — the old feedback only darkened the fill *while held*, which a fingertip covers on mobile, so taps on buttons like **Save** felt dead. The ring colour tracks the theme (light on dark themes, dark on light) so it stays visible on every palette. Saving a Session Program now flashes a green **"Saved"** confirmation on the button, so an overwrite (which doesn't change the list) is no longer silent.
- **Per-user theme.** The colour theme is now saved per profile (was one global setting shared by everyone). Existing installs keep their current theme; each profile can now choose its own.

### Changed

- **A session's detail opens as soon as you tap it** (#59): its title, stats and notes show at once, and you can read and edit the notes while the band power and graphs load (each shows "Loading…" until its data is in, then they fill in one by one), instead of a full-screen spinner until everything was drawn. Going back, or opening another session, while one loads never shows the first one's data. The session's data is now read once instead of twice, so the graphs also arrive a little sooner.
- **The metric a session is scored on can't change while it runs**: switching the audio control metric, its formula slot, or the formula in that slot during a simple session (or while it connects) is refused with "Stop the current session before…", and Settings shows the metric in force again. Switching mid-session mixed both metrics into one average, time above threshold and streak, saved under the last metric's name. The other formula slots and the threshold stay editable, and a program session, scored on its segments' metrics, leaves the metric and the formula slots free.
- **The Session saved card fits a landscape phone**: held sideways, the card shows the stats on the left and a larger notes field on the right, with OK and Delete below both, so nothing needs scrolling; held upright it stays one column. The session's name moved into the title: "Session saved · 2026-10-05 07:15 - MindWave Mobile" on one line sideways, under "Session saved" upright. The stats lines are closer together, and upright the notes field is as tall as **Save notes** next to it.
- **Each History row says when the session ran, how it scored, and what you noted** (#49): the first line is the date, start time and name ("2026-09-26 14:30 - MindWave Mobile", or your own name after the time); before, a row showed only its name, so sessions from different days looked the same and a renamed session lost even its time. The second line names the metric the session was scored on (the one that drove the feedback sound) with its average, then the duration and the longest streak; a program session shows the program's name. A third line shows the first line of the session's notes, and updates as soon as notes are saved. Long names and notes are cut with "…" instead of overflowing. The session detail is titled the same way (it showed "Session #id" and a raw timestamp). New sessions are named "YYYY-MM-DD HH:MM - device"; the rename editor edits only the name, and a time you type into a name stays. Sessions recorded before the app saved their scoring metric keep their old line (average Shamatha and duration): nothing is guessed for them, and no stored session is changed.
- **The session detail and the Session saved card show what was scored** (#49): a **Metric** row ("Shamatha", or the program's name), an **Average** row with that metric's average (none for a program) and a **Threshold** row ("50", or "Per segment" for a program) say what the session was scored on and what Time Above Threshold and Longest Streak were measured against, and the session detail's Metrics legend marks that series with "»"; sessions from before keep their **Avg Shamatha** and **Threshold Used** rows. Both cards drop Avg Meditation, the separate Avg Shamatha and Time Shamatha ≥ 90 (still stored and exported); the Session saved card adds the session's name and Longest Streak.
- **Session detail notes save themselves** (#40): an edit to a session's notes, tags or mood is saved when you leave the session detail — Back, another tab, or the app going to the background — with the same "Notes saved" as the **Save Notes** button, so it is no longer lost. Opening a session without changing anything writes nothing, and leaving saves only what you changed, so it never rates a session you haven't rated. Saving notes no longer reloads History, which kept its place in the list.
- **History opens at once, however long your history** (#42): the session list now builds only the rows on screen and reuses them as you scroll, so History opens without a full-screen spinner, and picking a day, Show All and Select / Cancel no longer rebuild every row (on a phone with a few hundred sessions each took tens of seconds, and grew with every session). Leaving a profile also drops its selected sessions, so Select → Export can't include another profile's sessions. The rename editor's Save button shows its label (it was squeezed to one letter per line), no longer reaches over the row's rename/delete buttons, and the keyboard comes up when you tap the pencil.
- **Graphs stay fast however far you zoom out** (#70): zoomed out, a graph now draws at most a few points per pixel column (each column's first, last, highest and lowest value), so zooming out over a long session — or the Raw EEG view zoomed out over its last minute — no longer makes every redraw slower. The line looks the same: no peak or dip is dropped.
- **All pop-up windows share one look, in your theme**: confirmations (Stop, Delete), the graph series and duration pickers, the program and formula pickers, file pickers, the profile chooser, info and diagnostic dialogs, the session-end card, the connection and loading screens and the "Notes saved" message are now the same rounded panel in the current theme's colours — they used to be always dark, whatever the theme. Every Cancel/Close button looks the same, and windows size to their content instead of leaving half the window empty. The quick-notes field on the session-end card now says "Quick notes" inside it (the separate label made the card too tall for a landscape phone).
- **Android app is half the size**: the APK no longer carries the build tools' Python environment by mistake. APK 39 MB → 20 MB; the app files unpacked on the first launch after an install or update 53 MB → 2.4 MB.

### Fixed

- **Moving the threshold during a session now moves the scoring with it** (#83): the feedback sound followed the slider at once, but Time Above Threshold and Longest Streak kept counting against the threshold the session started with, the SHAMATHA badge kept that value too, and a session still connecting started with it. They now change together, from the moment you let go of the slider (a drag counts as one change, at the value where it stops). During a program session the slider no longer moves the sound away from the segment's target: the segments set the targets, so the threshold controls are locked until the program stops: dimmed, they don't move, and every touch on them says why. The graph's dashed threshold line steps where the threshold changed — live, after a screen lock and in History — instead of redrawing the whole session at the new value (with no session running, a new threshold clears the last session's graphs from the Session screen and shows its line), and the Threshold row of the Session saved card and the session detail lists the thresholds in order ("70 › 85"). Every recorded tick now stores the metric it was scored on, its value and the threshold in force (also in CSV exports), so what a session was measured against no longer depends on settings that changed during it; sessions recorded before keep their single threshold.
- **A headset that drops the link while connecting no longer makes you tap Retry**: when the headset closed a new connection without sending data, the app reconnected by itself but then gave up a fraction of a second later, because the 8-second wait for data was still counting from the first connection; the new connection now gets its own 8 seconds, and its own 30 seconds to connect (a drop after the first 30 seconds, e.g. while you were still placing the sensor, ended the wait). Data received before such a drop also no longer counts as "headset streaming" for the new connection, which could leave the wait open with no timeout, nor starts the session on a new connection that hasn't sent anything yet. A headset that keeps closing the connection ends the wait at the third drop, asking you to switch it off and on.
- **Cancelling or stopping a session that is still connecting always cancels it** (#52): Cancel during "Scanning for MindWave…" no longer starts the session anyway; Cancel (or deleting the active profile) at the moment the headset's first data arrives no longer leaves the feedback sound playing with no session running; Stop right after a failed connection no longer offers to save a session that never started, and Stop as the timer ends no longer drops the headset connection; and a cancelled or failed program session no longer leaves the program's graph series behind.
- **A session's time in History is when it started**: the time and the name ("HH:MM - device") were taken when the session was first saved, a minute after it started. The session screen's start time and the graph's clock also come from the start: a session that connected while the screen was locked showed the unlock time.
- **A session the app dies in keeps its real length** (#30): a running session's length and stats were saved once, after its first minute, and only updated when it ended normally — so a session ended by a crash or by Android closing the app in the background showed about a minute in History over all of its recorded data. They are now saved together with the data every minute, when the app goes to the background, and when a backup is made, so History, the stats and a mid-session backup agree with the recorded data (up to the last minute, on a crash). A paused session keeps its length up to the pause.
- **The app crashed when zooming the session graph out over a long session**: once about 45 minutes or more were in view, drawing the coloured Shamatha line exceeded the phone's graphics limit for one shape and the app closed with a crash report. The line is now drawn in pieces that stay within the limit.
- **Switching the colour theme left parts of the app in the old colours** (#38): after a theme change in Settings the stats card under the session graph could turn white with white text, and the session detail, the Settings sections, the session-end card, the History 14-day bars and the graphs kept the previous theme until the app was restarted. Every screen now repaints at once, in both directions, including parts hidden at the moment of the switch. The Theme section highlights the right theme after a profile switch too, and no longer says the change needs a restart. Starting the app now builds the screens in your profile's theme directly; before, they were built in a default theme and then switched. Text on a selected button (the Metrics/Raw toggle, Cal/14d, the selected theme, selected graph series and durations) now picks the readable glyph for its colour, and two pop-up texts that were dark on the dark pop-up in the light themes (the first-run welcome, "No saved programs") are readable.
- **Time above threshold and Longest streak counted the wrong metric** (#51): in a normal (non-program) session they were measured on Meditation while the feedback sound followed Shamatha or your custom formula. They now count the metric that drives the sound, the live graph legend marks it with » (when that line is shown), and each session records which metric it was scored on (key, name and its average). Expect these two numbers to change meaning from this version on; earlier sessions keep their old values, which were measured on Meditation.
- **Taps on a session's Notes field often went to the graph instead** (#66): once the session detail was scrolled down to Notes (always in landscape, and on phones where the detail is taller than the screen), the graph scrolled out of view below still claimed taps in the area it would occupy unscrolled, so the Notes field rarely took focus. Graphs now only receive taps where they are actually drawn, in their own coordinates, so every visible part of a graph takes taps, drags and pinches. A vertical swipe over a graph now scrolls the page (horizontal drags still pan the graph), which matters in landscape, where the session graph fills the screen above the stats and Start/Stop. Pinch-zoom on a graph inside a scrolled page works reliably.
- **Deleting a session from History rebuilt the whole list** (#56): with a few hundred sessions the phone showed a full-screen "Loading history…" spinner for about 20 seconds after one delete and then jumped back to the top of the list, and in one report the list came back blank until the app was restarted. A delete now removes just that row, keeps your place and any day filter, and updates the count and the calendar/14-day bars at once; renaming a session no longer rebuilds the list either. The blank list itself came from the scroll position running away when the list was rebuilt right after a fling past its end; the list now always lands at the top, visible. Reloading History also keeps an active day filter, and switching or deleting a profile no longer leaves the previous profile's sessions in History (or in Select / Export).
- **Restore on Android reported "Permission denied" and skipped the relaunch** (#63): the backup's data was in fact copied over the database, but copying the file's metadata then failed, so the app showed a `restore_failed` report and kept running on the pre-restore state instead of asking for a relaunch. Restore now copies only the data, into a temp file that replaces the database in one step (a failed copy leaves the current database untouched), removes the old database's leftover journal files, and deletes its temporary copy of the picked backup on every outcome. After a restore that does fail, settings changes are saved again (they were silently dropped for the rest of that run), and a desktop backup can no longer be saved over the app's own live database file.
- **A quick double tap on a confirm dialog could run its action twice**, and OK tapped right after Cancel could still run it: the dialog kept accepting taps while it faded out. Every confirm (Stop, Restore, delete, program save/load) now acts once.
- **A single tap could delete a session, and session notes were easily lost** (#39): the Stop dialog's **Discard** deleted the session at once with no confirmation, and closing the end card with **Close** or **View in History** threw away notes you had typed. Stop now asks "Stop session?" and always saves — like a timer or lost-signal ending — and every ending shows the same **Session saved** card: **Save notes** saves them on the spot, **OK** keeps notes you typed but didn't save (also when the app goes to the background or is closed), and **Delete session** asks for confirmation first. A user Stop during a Session Program now also restores the graph's series and clears the training marker, as the other endings already did. Saving notes no longer clears the session's tags and mood, and a failed save is reported instead of silently ignored.
- **After Stop → Cancel during a pause, the session counted double**: pressing Stop and then Cancel while paused, and then Resume, made the session process every update twice until the next pause or stop — the timer ran at double speed (ending a timed session early), the graph ran ahead of the clock, and time above threshold, longest streak and time at 90+ were inflated. Each session now runs exactly one update loop.
- **Pause → Resume silenced the feedback sound for the rest of the session** (#37): after resuming, neither the below-threshold sound nor the reward sound came back until the session was stopped, while the sinking bell and distraction chime kept playing, so it sounded as if the feedback sound had changed. Pause now keeps the session's sounds and Resume brings the same ones back.
- **The live session graph made the app stutter more the longer a session ran**: each update redrew the coloured Shamatha line as hundreds of separate pieces and re-rendered every axis label, so by a few minutes in a single redraw took up to ~200 ms on the phone and the screen hitched twice a second. It is now drawn as one shape with labels reused: the worst redraw is ~40 ms and frame hitches ~70 ms. The Shamatha line's colour now follows the value along every pixel, so a steep jump shows a smooth blue→red gradient.
- **After a glance at Raw EEG, the hidden raw graphs kept drawing**: switching back to Metrics left the raw and band graphs redrawing off-screen every update (~130 ms each on the phone, more than the visible graph). Hidden graphs now pause and catch up when shown again.
- **Time labels overlapped at wide zoom**: zoomed out to tens of minutes, the session graph drew a time label every 10 seconds on top of each other; marks are now spaced to stay readable at any zoom (10 s, 15 s, 30 s, 1 min … 2 h).
- **No alert sound when a session ended on lost signal**: when a session auto-stopped because the headset stopped sending data or the Bluetooth link dropped, the warble that should tell you so was cut off within milliseconds by the audio shutdown that follows it, so the session ended silently. The warble now plays to the end.
- **Settings leaked between profiles / weren't reset for a new profile.** Most settings (threshold, audio metric, feedback/reward sounds, alert toggles, timer, line width, rotation, zoom, marker hotkey, stats view, device mode) were only *applied if present* on load, so switching to a profile that hadn't set one — or creating a fresh profile after another was active — kept the previous profile's value instead of the default. All per-user settings now load through a single registry that always applies a defined default, so each profile is fully isolated. (Also fixes saved programs and other per-user UI showing the previous/deleted profile's data.)
- **Deleting a profile left its data behind.** `delete_user` only removed the profile row, orphaning its sessions (which could still appear in the All-Users history view), metrics, and settings. It now purges all of the deleted profile's data.

- **Mid-session backup captured stale settings** (issue #30): several settings (threshold, audio-drive metric, feedback/reward source, alert toggles, …) were only written to the database on pause/stop, so a **Backup** taken mid-session saved their *last-saved* values and a later restore silently reverted them. Backup now flushes current settings first, and settings persist **as you change them** (so they also survive an Android force-kill) — sliders and typed paths once they settle, taps immediately — with the batch save kept as a backstop. The **Restore** confirmation now states it replaces the **entire database** (with the number of profiles and sessions), and Backup and Restore both note that custom sound **files** are not stored in a backup. A missing custom **timer gong** file is now reported at session start and by its **Test** button (together with any missing feedback/reward file, in one message), instead of silently falling back to the default gong.
- **App could run with no active user, silently dropping per-user actions** (issue #29): after a reinstall, a restored/edited database, deleting the active profile, or a corrupt `last_user_id`, the app started usable but with no user selected — so saving a Session Program (and other per-user actions) silently did nothing, and History/Diary could show every profile's sessions commingled. The app now hard-gates on a resolved user (a blocking, un-escapable profile picker; the bottom nav stays disabled until you choose or create one), re-gates when you delete the active profile, and never falls through to all-profiles data for an unset user. Per-user actions now explain "select a profile" instead of failing silently; and a database connection closed while the app is still running (e.g. after a restore) self-heals instead of dropping writes.
- **"Off" audio feedback still played rain below threshold**: with the below-threshold sound set to Off (dual-zone feedback, v1.4.0), a session prepared no players, but the start path treated the empty set as "not yet configured" and fell back to a rain loop — so noise played anyway (most visible in program mode). The start path now plays only the configured channels (empty = silent); the Settings "Test" button still previews the rain sweep explicitly.
- **Headset could stop streaming until power-cycled after a cancelled or timed-out connect** (Android): the MindWave accepts only one Bluetooth connection, and a connect that was cancelled or hit the 30 s timeout could still complete in the background and hold that connection open with nobody reading it — so the next **Start** connected but got no data until the headset was switched off and on. The app now closes any connection it no longer owns, closes every failed connection attempt, and won't start a second reader while the previous one is winding down. Bluetooth data is now read in bulk (was one byte per call, ~4000 calls/s) on a raised-priority thread so the reader keeps up with the headset's 512 Hz stream, and the last-resort channel-1 connection fallback, which never actually ran, now works.
- **Cancel during "Connecting…" froze the app and then showed a false "Connection failed" error**: with the headset off or out of range, tapping **Cancel** blocked the screen for several seconds while the app waited for the connection attempt to give up (on desktop Linux and with a serial splitter too), then reported a connection failure you hadn't had ("Check device is on and paired"). Cancel now aborts the attempt immediately and returns quietly to idle; a **Start** tapped while a previous attempt is still closing says so ("Previous connection is still closing — retry in a few seconds") instead of starting a second, competing connection. **Stop** during "Connecting…" now also closes the connection overlay instead of leaving a frozen countdown on screen.
- **Phone stayed awake after a failed connection** (Android): when connecting failed (e.g. headset off), the app kept its wake lock and the foreground "session" notification running until the next session. They are now released on every way a connection attempt ends.
- **Cancelling before any session had started could crash the app** (e.g. Cancel on "Scanning for MindWave…" right after launch).
- **Switching profiles during a session changed that session's settings underneath it**: picking another profile (or the All-Users view) while a session was running or connecting loaded that profile's timer, threshold and sounds into the running session — a program's auto-stop could be switched off, or an untimed session could suddenly end on the other profile's timer and be saved under it. Switching profiles is now refused until the session is stopped ("Session in progress").
- **Dialog text could be cut off**: in landscape (or with a larger font) the Restore confirmation silently dropped the lines that didn't fit — including "This cannot be undone" — before an irreversible replace; information messages (e.g. "Session in progress"), the profile and session delete confirmations and the export result had the same flaw. All of them now size to their text and scroll when it's longer than the screen.
- **A storage error while changing a setting or tapping Backup closed the app**: a database write that failed (e.g. database locked by another program on desktop, disk full) escaped into the crash dialog, which exits the app, and aborted a backup that would have worked. It's now reported as a normal error message and the backup continues.
- **Dragging the threshold slider or typing a gong path wrote to storage on every step** (up to ~160 writes for one drag, one per keystroke), on the UI thread; each change is now saved once, half a second after you stop.
- **After a timed or program session, Restore was refused with "Session in progress"** (with Stop disabled) until another session was started and stopped, and deleting the active profile in that state also deleted the session just saved.
- **Rare crash or lost session data from overlapping database writes**: a setting change or Backup landing during the session's 60-second save could crash the app, drop up to a minute of recorded metrics, or save duplicate rows. Database writes from the session and the UI are now serialized.
- **Backup gave no visible confirmation**: the "Backup saved" note appeared only as a small line at the bottom of the Data Backup section, easy to miss. A **Backup saved** dialog now confirms it (with the reminder that custom sound files are not included).
- **Android backup dialog came up with an empty file name**, so each backup had to be named by hand. It now suggests `eeg_backup_<profile>_<date>_<time>.db`.
- **"Press back again to exit" hint never appeared on Android**: the first back press on the Session screen now shows it, as intended.
- **Deleting a profile didn't say its sessions go with it**: the confirmation said only "All their settings will be lost"; it now states how many sessions will be permanently deleted with the profile.

## [1.4.0] - 2026-06-29

### Added

- **Multi-select CSV export from History** (issue #7): a **Select** button on the History list enters selection mode — tap rows to check them, **Select all** / **Cancel**, then **Export N** bundles the chosen sessions into one **ZIP of per-session CSVs** (each `session_<id>.csv`, the existing format). Export runs off the UI thread behind the spinner and lands in `Documents/EEGMeditation/` (Android) / a Documents folder (desktop).
- **Dual-zone audio feedback** (issues #12, #9): the feedback now has two independently-chosen channels. The **below-threshold** sound (the existing noise, default Rain) fades out as you approach your threshold; a new **above-threshold reward** sound (default Off; Tone/Rain/Custom) fades *in* and rises the further you exceed the threshold (to full at +30), giving a positive cue once you reach shamatha. Either channel can be set to **Off** (no sound). The two cross-fade cleanly at the threshold. Settings → Audio. Subsumes the "sound after reaching shamatha" request (#9).
- **App version on the Android splash + About**: the startup presplash now shows the version (e.g. `v1.3.0`) under the logo, and Settings → Help → About is bumped to match — so you can tell at a glance which build is installed. The splash is regenerated by `tools/gen_presplash.py` (reads `APP_VERSION`, stamps a pristine `presplash_base.png`); rerun it after a version bump.
- **Per-band power breakdown in the diary** (issue #8): each session's detail now shows total power per frequency band as a **sortable table** — colored share bars with Power and % columns. A **Detailed / Grouped** toggle switches between the 8 sub-bands (delta / theta / alpha1 / alpha2 / beta1 / beta2 / gamma1 / gamma2) and the 5 collapsed bands (alpha = alpha1+alpha2, etc.). Tap a column header to sort (tap again to reverse); the view mode and sort persist per user. Computed on read by summing the already-recorded per-tick band powers — no schema change.
- **Shamatha reached is now obvious on the session screen** (issue #13): when your shamatha score holds at or above your meditation threshold, the status text turns into a bold `SHAMATHA` label on a green pill, then reverts when you drop back below. A short debounce (1.5 s above to enter, 1.5 s below to exit) keeps it from flickering on the 2 Hz signal.

### Changed

- **Distraction and Sinking now match the original Vernihor app.** These two metrics were a clean-room sigmoid redesign in the rewrite; they are now ported term-for-term from the original. Distraction is the raw `(beta1+beta2)/alpha1` ratio modulated by `(140 − shamatha)` and zeroed when alpha dominates; Sinking is alpha2-deficit driven, gamma-damped, and similarly gated. The shamatha/meditation score is unchanged (it was already a faithful port). Live and newly-recorded sessions use the new formulas; **existing sessions are unaffected** — the diary reads each session's stored values rather than recomputing them. Every session now records an `engine_version` so stored metric values stay attributable to the formula set that produced them.
- **Android releases are now signed with a fixed release key** (CI). GitHub release APKs were debug-signed with an ephemeral per-build key, so users could not install a new APK over an old one (signature mismatch) and were forced to uninstall — wiping their local database. The release workflow now signs with a consistent keystore (from GitHub secrets), so **future updates install in place and keep all sessions/settings**. Setup: `docs/ANDROID_SIGNING.md`. (Note: the first signed build is still a signature change vs. already-installed debug builds, so that one update still requires a reinstall.)

## [1.3.0] - 2026-06-27

### Fixed

- **Android database backup crashed, then couldn't reach /sdcard**: `make_backup` opened SQLite directly on `/sdcard` (FUSE storage can't provide the locks SQLite needs → `SQLITE_CANTOPEN`), and even after staging the backup in internal storage, scoped storage (targetSdk 33) blocked the copy with `EACCES` regardless of `WRITE_EXTERNAL_STORAGE` (and `MANAGE_EXTERNAL_STORAGE` doesn't exist on Android 10 / API 29). Android backup/restore now use the Storage Access Framework: a system "Save as" / "Open" dialog lets you choose the location, and bytes stream through the returned `content://` URI. No storage permission needed, the backup survives uninstall, and it mirrors the desktop file picker.
- **Disabled session buttons were invisible on light themes**: Kivy's `Label` draws `disabled_color` (default white at 30 % alpha → invisible on light cards), not `color`, while disabled — so the dimmed grey computed for the disabled Start/Pause/Stop/Mark glyphs was never used. `StyledButton` now sets `disabled_color` too, so disabled glyphs stay a legible dimmed grey on every theme.
- **Android release build failed in CI**: python-for-android `master` now builds each recipe in an isolated venv that pulls Cython 3.1.x, whose generated C fails to compile Kivy 2.3.0. Pinned `p4a.branch` to the known-good `v2024.01.21`.
- **Timer-end gong was silent on desktop**: `AudioEngine.stop()` unloaded the gong's `SoundLoader` sound one frame after it started — the timer-expiry path defers `stop()` to the main thread, after the gong is already playing. `stop()` no longer touches the gong; it now rings at program and timer end on desktop (Android was already handled via a separate `MediaPlayer`).
- **Program editor controls were unresponsive**: the hidden mode container's `disabled` children extended beyond their zero height and swallowed taps across the entire Timer / Program section. The active controls are now swapped into and out of the widget tree instead of merely hidden, so collapsed controls have no geometry on the touch layer.
- **Segment rows displayed in reverse order**: new segments were prepended to the editor list. They now append at the bottom, matching program execution order.
- **A program session leaked its timer into the next simple session**: starting a new simple session after a program session kept the program's total duration in the timer, which then auto-stopped the session early. Session start now re-syncs the timer from Settings for simple sessions.
- **The diary recorded later edits instead of the program that actually ran**: the `session_program` JSON was saved from the live settings state at stop time rather than from a snapshot taken at start. The snapshot is now captured at session start and is what gets persisted and replayed in the diary.
- **Series-picker Close button blended into the selected metrics on the green themes**: it was a `PRIMARY` (green) fill, nearly identical to the green `ACCENT` "selected" pills on Dark/Light Green. It's now a neutral outlined button (grey border, `TC.TEXT` label), distinct from the pills on every palette.
- **Opening a session froze the UI for ~4s on long sessions**: the diary's raw-EEG `_synthesize_waveform` generated the *whole* session at 512 Hz (≈1.4M samples for a 47-min session → ~11.5M `math.sin` calls) but the graph's deque only keeps the last 60 s — so 99.5 % was computed then discarded. It now synthesizes only the retained tail (preserving the global sample phase so the tail is bit-identical), cutting the synth from **3604 ms → 75 ms** and total session-open from **3993 ms → 569 ms** on-device. The diary load also now runs off the UI thread behind a loading spinner.
- **Legend labels overlapped / were clipped with many series**: every legend was a single-row `BoxLayout` that split the width equally, so 6 metrics + 3 custom formulas overlapped (on-graph) or ran off the edge (fullscreen). A new wrapping `LegendBar` (flow layout) flows labels and wraps to extra rows, sizing each label to its text — all series stay readable on the live, diary and fullscreen legends.
- **History tab froze for ~0.9s building the session list**: 76 rows were built in one synchronous loop on the UI thread. Rows now build in chunks across frames (`Clock`), behind a loading spinner, so the UI stays responsive and the first rows appear quickly.
- **Graph expand / series-picker glyphs were illegible off the dark-blue theme**: `_draw_icon_backing` used a fixed 40 %-black backing with a near-white glyph — on light palettes it rendered as a grey box with an invisible glyph, and on the dark palettes it sat *darker* than the graph background. The backing is now fully transparent; the glyphs draw directly on the graph in `TC.TEXT`, which contrasts on every palette (light on dark themes, dark on light).
- **Single hardware-back press left the app instantly**: the Android back button wasn't handled, so Kivy's default fired and one press dropped you to the launcher. Back is now consumed (`Window.on_keyboard`, key 27) and routed — see Added.
- **Settings section headers stole/ate taps after scrolling (a collapsed User Profile picker switched the user when you tapped Threshold)**: a collapsed `ThemedAccordion` section left its content laid out inside a zero-height `ScrollView` — display-clipped but still occupying the *touch* layer. Through the nested-ScrollView simulated-click transform, a hidden user-row button's `collide_point` matched a tap aimed at a section header below it, grabbed the touch, and fired its `on_release` (switching the active user). Collapsing a section now detaches its content from the ScrollView (re-attached on expand), so it has no geometry to overlap and taps reach the real visible header. Found by instrumenting the touch path on-device.
- **Metrics/Raw EEG view toggle unresponsive when the session layout overflowed into scroll mode** (e.g. desktop/landscape): `GraphAwareScrollView` matched graphs by their *logical* bounds, which extend past the visible viewport, so it stole touches aimed at widgets sitting outside the ScrollView (the toggle above the graph). It now only intercepts touches within its own viewport (a `collide_point` guard on `on_touch_down`/`on_scroll_start`). Found via an automated button-by-button click pass.
- **Session ended instantly when starting with a real device + timer**: on the BT-connect path `start_countdown()` was dispatched to the main thread while the tick thread proceeded to `tick()`; if the main thread stalled at connect, `remaining` was still 0 and the timer fired on the first tick (a 0-second "timer-ended" session). The countdown is now armed on the tick thread before the loop can read it.
- **History duration showed 0**: `compute_statistics()` read the `_elapsed` field (0 until `stop()`), so the 60-second partial flush wrote a duration-0 row that persisted if the app was later killed. It now uses the live `elapsed_seconds`.
- **Session lost / app frozen at timer end with the screen locked**: `_audio.stop()` ran on the daemon tick thread and called `MediaPlayer.release()`, which synchronizes with the player's event handler on the **main Looper** — paused during lock — and deadlocked the tick thread, so the session never saved and the noise never stopped. Timer-end now persists the session first on the tick thread, silences the noise with a non-blocking `mute()`, and defers the real teardown to the main thread.
- **Meditation gong did not ring at timer end while locked**: the bell used SoundLoader, which Android silences during screen lock. The timer gong now plays through a one-shot `MediaPlayer` (USAGE_MEDIA) so it sounds at the timer end with the screen off.
- **Stale graph after a locked timer session**: closing the summary revealed a graph covering only the pre-lock seconds (the locked portion never reached the live graph via the per-tick path). The live graphs are now reloaded in one batch from the session-lifetime mirror buffers on both resume and finish, and the header timer is synced to the final duration.
- **Delete-confirmation dialog text invisible in light themes**: the session/user name used `C.TEXT` (dark) on Kivy's always-dark popup chrome. Added a theme-independent `POPUP_TEXT` constant and a `text_size` binding (wrap) for the History session-delete and Settings user-delete dialogs.
- **White-noise could play while the connect overlay was still visible**: audio start is now dispatched atomically with hiding the overlay instead of starting on the tick thread ahead of it. `MediaPlayer.unload()` always calls `release()` even if `stop()` raised, and audio-teardown failures are logged instead of silently swallowed.

### Added

- **Selectable feedback sound** (issue #10): choose Rain (original), a built-in Tone drone, or a custom audio file (wav/mp3/ogg/flac/m4a) in Settings → Audio as the continuous feedback channel. The volume modulation is unchanged — it still tracks the active metric. Each program segment also has a **Feedback** picker (Default / Rain / Tone / Custom); "Default" inherits the global selection, and the source switches at each segment boundary lock-safely via `set_active_feedback` (setVolume-only, no mid-session teardown).
- **Session Program** (issue #6): programmable per-segment sessions as an alternative to a single fixed-duration timer.
  - Settings → Timer now has a **Simple | Program** toggle. Simple = existing single-duration timer (unchanged). Program reveals a segment editor.
  - Each segment row specifies: duration (minutes), a **formula** (Shamatha, Meditation, NS Attention, NS Meditation, or any saved custom formula), a **target** level, and an **end-cue** sound (Chime or Warble).
  - **+ Add Segment**, per-row delete, total-duration readout. Named programs can be saved and reloaded; the saved-programs library is per-user.
  - The program's total duration becomes the session timer; the session auto-stops at the last segment's end via the existing timer-end path (gong plays).
  - At each segment boundary a transition chime plays; the active target, audio-driver formula, and "time above target" stat all follow the current segment.
  - A **stepped threshold line** is drawn on both the live session metrics graph and the diary metrics graph (each segment's target over its time range).
  - The program that ran is recorded per session (`sessions.session_program` column); the diary replays the stepped threshold line from that record.
  - Per-segment feedback sound picker shipped in issue #10 (see Selectable feedback sound entry above).
- **Saved-program overwrite confirmation**: saving a program whose name already exists prompts an "Overwrite?" confirmation and replaces the existing entry instead of creating a duplicate. Loading and deleting saved programs also show a confirmation prompt. After loading a program, its name is pre-filled in the name field so a subsequent save overwrites it in place.
- **"Loaded:" program label in the segment editor**: the editor header shows `Loaded: <name>` (or `Loaded: (unsaved)`) and pre-fills the name field, so it is always clear which saved program is currently loaded.
- **Program indicator on the Session duration button**: when Program mode is active the duration button on the Session screen shows a large **P** instead of a duration. Switching timer mode in Settings and returning to the Session tab updates the button immediately. The duration popup gained a **Programs…** quick-picker that loads a saved program directly from the session screen, shows the loaded program's name on the button, and highlights the currently loaded program in the list.
- **Per-segment series highlighting on the live metrics graph**: the graph auto-shows the formula series being trained in the current segment and marks it with a bold `» ` prefix in the legend. A segment's custom formula is plotted on a dedicated line named after the formula; the user's manually-shown custom slots are hidden while the program drives its own and restored at session end.
- **Settings "Timer" section renamed to "Timer / Program"**: the Enable-Timer checkbox is now shown only in Simple mode (a program always drives the timer, so the toggle is irrelevant in Program mode).
- **Text inputs center-aligned**: all single-line text input fields (name, duration, formula expression, etc.) now align their text horizontally and vertically to center; multiline fields (notes) retain left/top alignment.
- **Threshold ± steppers**: Settings → Threshold now has `−` / `+` buttons that nudge the value by 5 (clamped 20–180), alongside the slider and quick presets, for fine control.
- **More timer presets**: Settings → Timer and the live-session duration picker gained 30 min, 1 h, 1 h 30 min and 2 h presets (slider already went to 120). The session-screen duration picker now lays its timed presets out in a 2-column grid with "Free" full-width below, so it stays compact.
- **`[PERF]` timing harness** (`app/logger.py` `timed(label)` context manager): logs block wall-time when `EEG_PERF=1` (off by default). Used to instrument the History and diary load/render paths; grep logs for `[PERF]`.
- **Loading spinner on slow loads**: the previously-unwired `LoadingOverlay` now backs the diary session-open (off-thread DB/compute, render dispatched to main) and the chunked History list build.
- **Android back-button navigation** (issue #4, F3): the hardware back button is now handled with a precedence chain — close an open fullscreen graph → dismiss an open popup (let the `ModalView` self-dismiss) → Diary detail back to History → any non-root tab (History/Settings) back to Session → on the Session root, **double-tap within 2 s to exit** (first press shows a "Press back again to exit" Android toast). Bound via `Window.on_keyboard`, consuming key 27 so Kivy's default exit-on-escape never fires.
- **Close-circle fullscreen button**: the fullscreen graph's red "Close" text button is now a transparent close-circle glyph (`Icons.CLOSE_CIRCLE_OUTLINE`, `C.TEXT`), matching the stroked, theme-aware look of the on-graph expand/series glyphs.
- **Three named custom formula slots** (issue #4, F4): Settings → Custom Formula now has three independent named slots (Slot 1 / 2 / 3), each with a name field, expression input, Apply, Save, and a per-slot status line. Slot names are shown as the series label on the live metrics graph (`set_series_name`). One slot at a time drives the audio noise channel — the `[1][2][3]` selector below the "Custom Formula" audio-metric radio binds `audio_formula_index`; if the selected slot has no valid formula, the engine falls back to shamatha. The on-graph series picker on the live metrics graph shows a **Choose…** button on each custom-formula row to assign a saved library formula to that slot without opening Settings. All three slots share one Y-axis (scale 200, reference line at 100). Active slot names and expressions persist as `active_formulas` (JSON, per-user); the audio index persists as `audio_formula_index` (flat KV, per-user). Legacy single-formula users are migrated: slot 1 seeds from the old `custom_formula` scalar.
- **Per-session formula replay in the diary** (issue #4, F4): each session now records the custom formulas active during it (name, expression, visibility, audio-drive flag) in the `sessions.custom_formulas` JSON column at save time. Opening the session in the diary rebuilds those evaluators and **recomputes** their series from the session's own stored band powers — so History shows the formulas (and names) that were active *then*, not today's edits. Recompute reuses the existing `recompute_formula_series` infra; injection happens before the diary graph populates and is reset per session. Malformed/missing records are tolerated (no crash, empty series).
- **On-graph series picker** (issue #4, F2): a list-glyph in each graph's top-left (mirroring the top-right expand glyph) opens a multi-select popup to choose which series are plotted; toggles update the graph + legend live. The picker is now wired on **every** multi-series graph — live metrics/band and diary metrics/raw-freq — by a single presenter (`_present_series_picker`) that reads each graph's own catalog, labels and colors; single-series graphs (raw waveform) are skipped since a picker there could only blank the line. Both affordances are drawn into the graph canvas and hit-tested in window coordinates, so neither can be starved by the ScrollView. Selection persists per-user per-graph as `graph_series_<graph_id>` (JSON); the live metrics graph migrates the legacy per-metric `toggle_<key>` rows, other graphs default to all-visible. The former **Settings → Graph Metrics** checkbox section (and "Show Custom Formula") was removed — the on-graph picker is now the single series-selection UI (subsume).
- **Fullscreen-expandable graphs** (issue #4, F1): every time-series graph shows a top-right expand glyph; tapping it opens the graph in a full-window overlay with a Close button. Implemented once in the shared `ScrollableGraphWidget` (`set_expand_callback`), wired to all live + diary graphs via one presenter. The graph is *reparented* (not cloned) into a root `FloatLayout` overlay, so a live session graph keeps updating in fullscreen; Close restores it to its original parent/size. A full-window overlay (not a `Popup`) is used so the graph reaches every edge.
- **Graph UX infrastructure** (foundation for the rest of issue #4):
  - `app/ui/touch_utils.py` — `point_in_rect(px, py, rect)`, the shared transform-safe sub-region hit-test primitive (touches arrive in widget-local space; the recurring bug was a responsive area not matching the visible one). Used by the expand glyph; the History/user-picker manual routers are candidates to migrate.
  - `LoadingOverlay` widget (`app/ui/widgets/loading_overlay.py`) — reusable dimmed modal spinner (status + animated dots, theme-aware, collapses out of the touch chain when hidden). Mounted app-global by wrapping the root in a `FloatLayout`; driven via `EEGMeditationApp.show_loading(text)` / `hide_loading()`.
  - `DatabaseManager.get_user_json_setting()` / `set_user_json_setting()` — JSON-encoded per-user settings over the existing flat KV store (basis for per-graph series selection and active-formula lists).
- **History view toggle**: Calendar heatmap / 14-day bar chart segmented control on the History screen. Both views share day-tap-to-filter behavior. Selection persists per user as `history_view_mode`.
- **`Last14DaysBars` widget** (`app/ui/history_screen.py`) — bar chart of the last 14 days' avg shamatha, mirroring `CalendarHeatmap`'s public API.
- **Shared `UserPickerForm`** widget (`app/ui/widgets/user_picker.py`) used by the wizard, the first-run popup, and Settings → User Profile. Existing profiles are listed; typing a duplicate name surfaces an inline "Use existing 'X'" / "Change name" choice instead of failing silently.
- **Wizard skip-step-2** when an existing profile with a saved BT device is picked — onboarding goes directly to the live session.
- **Settings → Data Backup** section with **Backup database** / **Restore database** buttons.
  - Backup uses SQLite's online `Connection.backup()` API (transaction-safe).
  - Android writes to `/sdcard/Documents/EEGMeditation/meditation_backup_YYYYMMDD_HHMMSS.db` (visible to file managers, Telegram, `adb pull`).
  - Desktop opens a Kivy `FileChooserPopup`.
  - Restore validates that the file is a real SQLite DB with `users` and `sessions` tables, asks for confirmation, then force-restarts the app via a "Please relaunch" popup.
- **`DatabaseManager.find_user_by_name`** and typed **`UserExistsError`** raised by `create_user` on duplicate.
- **`crash_handler.queue_pre_app_error` / `flush_pre_app_errors`** for diagnostics that occur before the Kivy app is up (e.g. `config.py` migrations). Replayed from `EEGMeditationApp.on_start()`.

### Changed

- **Desktop DB path moved** from project-root / next-to-binary to the platform user-data folder:
  - Linux: `${XDG_DATA_HOME:-~/.local/share}/EEGMeditation/`
  - Windows: `%APPDATA%\EEGMeditation\`
  - macOS: `~/Library/Application Support/EEGMeditation/`

  On first launch, an existing DB at the old path is copied across automatically. The old file is left in place for manual rollback — you can safely delete it after verifying the move worked.
- **DB migration failures** (Android `/sdcard → app_storage_path`, desktop legacy → user-data) now surface a diagnostic via the in-app error dialog instead of being silently swallowed. **Project policy**: any I/O exception we can't reasonably ignore must use `report_soft_error(label, detail)` (or `queue_pre_app_error` if pre-app-start).

### Removed

- **`AnalyticsScreen`, `HomeScreen`, `AnalyticsAggregator`** — unreachable from the bottom nav. Their functionality is replaced by the new History view toggle. Roadmap entry added for a project-wide dead-code audit.

## [1.2.0] - 2026-04-27

### Fixed (timer overhaul, folded into the v1.2.0 retag)

- **Timer-end sound was inaudible**: when the meditation timer expired,
  the bell was started by the tick thread and then unloaded ~10–50 ms
  later by the immediate `_audio.stop()` inside `_stop_and_save`. The
  log line "Timer sound: default bell" appeared but no audible bell
  played. Reordered the timer-expiry path to play the bell *after*
  `_stop_and_save` (so the engine teardown can't truncate it) and added
  `AudioEngine.stop_timer_bell()`. The bell now keeps playing on the
  summary card until the file ends naturally, or the user taps any
  summary button (Save / View in History / Close), which calls
  `stop_timer_bell` first. Starting a new session also pre-emptively
  stops any leftover bell.
- **Custom timer-end sound was unreachable in the UI**: the path input,
  Browse (file chooser) and Test buttons lived on `app/ui/timer_screen.py`,
  which was registered in the screen manager but had no nav entry, so
  no user could actually set a custom WAV. Moved those controls into
  Settings → Timer accordion. The orphan `TimerScreen` is removed; the
  countdown logic moved to the headless `app/session/timer_state.py`
  (`TimerState`).
- **Custom timer-end sound was not restored at launch**: the path was
  written to user settings but read back into the orphan widget,
  effectively losing it on every launch. The persisted value now
  restores into both `TimerState` and the new Settings input.

### Added (timer overhaul, folded into the v1.2.0 retag)

- `AudioEngine.stop_timer_bell()` — stop only the timer-end bell early,
  used by summary-button handlers to honour user-driven dismissals.
- `TimerState` — Kivy-free model with `enabled`, `duration_minutes`,
  `remaining_seconds`, `custom_sound_path`, `start_countdown()`, `tick()`
  and `reset()`. Drives the session tick loop directly.
- **Default timer-end bell is now deeper and longer** (220 Hz fundamental,
  4 s decay vs the previous 800 Hz / 0.6 s tingsha). Generated to a
  separate `timer_bell.wav` so the sinking-alert bell stays short and
  high for crisp mid-session pings. Configurable via
  `APP.TIMER_BELL_FREQUENCY` / `APP.TIMER_BELL_DURATION`.
- **Test button doubles as a Stop button.** Tapping Test in
  Settings → Timer starts the configured sound and flips the button
  text to "Stop"; tapping it again interrupts playback. The button
  reverts to "Test" automatically when the file ends naturally
  (Sound.on_stop binding, scheduled on the main thread).

### Removed (timer overhaul, folded into the v1.2.0 retag)

- `app/ui/timer_screen.py` — the orphan `TimerScreen` UI was unreachable
  through the bottom nav (which only lists session / history / settings)
  and its widgets (countdown label, file picker, Test Sound) were dead
  code. Functionality moved as described above.

### Added

- Landscape-aware Live Session layout with pinned bottom bar and scrollable body.
- Global crash handler with markdown report copied to clipboard.
- Multi-hour locked-screen operation on Android via foreground service + partial wake lock.
- Short warble alert when a session terminates unexpectedly (BT lost, stale data).
- Toggle between live and aggregate stats on the bottom of the session screen.
- **Session duration picker on the Live Session screen.** The Start
  controls now split into a simple `Start` button and an adjacent
  duration-picker button that shows the active choice (e.g. `▼ 10 min`
  or `▼ Free`). Tapping the duration button opens a modal popup with
  five preset choices (**5 / 10 / 15 / 20 min** or **Free**); the current
  preset is highlighted. Picking one applies the timer and dismisses the
  popup. Start simply begins the session with whatever is set. Settings →
  Timer preset row aligned to [5, 10, 15, 20] for consistency.
- `StyledButton(vertical=True)` for 2-row icon-top/text-bottom buttons.
- `GraphAwareScrollView` yields drag and multi-touch to graph widgets (press-drag scrolls time axis; pinch zooms).
- Custom `_DurationPickerButton` (compact 2-row pill) for the Live Session timer dropdown.
- Live/Aggregate stats toggle on the Live Session screen, persisted per user.
- Default Shamatha-only metric legend for new users.
- Adaptive landscape layout (`_compute_graph_height_adaptive`).

### Changed

- 2 Hz session tick moved from Kivy Clock to a daemon thread; UI updates dispatched via `Clock.schedule_once`.
- Android noise channel uses `MediaPlayer` (with `USAGE_MEDIA` audio attributes) so audio survives screen lock.
- `on_pause()` always returns True (the previous False return was killing the app on screen lock).
- History row touch routing replaced with a single `_list_touch_down` handler at the session-list level (Android tap-target reliability).
- Bottom-bar action buttons (Start/Pause/Stop/Mark) render as 2-row icon+text.

### Fixed

- Connect-overlay countdown freezing on slow BT connects (`_stop_tick_thread` no longer joins the current thread).
- Sinking bell / distraction chime default OFF for new users.
- Stats toggle button vertical alignment + clearer "LIVE"/"AVG" text.
- **Settings → Device list clipped to a single row on Android.** When the
  Device accordion section was opened *before* the Bluetooth scan
  populated the list, `_AccordionSection._scroll.height` snapshotted the
  empty content height and never grew when rows were appended later. The
  `_content.minimum_height` is now bound to `_update_height`, so the
  ScrollView tracks grandchild growth.

### Added

- **Multi-device picker.** When more than one paired device matches
  `mindwave`/`neurosky` (case-insensitive) on auto-scan or on session
  start, the app no longer silently picks the first one — it routes the
  user to Settings → Device, opens the section, scrolls it into view,
  shows a "pick one" banner and lists only the matching devices. The
  banner is cleared automatically once a device connects.
  (`SettingsScreen.focus_device_section`, `EEGMeditationApp._filter_mindwave`.)
- **Soft-error / diagnostics dialog.** New `crash_handler.report_soft_error(label, detail)`
  reuses the crash dialog with a non-fatal banner and a "Close" button
  (no `app.stop()`). Per-label cooldown (60 s) prevents one flaky
  subsystem from spamming the user. Wired to the BT-connect-failure path
  so users get a copy-pasteable technical report alongside the friendly
  retry overlay. New **Copy Diagnostics** button in Settings → Device
  builds a report on demand (paired BT list, current device, last
  connect error, signal/battery, audio config) and pops the same dialog
  bypassing the cooldown.

## [1.1.1] - 2026-04-12

### Fixed

- **Android**: wizard appearing on every app launch — fixed by using
  `app_storage_path()` for a stable DB path instead of `/sdcard` (which
  fails under scoped storage). Old DB auto-migrated on first run.
- **Android**: wizard TextInput keyboard not appearing — replaced inline
  TextInput with a Popup-based flow that gets proper keyboard focus.
- **Android**: help section showing "Help file not found" — `.txt` files
  were excluded from the APK build.
- **Bluetooth**: "connected but no EEG data" — added actionable error
  messages, stale data auto-stop, and root-cause guidance (battery).
- **Bluetooth**: EBUSY connection errors on session restart — keep BT
  connection alive between sessions to avoid RFCOMM channel conflicts.
- **Bluetooth**: `EINPROGRESS` (errno 115) on Linux RFCOMM connect —
  socket timeout set to 30s before `connect()`.
- Stale data from previous session tricking signal check — reset sample
  state in `NeuroSkyStream.start()`.
- "Bad file descriptor" error spam on normal stream stop.
- Overlay and alert messages truncated on small screens — label auto-sizes
  to fit multi-line content.

### Added

- **Smart time formatting** throughout the app: seconds if < 1 minute,
  minutes if < 1 hour, hours otherwise.
- **Time Shamatha ≥ 90** stat — tracks time at high meditation quality
  regardless of user-set threshold. Displayed in session summary and
  diary.
- **Stale data detection**: session auto-stops after 10 seconds with no
  new EEG packets.
- **Low battery warning** infrastructure (TGAM hardware doesn't actually
  send battery code 0x01, but parser handles it if present).
- `tools/bt_test.py` — minimal RFCOMM + ThinkGear parser for BT debugging
  without Kivy/threading overhead.
- `tools/ble_battery_scan.py` — BLE GATT service enumerator (MindWave
  Mobile 2's BLE is iOS-only in practice).

### Changed

- Connection timeout increased to 30 seconds (was 20s); signal wait
  reduced to 8 seconds (was 20s).
- App exit no longer explicitly closes BT socket — kernel handles cleanup
  while BlueZ may keep the ACL link for faster next-launch reconnect.
- Battery and connection troubleshooting docs updated in user manuals
  (EN + UA) and in-app help files. NiMH rechargeable batteries are
  recommended; Li-ion 1.5V rechargeable should be avoided (voltage
  regulator masks low charge).

## [1.1.0] - 2026-04-12

### Added

- CSV export for session data (per-tick metrics) with Android MediaStore
  integration for saving to Documents folder.
- Help & Troubleshooting section in Settings, loaded from external
  `help_{lang}.txt` files (EN + UA).
- Session auto-stop at 3-hour limit with alert.
- 50/60 Hz power line noise detection on raw EEG waveform.
- Android storage permission request at runtime.

### Changed

- Graph buffer expanded to 2 hours / 3 hours max session.
- Threshold max raised to 180; presets updated to 50/80/100/130/160.

### Fixed

- Android storage permissions on API 30+ (MediaStore for export).
- Various ruff lint issues across the project (407 fixes).
- Accordion styling and layout warnings.

## [1.0.3] - 2026-04

### Fixed

- Windows CI build: `KIVY_DOC=1` to prevent GL init on headless runner.
- Windows build: manually construct Kivy data paths instead of relying
  on broken PyInstaller hooks.

### Added

- Auto-connect BT overlay with retry/cancel buttons.
- Logarithmic volume curve for white-noise feedback.
- Workflow dispatch with per-platform build picker.

## [1.0.2] - 2026-04

### Fixed

- Linux CI build: use system Python for `socket.AF_BLUETOOTH` support.
- Windows build: collect Kivy subpackages individually.
- YAML syntax in release workflow.

## [1.0.1] - 2026-04

### Added

- Windows build in CI/CD pipeline.
- Disclaimer and scriptures.ru attribution.

### Fixed

- Windows build: disable UPX, add `pywin32`, bundle app data.
- Remove hardcoded paths for GitHub publication.

## [1.0.0] - 2026-03

Initial public release.

### Features

- NeuroSky MindWave Mobile 2 support (Bluetooth Classic RFCOMM) on
  Linux, Windows, macOS, and Android.
- Real-time meditation (Shamatha) scoring based on EEG band powers.
- Mock EEG source for demo and development.
- SQLite storage for sessions, metrics, user profiles, and settings.
- History view with GitHub-style calendar heatmap.
- Diary detail view with notes, tags, mood rating, graph tabs
  (metrics / raw EEG / frequency).
- Settings: threshold, audio feedback, timer, custom formulas,
  theme selector (4 palettes).
- Audio feedback: white noise (log volume), tingsha bell (sinking),
  chime (subtle distraction), warble (disconnect alert).
- Power line noise detection at 50/60 Hz.
- Multi-platform builds (PyInstaller for desktop, Buildozer for Android).

[1.4.0]: https://github.com/kirill-levenets/eeg-meditation-trainer/releases/tag/v1.4.0
[1.3.0]: https://github.com/kirill-levenets/eeg-meditation-trainer/releases/tag/v1.3.0
[1.2.0]: https://github.com/kirill-levenets/eeg-meditation-trainer/releases/tag/v1.2.0
[1.1.1]: https://github.com/kirill-levenets/eeg-meditation-trainer/releases/tag/v1.1.1
[1.1.0]: https://github.com/kirill-levenets/eeg-meditation-trainer/releases/tag/v1.1.0
[1.0.3]: https://github.com/kirill-levenets/eeg-meditation-trainer/releases/tag/v1.0.3
[1.0.2]: https://github.com/kirill-levenets/eeg-meditation-trainer/releases/tag/v1.0.2
[1.0.1]: https://github.com/kirill-levenets/eeg-meditation-trainer/releases/tag/v1.0.1
[1.0.0]: https://github.com/kirill-levenets/eeg-meditation-trainer/releases/tag/v1.0.0