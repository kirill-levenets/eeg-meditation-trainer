# Changelog

All notable changes to the EEG Meditation Trainer are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Session duration picker on the Live Session screen.** The Start button
  now shows the active duration (e.g. `Start · 10 min` or `Start · Free`)
  and carries a chevron on its right side. Tapping the chevron opens an
  inline row of presets (**5 / 10 / 15 / 20 min** or **Free**) directly
  above the controls; tapping a preset sets the timer and collapses the
  row. The main Start zone simply starts the session with whatever is set.
  Settings → Timer preset row aligned to [5, 10, 15, 20] for consistency.

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