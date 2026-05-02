# Changelog

All notable changes to the EEG Meditation Trainer are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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