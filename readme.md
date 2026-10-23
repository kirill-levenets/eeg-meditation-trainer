# EEG Meditation Trainer

Cross-platform application for training Shamatha meditation with EEG neurofeedback from a NeuroSky MindWave Mobile 2.
Built with Python/Kivy for Android, Linux, Windows and macOS.

Inspired by the [EEG meditation research and Vernihor formula](https://scriptures.ru/yoga/eeg_voprosy_i_otvety.htm) from scriptures.ru.

## Features

- **Real-time EEG visualization** — a scrollable graph with the Y-axis up to 200, horizontal grid lines every 20 and vertical ones on the time axis, live value labels, and elapsed and wall-clock time on the X-axis;
  a dashed threshold line steps where the threshold changed (a moved slider, a program's segments), live and in History.
- **Raw EEG view** — the Session screen's Metrics / Raw EEG toggle shows the 512 Hz raw waveform and a frequency-band chart with an adaptive Y-axis.
- **Scrollable graphs** — drag to scroll, pinch (Android) or mouse wheel (desktop) to zoom, and the graphs of one screen zoom together;
  one tap fits the whole session (the Session screen's as it grows), another opens a graph full screen;
  a graph's buttons sit in its corners, its margins take only what its labels need, and time labels read hours past an hour.
- **Meditation scoring** — the Vernihor shamatha formula ([below](#shamatha-formula)), matched against the original Windows app (MSE ~28);
  Distraction and Sinking ported from the original Vernihor app (alpha-gated, shamatha-modulated; Sinking also gamma-damped);
  Subtle Distraction (short-window variance with a warm-up guard); NeuroSky's own eSense Attention and Meditation.
- **State classification** — Stable Focus, Subtle Distraction, Gross Distraction, Sinking, Neutral.
- **Session markers** — **Mark** puts a vertical marker on all graphs; markers are saved with the session, shown on its graphs in History and exported as a CSV column.
- **Multi-channel audio** — a below-threshold feedback sound (Off, Rain, Tone, or your own wav/mp3/ogg/flac/m4a file) whose volume log-scales with the scored metric;
  a reward sound that fades in above the threshold (Off, Rain, Tone, Crickets — a soft chirp about every 10 s — or a file);
  a tingsha bell for sinking, a chime for subtle distraction and a warble for a lost connection.
  Settings → Audio picks the sounds; Settings → Threshold picks the metric that drives the feedback and reward sounds:
  Shamatha, NS Meditation, NS Attention or a Custom Formula slot (1/2/3; an invalid slot falls back to Shamatha).
- **Scoring against the threshold in force** — moving the threshold during a session moves the feedback sound, Time Above Threshold, Longest Streak and the SHAMATHA badge together, once the slider stays put for half a second;
  every recorded tick stores the metric it was scored on, its value and the threshold in force (also in CSV exports), and the session cards list the thresholds in order ("70 › 85").
- **Meditation timer** — 1-120 min with presets, on/off, countdown, auto-stop, and an end sound (default bell or your own file) with a test button.
  The duration button next to Start shows the choice ("10m", "1h", "∞" for Free, "P" for a program) and opens a picker: 5, 10, 15, 20, 30 min, 1 h, 1 h 30 min, 2 h, Free, or a saved program.
- **Session Program** — Settings → Timer / Program has a **Simple | Program** toggle; a program is an ordered list of timed segments.
  Each segment has its own formula (Shamatha, Meditation, NS Attention, NS Meditation or a saved custom formula), target, end cue (Chime or Warble) and feedback sound (Default, the Audio setting; Rain; Tone; a file).
  The program's total duration runs the session timer; at each boundary the segment's end cue plays and the target, scored metric and feedback sound switch, also with the screen locked.
  The live graph shows each segment's formula and marks the one in training; a stepped threshold line follows the targets live and in History, which keeps the program each session ran.
  Programs are saved under unique names; overwriting, loading or deleting one asks first.
- **NeuroSky MindWave Mobile 2** — Bluetooth Classic RFCOMM on Android (pyjnius) and Linux (Python socket), the headset's COM port on Windows (pyserial), or a serial device given with `--serial`;
  a ThinkGear parser (8 band powers, attention, meditation, signal quality, 512 Hz raw wave) on a background reader thread that reconnects after a read error.
  At Start the app waits for the connection and the first data and shows its status;
  Settings → Device lists the paired headsets, marks the one in use and the connected one, and lets you name each.
- **Settings panel** — accordion sections: User Profile, Timer / Program, Device, Data Backup, Threshold (20-180), Audio, Display, Custom Formula, Theme, Developer Tools, Help & Troubleshooting;
  preset buttons under the sliders; settings are saved per profile.
  Help & Troubleshooting shows in Ukrainian on a phone set to Ukrainian, English otherwise.
  Display holds the text size (Normal / Large / Larger), the scored line's colours (mono or one of five gradients), line width, screen rotation and the marker hotkey.
- **Custom formula engine** — 3 named slots, each with a name, an expression, Apply, Save and a status line;
  an expression is Python-style over band powers, combined, normalized and sqrt-relative bands, computed metrics, math functions and windowed `avg(expr, N)`, AST-parsed against a whitelist;
  a formula library per profile; any slot can drive the audio; all 3 share one Y-axis (scale 200);
  the graph's series picker has a "Choose…" button per slot to assign a library formula without opening Settings.
- **Session detail** — notes, tags and mood (saved with Save Notes, or when you leave the session) and CSV export;
  a whole-session band power table and tabbed graphs (Metrics / Raw EEG / Frequencies) with markers and the threshold line;
  a Try another threshold slider (one per segment for a program) recalculates time above threshold and the longest streak, view only.
  A session is named after its start time and headset; rename and delete are in the History list.
- **Full signal storage** — raw bands, computed metrics, native NeuroSky values and markers, per tick, in SQLite with automatic schema migration; a running session is saved every minute.
- **CSV export** — a session's full data with a marker column: on desktop to a folder you pick, on Android to `Documents/EEGMeditation/`; History's select mode exports several sessions as one ZIP.
- **Mock EEG simulation** — NeuroSky-compatible band powers from a state machine (relaxed, focused, drowsy, distracted, deep calm) with smooth transitions, a 128 Hz synthesized raw waveform and eSense values.
- **User profiles** — sessions, settings and formulas per profile; the last profile opens at start, and the app can't be used without one.
- **Session guards** — Start needs a profile and, with no headset selected, scans the paired ones first; every ending (Stop, timer, lost signal) saves the session.
- **Navigation** — 3-tab bottom navigation (Session / History / Settings) with Material Design icons.
- **First run** — create a profile or pick an existing one, so a restored database doesn't lose history;
  a single paired MindWave is then selected automatically, several open Settings → Device to pick one, and with none the app runs on simulated EEG (demo mode).
- **Existing-user picker** — the first-run popup and Settings → User Profile share one form: pick an existing profile or type a new name;
  a duplicate name offers "Use existing 'X'" or "Change name" inline (the DB enforces unique names).
- **Session end summary** — an end card with the stats and a notes field, which can also delete the session after a confirmation.
- **History view** — a calendar heatmap (GitHub-style, by average shamatha) or a 14-day bar chart (each profile keeps its choice);
  arrows or a sideways swipe page it back in time, as far as the first session, and a tap on the dates returns to today;
  tap a day in either to filter the session list.
  A totals table under the chart sums the day, week and month around today or the tapped day, and all time: total time, time on target and best streak.
  A chevron folds the chart and the totals away so the list gets the screen.
  Each session row shows its date and start time, the metric it was scored on with its average, the duration, the longest streak and the first line of its notes.
  Select mode exports or deletes several sessions at once.
- **Theme system** — 4 themes (Dark Blue, Dark Green, Light Cream, Light Green) with live refresh; custom styled widgets with rounded corners.
- **App icon** — custom EEG brainwave icon and Android presplash.
- **Database location** — Android app-private storage; Linux `~/.local/share/EEGMeditation/` (or `$XDG_DATA_HOME/EEGMeditation/`), Windows `%APPDATA%\EEGMeditation\`, macOS `~/Library/Application Support/EEGMeditation/`;
  a database at an older location (`/sdcard/EEGMeditation` on Android, the project root or next to the binary on desktop) is copied in once.
- **Manual Backup / Restore** — Settings → Data Backup writes a transaction-safe copy of the database (SQLite online backup API) to a file you choose in Android's save dialog or a desktop file dialog;
  Restore validates the file, replaces the database and closes the app for a relaunch.
- **Adaptive landscape layout** — fixed graph height when the viewport is tall, scroll mode when it is short (the graph would fall below dp(400)); the controls sit inside the scrollable body.
- **Multi-hour locked-screen sessions on Android** — a foreground service and a partial wake lock keep the session running with the screen off;
  EEG compute and audio volume updates run on a daemon thread independent of Kivy's main loop, and audio plays through the lock as Android `MediaPlayer`s (`USAGE_MEDIA`) instead of the SDL2 mixer.
  On phones whose maker closes background apps anyway (Huawei, Xiaomi, Samsung, …), the app explains at first start what to allow (battery optimisation; Huawei's App launch) and keeps the buttons in Settings → Device.
- **Global crash handler** — an in-app dialog with a pre-formatted crash report copied to the clipboard.
- **Bottom stats toggle** — the stats card switches between live metrics and session aggregates.

## Documentation

- [User Manual (English)](docs/USER_MANUAL.md), [User Manual (Ukrainian)](docs/USER_MANUAL_UA.md)
- [Architecture](docs/architecture/README.md): how each subsystem works and why
- [Android release signing](docs/ANDROID_SIGNING.md)
- [Formula comparison tools](tools/COMPARISON.md), [EEG stream splitter](tools/SPLITTER.md)
- [Changelog](CHANGELOG.md), [Contributing](CONTRIBUTING.md)

## Project Structure

```
main.py              # Entry point; --serial PATH reads a serial device instead of Bluetooth
app/
├── config.py        # Tunable parameters (SIGMOID, METRICS, APP), DB paths
├── eeg/             # Headset streams (Bluetooth, serial, mock), ThinkGear parser, bands
├── metrics/         # MetricsEngine, custom formulas, noise detection
├── session/         # Session state machine, 2 Hz tick, checkpoints, scoring, programs
├── audio_feedback/  # AudioEngine: feedback, alerts, timer gong
├── storage/         # SQLite, backup and restore, file and Android storage helpers
├── settings/        # Per-profile settings registry
├── ui/              # The app (app_manager.py), screens, theme, widgets
└── assets/          # Icon font, in-app help, app icon and presplash
android_src/         # The session's Android foreground service (Java)
docs/                # User manuals, architecture, Android release signing
tests/               # pytest suite
tools/               # Bluetooth diagnostics, stream splitter, replay, side-by-side comparison
```

Module by module: `CLAUDE.md`'s module map and [docs/architecture](docs/architecture/README.md).

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

Distraction, Sinking and Subtle Distraction are in [metrics-scoring.md](docs/architecture/metrics-scoring.md).

## Setup (Desktop Development)

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies: requirements.txt runs the app, requirements_dev.txt adds the tests and build tools
pip install -r requirements_dev.txt

# Run tests (skips the ones marked slow)
python -m pytest tests/ -v

# Run all tests including the slow ones: before every push
python -m pytest tests/ --run-slow

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
# Package: tar czf EEG_Meditation_Trainer_linux.tar.gz -C dist EEG_Meditation_Trainer
```

Requires Python 3.10-3.12, `build-essential`, `pkg-config`.
The script creates `build_venv`, installs the pinned Kivy, Pillow and PyInstaller, and builds with PyInstaller.

### Android

```bash
./build_android.sh            # debug build: bin/eegmeditation-*-debug.apk
./build_android.sh release    # release build

# Install, or deploy and run with the log (buildozer is in build_venv_android, which the script creates)
adb install bin/eegmeditation-*-debug.apk
buildozer android deploy run logcat
```

Requires Python 3.10-3.12 and JDK 17 (check with `java -version`).
The first build downloads the Android SDK/NDK (~1.5 GB) and takes 15-30 min.
To use an SDK/NDK you already have, set `android.sdk_path` and `android.ndk_path` in `buildozer.spec`.
After a build error, run `buildozer android clean` and build again.
Release signing in CI: [docs/ANDROID_SIGNING.md](docs/ANDROID_SIGNING.md).

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

Requires Windows 10/11 and Python 3.10-3.12 from [python.org](https://www.python.org/downloads/), on `PATH` (`python --version` must work).
The script deletes `build\` and `dist\`, creates `build_venv`, installs `requirements_windows.txt`, and runs `python -m PyInstaller eeg_meditation.spec --noconfirm`.
To distribute, zip the whole `dist\EEG_Meditation_Trainer\` folder: the exe runs from it without a Python install.

- **Missing DLLs**: check that `kivy_deps.sdl2` and `kivy_deps.glew` are installed; the spec bundles their binaries.
- **Black screen at start**: set `console=True` in `eeg_meditation.spec` to see the errors.

### macOS

macOS builds run in CI (the `build-macos` job in `.github/workflows/release.yml`); a local build follows that job:

```bash
brew install sdl2 sdl2_image sdl2_mixer sdl2_ttf pkg-config
pip install kivy==2.3.0 pillow==10.4.0 pyinstaller==6.11.1
pyinstaller --name "EEG_Meditation_Trainer" --noconfirm --clean --onedir --windowed \
    --icon app/assets/icons/icon.icns main.py
# Output: dist/EEG_Meditation_Trainer/
```

Add the job's `--hidden-import` flags, then copy Kivy's `data` and `modules` into the bundle as its next step does.
Requires Python 3.10-3.12, macOS 13+.

### CI

```bash
# CI: build single platform
gh workflow run release.yml -f platform=linux  # or windows, macos, android, all
```

Pushing a `v*` tag builds all four platforms and publishes a GitHub release with their packages.

## Configuration

All tunable parameters in `app/config.py`:

- **SigmoidConfig** — k and midpoint of the subtle-distraction sigmoid
- **MetricsConfig** — Cmax, rolling window size, threshold default, limits
- **AppConfig** — update frequency (2 Hz), graph window and session limit (3 h), flush interval, audio and alert settings, DB path

## Disclaimer

This software is provided for educational and personal exploration purposes only.
It is **not a medical device** and must not be used for medical diagnosis, treatment, or any clinical purpose.
EEG data from consumer-grade headsets (NeuroSky MindWave) is inherently noisy and should not be relied upon for health decisions.
Use at your own risk.

## Tech Stack

- **Python 3.10-3.12** — Core language
- **Kivy 2.3.0** — Cross-platform UI; audio through SoundLoader on desktop and Android's `MediaPlayer` on Android
- **SQLite** — Session, metrics, user profile storage
- **Buildozer** — Android packaging
- **PyInstaller** — Desktop executable packaging (Linux, Windows, macOS)
