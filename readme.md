# EEG Meditation Trainer

Cross-platform application for training Shamatha meditation using EEG neurofeedback from NeuroSky MindWave Mobile 2. Built with Python/Kivy for Android, Linux, Windows, and macOS.

Inspired by the [EEG meditation research and Vernihor formula](https://scriptures.ru/yoga/eeg_voprosy_i_otvety.htm) from scriptures.ru.

## Features

- **Real-time EEG visualization** — Live scrollable graph with Y-axis up to 200, horizontal grid lines every 20 units, real-time value labels, X-axis with relative and wall-clock timestamps, dashed threshold line, session start time display
- **Raw EEG data tab** — Oscillating EEG waveform (512Hz) + aggregated frequency band plots with adaptive Y-axis scaling; both graphs synchronized for linked scrolling and zooming
- **Scrollable graphs** — All graphs support touch drag/slide scrolling and pinch-to-zoom (Android) / mouse wheel zoom (desktop); chunked line rendering; vertical + horizontal grid lines
- **Meditation scoring** — Vernihor shamatha formula `(avg(ratio, 4) * 0.75 - 0.3) * 100` with sqrt-normalized relative band units and duplicate-sample deduplication; verified against original Windows app (MSE ~28); Distraction, Sinking, Subtle Distraction (short-window variance with warmup guard); native NeuroSky eSense Attention & Meditation
- **Session markers** — Place vertical markers on all graphs during a session to tag significant moments; markers stored in DB, displayed in diary previews, exported in CSV as a separate column
- **Multi-channel audio engine** — Ch1: selectable continuous feedback sound (Rain noise, built-in Tone drone, or a custom audio file — wav/mp3/ogg/flac/m4a); volume log-scales with the active metric. Ch2: tingsha bell for sinking alerts; Ch3: chime for subtle distraction; Ch4: warble for disconnect alert. Configurable audio control metric (Meditation, Shamatha, NS Meditation, NS Attention, Custom Formula slot 1/2/3; falls back to shamatha if the selected slot is invalid). Feedback source chosen in Settings → Audio; custom file path browsable via a file picker
- **Meditation timer** — Configurable duration (1-120 min) with presets, countdown display, auto-stop, custom end sound with file chooser and test button
- **Session Program** — Settings → Timer **Simple | Program** toggle: Program mode lets you define an ordered list of timed segments, each with its own formula (Shamatha, Meditation, NS Attention, NS Meditation, or any saved custom formula), target level, and end-cue sound (Chime or Warble). The program's total duration drives the session timer; a transition chime plays at each segment boundary and the target/audio-driver update live. The live graph highlights the currently-trained series and plots each segment's formula; a stepped threshold line tracks per-segment targets on both the live and diary graphs. Programs are saved by name (unique; re-saving the same name overwrites with a confirmation dialog; load and delete also confirm). The duration button on the Session screen shows **P** in program mode and opens a quick Programs picker to switch or inspect the active program — the loaded program's name is displayed. The program that ran is recorded per session so the diary can replay the stepped threshold. Each segment also has a **Feedback** picker (Default / Rain / Tone / Custom file); "Default" inherits the global Audio selection. The feedback source switches at each segment boundary, lock-safely.
- **Session duration picker on Live Session** — Dedicated duration button next to Start shows the active choice (`▼ 10 min` / `▼ Free`) and opens a modal preset picker (5 / 10 / 15 / 20 min / Free); current preset highlighted
- **State classification** — Stable Focus, Subtle Distraction, Gross Distraction, Sinking, Neutral
- **NeuroSky MindWave Mobile 2** — Bluetooth RFCOMM on Android (pyjnius) and Linux (Python socket); ThinkGear protocol parser; background reader thread; BT connection wait with status display; paired device scanning
- **Settings panel** — ThemedAccordion sections: User Profile, Timer, Device, Threshold (max 180), Audio, Display, Custom Formula, Theme selector; preset buttons under sliders; profile and timer inline; all persisted per user
- **Custom formula engine** — Up to 3 named custom formula slots, each a Python-style expression with band powers, combined/normalized bands, sqrt-relative bands, computed metrics, math functions, and windowed `avg(expr, N)`; AST-parsed with whitelist validation; save/load formula library per user; one slot drives the audio noise channel; all 3 share a Y-axis (scale 200); on-graph picker has a "Choose…" button per slot to assign from the library without opening Settings
- **Session diary** — Notes, tags, mood rating, CSV export with file save dialog, tabbed signal preview (Metrics / Raw EEG / Frequencies) with markers and threshold line; inline rename/delete moved to history list; session names include device type
- **Full signal storage** — Raw bands, computed metrics, native NeuroSky values, markers — all per-tick in SQLite with automatic schema migration
- **CSV export** — Full session data with file chooser dialog; includes marker column
- **Mock EEG simulation** — NeuroSky-compatible: band powers, 512Hz raw waveform, eSense values; state machine with smooth transitions
- **User profiles** — Multiple profiles with per-user sessions, settings, and formulas; last user persisted; diary disabled until user selected
- **Session guards** — Start blocked without user or device; stop dialog with Save/Discard/Cancel; timer auto-stop saves automatically
- **Navigation** — 3-tab bottom navigation (Session / History / Settings) with Material Design icons
- **First-run wizard** — 2-step setup on first launch (create profile, connect device or use demo mode); existing profiles surface in a picker so reinstalls don't lose history
- **Existing-user picker** — Wizard, first-run popup, and Settings → User Profile share one form: pick an existing profile or type a new name; duplicate names trigger an inline "Use existing 'X'" / "Change name" choice (DB enforces unique names)
- **Session end summary** — Post-session overlay with stats and quick notes field
- **History view** — Calendar heatmap (GitHub-style by avg shamatha) **or** 14-day bar chart, toggleable per user; tap a day in either to filter the session list
- **Theme system** — 4 themes (Dark Blue, Dark Green, Light Cream, Light Green) with live refresh; custom styled widgets with rounded corners
- **App icon** — Custom EEG brainwave icon and Android presplash
- **macOS support** — Native build via PyInstaller
- **Android storage** — Tries /sdcard/EEGMeditation, falls back to app-private storage if permission denied
- **Desktop DB location** — Linux `~/.local/share/EEGMeditation/`, Windows `%APPDATA%\EEGMeditation\`, macOS `~/Library/Application Support/EEGMeditation/`; one-time migration of any pre-existing DB at the old project-root / next-to-binary path
- **Manual Backup / Restore** — Settings → Data Backup writes a transaction-safe copy of your sessions (SQLite online backup API) to `Documents/EEGMeditation/` on Android (Telegram-/MTP-friendly) or a user-chosen location on desktop; Restore validates the file then force-restarts the app
- **Adaptive landscape layout** — fixed graph height when viewport is tall; scroll mode when short (graph would fall below dp(400)); controls live inside the scrollable body.
- **Multi-hour locked-screen sessions on Android** — foreground service + partial wake lock keeps the session running with the screen off; EEG compute and audio volume updates run on a daemon thread independent of Kivy's main loop.
- **Audio continues playing through screen lock on Android** — noise channel uses `MediaPlayer` (`USAGE_MEDIA` audio attributes) instead of SDL2 mixer so it survives screen lock.
- **Global crash handler** — in-app dialog with a pre-formatted crash report copied to clipboard.
- **Toggle bottom stats card** between live metrics and session aggregates.

## Documentation

- [User Manual (English)](docs/USER_MANUAL.md)
- [User Manual (Ukrainian)](docs/USER_MANUAL_UA.md)
- [Formula Comparison Tools](tools/COMPARISON.md)

## Project Structure

```
app/
├── ui/
│   ├── theme.py                # Colors, fonts, styled widgets, ThemedAccordion
│   ├── app_manager.py          # Main app, screen routing, session lifecycle
│   ├── live_session.py         # Session screen (metrics + raw EEG toggle)
│   ├── history_screen.py       # Calendar/14-Day toggle + session list
│   ├── settings_screen.py      # Accordion settings: User Profile, Timer, Device, Data Backup, …
│   ├── wizard_screen.py        # First-run setup wizard
│   ├── diary_screen.py         # Session detail view with graphs
│   ├── raw_eeg_screen.py       # ScrollableGraphWidget
│   ├── profile_screen.py       # Legacy user profile management (kept for now)
│   └── widgets/
│       └── user_picker.py      # Shared UserPickerForm (wizard, popup, settings)
├── assets/
│   ├── fonts/                   # Material Design Icons font
│   └── icons/                   # App icon (PNG/ICO/ICNS) + presplash
├── eeg/                    # EEG data sources
│   ├── mock_stream_v2.py       # Frequency-based EEG synthesis (active mock)
│   ├── neurosky_stream.py      # Real Bluetooth RFCOMM + ThinkGear parser
│   └── buffer.py               # Rolling average and variance buffers
├── metrics/                # Signal processing
│   ├── engine.py               # Shamatha formula, sinking, distraction, state classification
│   ├── custom_formula.py       # AST-parsed user formula engine with avg() support
│   └── noise_detector.py       # Power line noise (50/60Hz) detection
├── audio_feedback/
│   └── noise.py                # 4-channel audio: white noise, bell, chime, warble
├── session/
│   ├── manager.py              # Start/Pause/Resume/Stop state machine
│   ├── session_program.py      # SessionProgram headless model (segments, boundaries, threshold steps)
│   └── timer_state.py          # Headless countdown timer
├── storage/
│   ├── database.py             # SQLite: sessions, metrics, users, settings, CSV export
│   └── backup.py               # make_backup / validate_backup / restore_backup
├── config.py               # Sigmoid params, thresholds, app constants, Android+Desktop DB paths
├── crash_handler.py        # Global error UI; report_soft_error + pre-app error queue
└── logger.py               # Centralized logging

tools/
├── splitter.py             # BT stream splitter for simultaneous app comparison
├── replay.py               # Replay recorded .eeg sessions
├── run_comparison.sh       # One-script simultaneous comparison with Wine app
└── COMPARISON.md           # Comparison setup documentation
```

## Shamatha Formula

Vernihor formula (Windows variant, confirmed by data fitting):

```
score = max(0, avg(ratio, 4) * 0.75 - 0.3) * 100
```

Where:
- `ratio = (s_alpha1 + 0.8 * s_alpha2) / (s_beta2 + s_beta1 + 0.4 * s_theta + 0.08 * s_delta)`
- `s_X = sqrt(X / (delta + theta + alpha1 + alpha2 + beta1 + beta2))` — sqrt-normalized relative bands
- `avg(ratio, 4)` — rolling average over 4 unique NeuroSky samples (1Hz)
- Duplicate samples from 2Hz polling are skipped

## Setup (Desktop Development)

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run tests (236 tests)
python -m pytest tests/ -v

# Run application
python main.py

# Run with serial device (e.g. from splitter)
python main.py --serial /tmp/mindwave_b
```

## Building

### Linux

```bash
./build_linux.sh
# Output: dist/EEG_Meditation_Trainer/EEG_Meditation_Trainer
```

Requires Python 3.10+, `build-essential`, `pkg-config`.

### Android

```bash
./build_android.sh            # debug build
./build_android.sh release    # release build

# Deploy and run
buildozer android debug deploy run logcat
```

Requires Python 3.10+, JDK 17. First build downloads Android SDK/NDK (~1.5 GB).

System deps (Ubuntu/Debian):
```bash
sudo apt-get install -y build-essential git zip unzip autoconf libtool \
    pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev cmake \
    libffi-dev libssl-dev automake openjdk-17-jdk
```

### Windows

```bat
build_windows.bat
REM Output: dist\EEG_Meditation_Trainer\EEG_Meditation_Trainer.exe
```

Requires Python 3.10-3.12 from python.org.

### macOS

```bash
# macOS (CI only, or local with Homebrew SDL2)
# brew install sdl2 sdl2_image sdl2_mixer sdl2_ttf
# pyinstaller --windowed --icon app/assets/icons/icon.icns main.py
```

### CI

```bash
# CI: build single platform
gh workflow run release.yml -f platform=linux  # or windows, macos, android, all
```

## Configuration

All tunable parameters in `app/config.py`:

- **SigmoidConfig** — k and midpoint for each sigmoid normalization
- **MetricsConfig** — Cmax, rolling window size, threshold defaults, limits
- **AppConfig** — Update frequency (2Hz), graph window (5min), flush interval, audio settings

## Disclaimer

This software is provided for educational and personal exploration purposes only. It is **not a medical device** and must not be used for medical diagnosis, treatment, or any clinical purpose. EEG data from consumer-grade headsets (NeuroSky MindWave) is inherently noisy and should not be relied upon for health decisions. Use at your own risk.

## Tech Stack

- **Python 3.10-3.12** — Core language
- **Kivy 2.3** — Cross-platform UI + SoundLoader audio (Android, Linux, Windows, macOS)
- **SQLite** — Session, metrics, user profile storage
- **Buildozer** — Android packaging
- **PyInstaller** — Desktop executable packaging (Linux, Windows, macOS)