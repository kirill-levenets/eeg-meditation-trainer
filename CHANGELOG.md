# Changelog

All notable changes to the EEG Meditation Trainer are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

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

- **Session Program** (issue #6): programmable per-segment sessions as an alternative to a single fixed-duration timer.
  - Settings → Timer now has a **Simple | Program** toggle. Simple = existing single-duration timer (unchanged). Program reveals a segment editor.
  - Each segment row specifies: duration (minutes), a **formula** (Shamatha, Meditation, NS Attention, NS Meditation, or any saved custom formula), a **target** level, and an **end-cue** sound (Chime or Warble).
  - **+ Add Segment**, per-row delete, total-duration readout. Named programs can be saved and reloaded; the saved-programs library is per-user.
  - The program's total duration becomes the session timer; the session auto-stops at the last segment's end via the existing timer-end path (gong plays).
  - At each segment boundary a transition chime plays; the active target, audio-driver formula, and "time above target" stat all follow the current segment.
  - A **stepped threshold line** is drawn on both the live session metrics graph and the diary metrics graph (each segment's target over its time range).
  - The program that ran is recorded per session (`sessions.session_program` column); the diary replays the stepped threshold line from that record.
  - Per-segment continuous feedback sound (replacing white noise) is modeled in v1 but inert — lands with issue #10.
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

[1.1.1]: https://github.com/kirill-levenets/eeg-meditation-trainer/releases/tag/v1.1.1
[1.1.0]: https://github.com/kirill-levenets/eeg-meditation-trainer/releases/tag/v1.1.0
[1.0.3]: https://github.com/kirill-levenets/eeg-meditation-trainer/releases/tag/v1.0.3
[1.0.2]: https://github.com/kirill-levenets/eeg-meditation-trainer/releases/tag/v1.0.2
[1.0.1]: https://github.com/kirill-levenets/eeg-meditation-trainer/releases/tag/v1.0.1
[1.0.0]: https://github.com/kirill-levenets/eeg-meditation-trainer/releases/tag/v1.0.0