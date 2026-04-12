# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EEG Meditation Trainer — a Python/Kivy application for Shamatha meditation training using EEG neurofeedback from NeuroSky MindWave Mobile 2. Targets Android (via Buildozer), Linux, macOS and Windows (via PyInstaller) desktops.

## Commands

```bash
# Run application
python main.py

# Run with serial device (e.g. from mindwave-splitter)
python main.py --serial /tmp/mindwave_b

# Run all tests
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_engine.py -v

# Run a single test
python -m pytest tests/test_engine.py::TestMetricsEngine::test_compute_metrics -v

# Build Linux executable
./build_linux.sh              # output: dist/EEG_Meditation_Trainer/

# Build Android APK
./build_android.sh            # debug build
./build_android.sh release    # release build

# Build Windows executable (run on Windows)
build_windows.bat

# CI: build a single platform via workflow dispatch
gh workflow run release.yml -f platform=windows   # or linux, macos, android, all
```

## Architecture

**Entry point:** `main.py` → instantiates `EEGMeditationApp` (Kivy app with ScreenManager).

**Data flow:** EEG stream → MetricsEngine → SessionManager → UI screens + Database

### Core modules

- **EEG sources** (`app/eeg/`): `mock_stream_v2.py` (active mock with frequency-based synthesis, NeuroSky-compatible format), `mock_stream.py` (legacy mock), and `neurosky_stream.py` (real Bluetooth RFCOMM / pyserial, ThinkGear protocol). Both active sources produce 8 band powers + raw 512Hz waveform + eSense attention/meditation. Desktop BT falls back to PyBluez if `socket.AF_BLUETOOTH` is missing (common in PyInstaller bundles). Real stream tracks `_last_packet_time` for stale data detection and parses battery level (code 0x01, though TGAM hardware doesn't send it). BT connection kept alive between sessions to avoid RFCOMM/EBUSY issues; `reset_sample_state()` clears cached values for new sessions.
- **Metrics pipeline** (`app/metrics/engine.py`): Consumes raw band powers, computes meditation score, shamatha score, distraction, sinking, subtle distraction via sigmoid normalization. Uses rolling buffers from `app/eeg/buffer.py`. Power-line noise detection in `app/metrics/noise_detector.py`.
- **Custom formula engine** (`app/metrics/custom_formula.py`): AST-parsed user-defined expressions with whitelisted functions and `avg(expr, N)` windowed averages.
- **Session lifecycle** (`app/session/manager.py`): Start/Pause/Resume/Stop state machine. Coordinates EEG stream, metrics engine, audio feedback, and database flush. Tracks `time_shamatha_90` (time shamatha score >= 90, independent of user threshold).
- **Audio feedback** (`app/audio_feedback/noise.py`): 4-channel engine — white noise (log-scaled volume, MAX_VOLUME=0.3), tingsha bell (sinking), chime (subtle distraction), warble (disconnect alert). Uses Kivy SoundLoader with crossfaded WAV generation.
- **Storage** (`app/storage/database.py`): SQLite with automatic schema migration. Stores sessions (with `session_name`, `time_shamatha_90` columns), per-tick metrics timeseries, user profiles, per-user settings. CSV export support.

### UI layer (`app/ui/`)

**Navigation:** 3-tab bottom bar (Session / History / Settings) via `BottomNav` in `theme.py`. First-run wizard shown when no users exist.

- **Theme system** (`theme.py`): Centralized `C` color accessor (4 palettes: Dark Blue, Dark Green, Light Cream, Light Green), `F` font sizes, `S` spacing. `format_duration(seconds)` — smart time display (seconds if <1m, minutes if <1h, hours otherwise). Custom widgets: `StyledButton` (rounded, press feedback, MDI icons, outline mode), `Card`, `Divider`, `ThemedAccordion`, `PresetRow`, `BottomNav`. Theme changes notify listeners for live refresh.
- **Icons** (`app/assets/fonts/materialdesignicons-webfont.ttf`): Material Design Icons font, registered as `'Icons'`. `ICONS_AVAILABLE` flag for graceful fallback if font missing.
- **App icons** (`app/assets/icons/`): Generated EEG brainwave icon (512/192/128/48 PNG + ICO + ICNS), presplash for Android.
- **Session screen** (`live_session.py`): Metrics/Raw EEG toggle (inline, no separate screen), connection overlay with status + countdown, session end summary card with quick notes.
- **History screen** (`history_screen.py`): GitHub-style calendar heatmap colored by avg shamatha, day filter, session list with inline rename/delete.
- **Settings screen** (`settings_screen.py`): `ThemedAccordion` sections — User Profile, Timer, Device, Threshold (max 180), Audio, Display, Graph Metrics, Custom Formula, Theme selector. Preset buttons under sliders.
- **Wizard** (`wizard_screen.py`): 2-step first-run (name → device scan/skip). Hidden bottom nav during wizard. First-run name entry uses a Popup (not inline TextInput) because Kivy TextInput doesn't get keyboard focus on some Android devices when shown in the initial screen.
- **Diary detail** (`diary_screen.py`): Session stats, notes/tags/mood, graph tabs (metrics/raw/freq). Navigated from History, with back button.

**Configuration:** All tunable parameters (sigmoid curves, thresholds, update frequency, audio settings) are in `app/config.py` as dataclass-style config objects (`SIGMOID`, `METRICS`, `APP`).

### Diagnostic tools (`tools/`)

- `bt_test.py` — Minimal raw RFCOMM + ThinkGear parser for connection debugging. No Kivy, no threads. Usage: `python tools/bt_test.py [MAC]`
- `ble_battery_scan.py` — BLE GATT service enumerator (requires `bleak`). MindWave Mobile 2 doesn't expose BLE on Linux/Android (iOS only).

## Key Design Decisions

- Update loop runs at 2Hz (`AppConfig.UPDATE_FREQUENCY = 0.5s`), graph holds 600 points (5 min).
- Band powers are sqrt-normalized to relative units before metric formulas.
- NeuroSky Bluetooth uses pyjnius on Android, Python socket BTPROTO_RFCOMM on Linux (with PyBluez fallback), pyserial over virtual COM port on Windows. BT connection is kept alive between sessions (not closed on session stop) to avoid RFCOMM EBUSY and ThinkGear reinit failures. On app exit, the socket is NOT explicitly closed — the kernel handles cleanup while BlueZ may keep the ACL link for faster next-launch reconnect. Connection timeout is 30s, signal wait is 8s. Stale data (no new packets for 10s) auto-stops the session.
- Android DB path always uses `app_storage_path()` (not `/sdcard`) for stable path across launches. Old DB auto-migrated on first run. `KIVY_KEYBOARD_MODE=systemanddock` + `softinput_mode=below_target` set for Android TextInput stability.
- Database path resolves relative to executable (frozen) or project root (development).
- `conftest.py` only sets `sys.path` — no shared fixtures.
- Volume curve uses log scaling (`k=9`): rises fast initially, flattens near max (0.3). Prevents harsh noise at low scores.
- Theme colors accessed via `C.PRIMARY` etc. — `C` is a `_ColorAccessor` instance that reads from a mutable dict. `C.set_theme(name)` swaps palette and notifies listeners.
- Settings saved in `on_pause()` (Android) and `on_stop()` (desktop) so they persist when OS kills backgrounded app.
- Session names auto-generated as `"HH:MM - DeviceName"` to distinguish mock vs real.
- Windows CI build sets `KIVY_DOC=1` in the PyInstaller spec to prevent GL init on headless runner; Kivy data paths (`kivy_install/data/`, `kivy_install/modules/`) are constructed manually instead of importing `kivy.tools.packaging.pyinstaller_hooks`.
- Linux CI uses system Python (ubuntu-24.04) instead of `actions/setup-python` to get `socket.AF_BLUETOOTH` support.
- MDI icon font path resolution tries multiple candidates for cross-platform compat (standard, Android, fallback).

## Documentation Rules

**All documentation files must stay in sync with code changes.** When modifying features, UI, commands, architecture, or build process, update the relevant docs in the same commit or PR:

- `CLAUDE.md` — Architecture, commands, design decisions. Update when adding/removing modules, changing build process, or altering key patterns.
- `readme.md` — English README: features, project structure, build instructions, setup. Update when adding user-visible features or changing platforms/dependencies.
- `readme_ua.md` — Ukrainian README: mirror all `readme.md` changes in Ukrainian.
- `docs/USER_MANUAL.md` — English user manual. Update when UI flow, screens, or settings change.
- `docs/USER_MANUAL_UA.md` — Ukrainian user manual: mirror English manual changes.
- `app/assets/help/help_en.txt` — In-app help content (English). Update when features, connection flow, or settings change.
- `app/assets/help/help_ua.txt` — In-app help content (Ukrainian): mirror English help changes.
- `IMPROVEMENTS.md` — Roadmap. Mark items as completed when implemented; add new ideas as they emerge.
- `pyproject.toml` — Ruff config. Run `ruff check app/ tests/ main.py` before every commit; all checks must pass.
