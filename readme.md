# EEG Meditation Trainer

Mobile application for training Shamatha meditation using EEG neurofeedback. Built with Python/Kivy for Android.

## Features

- **Real-time EEG visualization** — Live scrollable multi-line graph showing meditation metrics at 2 Hz with 5-minute buffer
- **Raw EEG data tab** — Separate screen plotting all 8 EEG sub-bands and aggregated frequency bands in real-time
- **Scrollable graphs** — All graphs support time-scrolling through the full 5-minute data window via slider
- **Meditation scoring** — Calmness, Shamatha score, Distraction, and Sinking detection
- **Audio neurofeedback** — White noise generated with stdlib (no numpy), played via Kivy SoundLoader (Android-compatible), volume fades to silence as meditation deepens
- **State classification** — Stable Focus, Subtle Distraction, Gross Distraction, Sinking
- **Session diary** — Notes, tags, mood rating, and CSV export for each session
- **Full signal storage** — Raw EEG bands, computed metrics, frequencies, stability, and calmness all stored per-tick in SQLite
- **CSV export** — Export any session's full signal data (raw + computed) to CSV from the diary screen
- **User profiles** — Create named user profiles, switch between users; diary and sessions are filtered per-user
- **Analytics** — Daily/weekly/monthly trends, streak counter, progress tracking
- **SQLite storage** — Sessions, metrics timeseries, and user profiles with automatic schema migration

## Project Structure

```
app/
├── ui/                 # Kivy screens, widgets, and ScreenManager
│   ├── app_manager.py      # Main app with ScreenManager and update loop
│   ├── live_session.py      # Live session screen with scrollable graph and controls
│   ├── raw_eeg_screen.py    # Raw EEG data tab with sub-band and frequency band plots
│   ├── profile_screen.py    # User profile management and user switcher
│   ├── settings_screen.py   # Threshold slider, graph toggles
│   ├── diary_screen.py      # Session list, notes, mood rating, CSV export
│   └── analytics_screen.py  # Trend graphs and summary stats
├── eeg/                # EEG data source
│   ├── mock_stream.py       # Simulated EEG for development
│   └── buffer.py            # Rolling average and variance buffers
├── metrics/            # Signal processing and state formulas
│   └── engine.py            # Full metrics pipeline with sigmoid normalization
├── audio_feedback/     # White noise generator
│   └── noise.py             # Realtime white noise via sounddevice with dynamic volume
├── session/            # Session lifecycle
│   └── manager.py           # Start/Pause/Resume/Stop state machine
├── storage/            # Database
│   └── database.py          # SQLite schema, CRUD, user profiles, CSV export
├── analytics/          # Data aggregation
│   └── aggregator.py        # Daily/weekly/monthly trend computation
├── config.py           # Sigmoid params, thresholds, app constants
└── logger.py           # Centralized logging
```

## Metrics Computed

| Metric | Formula | Range |
|--------|---------|-------|
| Meditation Score | `clamp(200 * calmness / Cmax)` | 0–200 |
| Sinking | `sigmoid((theta+delta) / (alpha+beta+1))` | 0–100 |
| Distraction | `sigmoid((beta+gamma) / (alpha+1))` | 0–100 |
| Subtle Distraction | `sigmoid(stability / stability_max)` when score > threshold | 0–100 |
| Shamatha Score | `sigmoid(calmness*0.4 + clarity*0.3 + stability_factor*0.3)` | 0–100 |

## Setup (Desktop Development)

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run tests
python -m pytest tests/ -v

# Run application
python main.py
```

## Building Android APK

### Prerequisites

Install system dependencies (Ubuntu/Debian):

```bash
sudo apt-get update
sudo apt-get install -y \
    python3-pip \
    build-essential \
    git \
    zip \
    unzip \
    openjdk-17-jdk \
    autoconf \
    libtool \
    pkg-config \
    zlib1g-dev \
    libncurses5-dev \
    libncursesw5-dev \
    libtinfo5 \
    cmake \
    libffi-dev \
    libssl-dev \
    automake
```

### Install Buildozer

```bash
pip install buildozer cython
```

### Build Debug APK

```bash
# First build (downloads Android SDK/NDK automatically, takes 15-30 min)
buildozer android debug

# APK output location:
# bin/eegmeditation-1.0.0-arm64-v8a_armeabi-v7a-debug.apk
```

### Build Release APK

```bash
# Generate a keystore (one time)
keytool -genkey -v -keystore ~/eeg-release.keystore \
    -alias eeg -keyalg RSA -keysize 2048 -validity 10000

# Build release
buildozer android release

# Sign the APK
jarsigner -verbose -sigalg SHA256withRSA -digestalg SHA-256 \
    -keystore ~/eeg-release.keystore \
    bin/eegmeditation-1.0.0-arm64-v8a_armeabi-v7a-release-unsigned.apk eeg

# Align the APK
zipalign -v 4 \
    bin/eegmeditation-1.0.0-arm64-v8a_armeabi-v7a-release-unsigned.apk \
    bin/eegmeditation-release.apk
```

### Install on Device

```bash
# Via USB (enable USB debugging on device)
adb install bin/eegmeditation-1.0.0-arm64-v8a_armeabi-v7a-debug.apk

# Or via buildozer
buildozer android deploy run logcat
```

### Troubleshooting Build

- **Java version**: Requires JDK 17. Check with `java -version`
- **SDK/NDK**: Buildozer auto-downloads. Set `ANDROIDSDK` and `ANDROIDNDK` env vars if using existing install
- **First build slow**: SDK/NDK download + compilation takes 15-30 minutes
- **Build errors**: Run `buildozer android clean` then rebuild
- **Logs**: Check `buildozer android deploy run logcat` for runtime errors

## Configuration

All tunable parameters are in `app/config.py`:

- **SigmoidConfig** — `k` and `midpoint` for each sigmoid normalization
- **MetricsConfig** — Cmax, rolling window size, threshold defaults, limits
- **AppConfig** — Update frequency, graph window, flush interval, audio settings

## Tech Stack

- **Python 3.x** — Core language
- **Kivy 2.3** — Cross-platform UI framework
- **SQLite** — Session, metrics, and user profile storage
- **Buildozer** — Android packaging tool
