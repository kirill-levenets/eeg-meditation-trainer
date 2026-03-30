# EEG Meditation Trainer

Cross-platform application for training Shamatha meditation using EEG neurofeedback from NeuroSky MindWave Mobile 2. Built with Python/Kivy for Android, Linux, and Windows.

Inspired by the [EEG meditation research and Vernihor formula](https://scriptures.ru/yoga/eeg_voprosy_i_otvety.htm) from scriptures.ru.

## Features

- **Real-time EEG visualization** — Live scrollable graph with Y-axis up to 200, horizontal grid lines every 20 units, real-time value labels, X-axis with relative and wall-clock timestamps, dashed threshold line, session start time display
- **Raw EEG data tab** — Oscillating EEG waveform (512Hz) + aggregated frequency band plots with adaptive Y-axis scaling; both graphs synchronized for linked scrolling and zooming
- **Scrollable graphs** — All graphs support touch drag/slide scrolling and pinch-to-zoom (Android) / mouse wheel zoom (desktop); chunked line rendering; vertical + horizontal grid lines
- **Meditation scoring** — Vernihor shamatha formula `(avg(ratio, 4) * 0.75 - 0.3) * 100` with sqrt-normalized relative band units and duplicate-sample deduplication; verified against original Windows app (MSE ~28); Distraction, Sinking, Subtle Distraction (short-window variance with warmup guard); native NeuroSky eSense Attention & Meditation
- **Session markers** — Place vertical markers on all graphs during a session to tag significant moments; markers stored in DB, displayed in diary previews, exported in CSV as a separate column
- **Multi-channel audio engine** — Ch1: gapless white noise (volume scales with configurable metric); Ch2: tingsha bell for sinking alerts; Ch3: chime for subtle distraction; Ch4: warble for disconnect alert. Configurable audio control metric (Meditation, Shamatha, NS Meditation, NS Attention, Custom Formula)
- **Meditation timer** — Configurable duration (1-120 min) with presets, countdown display, auto-stop, custom end sound with file chooser and test button
- **State classification** — Stable Focus, Subtle Distraction, Gross Distraction, Sinking, Neutral
- **NeuroSky MindWave Mobile 2** — Bluetooth RFCOMM on Android (pyjnius) and Linux (Python socket); ThinkGear protocol parser; background reader thread; BT connection wait with status display; paired device scanning
- **Settings panel** — Device status, mock/real switch, BT scan + select, threshold slider, audio metric picker (radio buttons), test audio, sinking/subtle distraction/disconnect alert toggles, line width slider, screen rotation, graph metric toggles, custom formula show/hide checkbox; all persisted per user
- **Custom formula engine** — Python-style expressions with band powers, combined/normalized bands, sqrt-relative bands, computed metrics, math functions, and windowed `avg(expr, N)`; AST-parsed with whitelist validation; save/load/export formula library per user
- **Session diary** — Notes, tags, mood rating, CSV export with file save dialog, delete/rename sessions, tabbed signal preview (Metrics / Raw EEG / Frequencies) with markers and threshold line
- **Full signal storage** — Raw bands, computed metrics, native NeuroSky values, markers — all per-tick in SQLite with automatic schema migration
- **CSV export** — Full session data with file chooser dialog; includes marker column
- **Mock EEG simulation** — NeuroSky-compatible: band powers, 512Hz raw waveform, eSense values; state machine with smooth transitions
- **User profiles** — Multiple profiles with per-user sessions, settings, and formulas; last user persisted; diary disabled until user selected
- **Session guards** — Start blocked without user or device; stop dialog with Save/Discard/Cancel; timer auto-stop saves automatically
- **Analytics** — Daily/weekly/monthly trends with step-20 grid lines, streak counter, storage usage display
- **Navigation** — Tab bar with hamburger toggle button; Profile tab first
- **Android storage** — Tries /sdcard/EEGMeditation, falls back to app-private storage if permission denied

## Documentation

- [User Manual (English)](docs/USER_MANUAL.md)
- [User Manual (Ukrainian)](docs/USER_MANUAL_UA.md)
- [Formula Comparison Tools](tools/COMPARISON.md)

## Project Structure

```
app/
├── ui/                     # Kivy screens and widgets
│   ├── app_manager.py          # Main app, ScreenManager, update loop, navigation
│   ├── live_session.py         # Session screen with graph, stats, markers, controls
│   ├── raw_eeg_screen.py       # ScrollableGraphWidget + Raw EEG screen
│   ├── profile_screen.py       # User profile management
│   ├── settings_screen.py      # All settings: device, audio, display, formula
│   ├── timer_screen.py         # Meditation timer with countdown
│   ├── diary_screen.py         # Session diary with preview graphs and CSV export
│   ├── analytics_screen.py     # Trend graphs and summary statistics
│   └── home_screen.py          # Home screen (alternative navigation, unused)
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
│   └── manager.py              # Start/Pause/Resume/Stop state machine
├── storage/
│   └── database.py             # SQLite: sessions, metrics, users, settings, CSV export
├── analytics/
│   └── aggregator.py           # Daily/weekly/monthly trend computation
├── config.py               # Sigmoid params, thresholds, app constants, Android storage
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

# Run tests (241 tests)
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

## Configuration

All tunable parameters in `app/config.py`:

- **SigmoidConfig** — k and midpoint for each sigmoid normalization
- **MetricsConfig** — Cmax, rolling window size, threshold defaults, limits
- **AppConfig** — Update frequency (2Hz), graph window (5min), flush interval, audio settings

## Disclaimer

This software is provided for educational and personal exploration purposes only. It is **not a medical device** and must not be used for medical diagnosis, treatment, or any clinical purpose. EEG data from consumer-grade headsets (NeuroSky MindWave) is inherently noisy and should not be relied upon for health decisions. Use at your own risk.

## Tech Stack

- **Python 3.11** — Core language
- **Kivy 2.3** — Cross-platform UI + SoundLoader audio
- **SQLite** — Session, metrics, user profile storage
- **Buildozer** — Android packaging
- **PyInstaller** — Desktop executable packaging