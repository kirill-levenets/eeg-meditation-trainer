#!/usr/bin/env bash
# ============================================================
#  EEG Meditation Trainer - Linux Build Script
#  Run on a Linux machine with Python 3.10-3.12
#  Produces: dist/EEG_Meditation_Trainer/
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/build_venv"
DIST_DIR="${SCRIPT_DIR}/dist/EEG_Meditation_Trainer"

echo "=== EEG Meditation Trainer - Linux Build ==="
echo

# --- Check Python ---
PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3.10+ not found. Install python3 first."
    exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Using Python ${PY_VERSION} (${PYTHON})"

# --- Check system deps ---
MISSING_DEPS=()
for pkg in gcc make pkg-config; do
    if ! command -v "$pkg" &>/dev/null; then
        MISSING_DEPS+=("$pkg")
    fi
done

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo "WARNING: Missing system packages: ${MISSING_DEPS[*]}"
    echo "Install with: sudo apt-get install -y build-essential pkg-config"
    echo "         or:  sudo dnf install -y gcc make pkgconfig"
    echo
fi

# --- Create venv ---
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

echo "Activating virtual environment..."
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

echo "Installing dependencies..."
pip install --upgrade pip
pip install kivy==2.3.0 pillow==10.4.0
pip install pyinstaller==6.11.1

echo
echo "=== Building executable ==="
echo

pyinstaller \
    --name "EEG_Meditation_Trainer" \
    --noconfirm \
    --clean \
    --onedir \
    --noconsole \
    --strip \
    --exclude-module tkinter \
    --exclude-module _tkinter \
    --exclude-module unittest \
    --exclude-module pytest \
    --hidden-import app \
    --hidden-import app.ui \
    --hidden-import app.ui.app_manager \
    --hidden-import app.ui.live_session \
    --hidden-import app.ui.raw_eeg_screen \
    --hidden-import app.ui.settings_screen \
    --hidden-import app.ui.timer_screen \
    --hidden-import app.ui.diary_screen \
    --hidden-import app.ui.analytics_screen \
    --hidden-import app.ui.profile_screen \
    --hidden-import app.eeg \
    --hidden-import app.eeg.mock_stream \
    --hidden-import app.eeg.mock_stream_v2 \
    --hidden-import app.eeg.buffer \
    --hidden-import app.metrics \
    --hidden-import app.metrics.engine \
    --hidden-import app.audio_feedback \
    --hidden-import app.audio_feedback.noise \
    --hidden-import app.session \
    --hidden-import app.session.manager \
    --hidden-import app.storage \
    --hidden-import app.storage.database \
    --hidden-import app.analytics \
    --hidden-import app.analytics.aggregator \
    --hidden-import app.config \
    --hidden-import app.logger \
    --hidden-import kivy.core.window.window_sdl2 \
    --hidden-import kivy.core.text.text_sdl2 \
    --hidden-import kivy.core.image.img_sdl2 \
    --hidden-import kivy.core.audio.audio_sdl2 \
    --hidden-import kivy.core.clipboard.clipboard_sdl2 \
    --hidden-import kivy.graphics.opengl \
    --hidden-import kivy.graphics.opengl_utils \
    "${SCRIPT_DIR}/main.py"

if [ $? -ne 0 ]; then
    echo
    echo "BUILD FAILED - check errors above"
    exit 1
fi

echo
echo "=== Build complete! ==="
echo "Output: ${DIST_DIR}/"
echo "Run:    ${DIST_DIR}/EEG_Meditation_Trainer"
echo
echo "To distribute: tar czf EEG_Meditation_Trainer_linux.tar.gz -C dist EEG_Meditation_Trainer"
