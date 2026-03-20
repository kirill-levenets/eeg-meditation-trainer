# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EEG Meditation Trainer — a Python/Kivy application for Shamatha meditation training using EEG neurofeedback from NeuroSky MindWave Mobile 2. Targets Android (via Buildozer), Linux and Windows (via PyInstaller) desktops.

## Commands

```bash
# Run application
python main.py

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
```

## Architecture

**Entry point:** `main.py` → instantiates `EEGMeditationApp` (Kivy ScreenManager app).

**Data flow:** EEG stream → MetricsEngine → SessionManager → UI screens + Database

- **EEG sources** (`app/eeg/`): `mock_stream_v2.py` (active mock with frequency-based synthesis, NeuroSky-compatible format) and `neurosky_stream.py` (real Bluetooth RFCOMM, ThinkGear protocol). Both produce 8 band powers + raw 512Hz waveform + eSense attention/meditation.
- **Metrics pipeline** (`app/metrics/engine.py`): Consumes raw band powers, computes meditation score, shamatha score, distraction, sinking, subtle distraction via sigmoid normalization. Uses rolling buffers from `app/eeg/buffer.py`.
- **Custom formula engine** (`app/metrics/custom_formula.py`): AST-parsed user-defined expressions with whitelisted functions and `avg(expr, N)` windowed averages.
- **Session lifecycle** (`app/session/manager.py`): Start/Pause/Resume/Stop state machine. Coordinates EEG stream, metrics engine, audio feedback, and database flush.
- **Audio feedback** (`app/audio_feedback/noise.py`): 4-channel engine — white noise (meditation-scaled volume), tingsha bell (sinking), chime (subtle distraction), warble (disconnect alert). Uses Kivy SoundLoader with crossfaded WAV generation.
- **Storage** (`app/storage/database.py`): SQLite with automatic schema migration. Stores sessions, per-tick metrics timeseries, user profiles, per-user settings. CSV export support.
- **UI** (`app/ui/`): Kivy screens managed by `app_manager.py`. Live session graph with scrollable 5-min window, raw EEG oscilloscope, settings panel, timer, diary with signal preview tabs, analytics trends.

**Configuration:** All tunable parameters (sigmoid curves, thresholds, update frequency, audio settings) are in `app/config.py` as dataclass-style config objects (`SIGMOID`, `METRICS`, `APP`).

## Key Design Decisions

- Update loop runs at 2Hz (`AppConfig.UPDATE_FREQUENCY = 0.5s`), graph holds 600 points (5 min).
- Band powers are sqrt-normalized to relative units before metric formulas.
- NeuroSky Bluetooth uses pyjnius on Android, Python socket BTPROTO_RFCOMM on Linux desktop.
- Database path resolves relative to executable (frozen) or project root (development).
- `conftest.py` only sets `sys.path` — no shared fixtures.