#!/usr/bin/env bash
# ============================================================
#  EEG Meditation Trainer - Android Build Script
#  Run on a Linux machine with Python 3.10-3.12, JDK 17
#  Produces: bin/eegmeditation-*-debug.apk
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/build_venv_android"
BUILD_TYPE="${1:-debug}"

echo "=== EEG Meditation Trainer - Android Build (${BUILD_TYPE}) ==="
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

# --- Check Java ---
if ! command -v java &>/dev/null; then
    echo "ERROR: Java not found. Install JDK 17:"
    echo "  sudo apt-get install -y openjdk-17-jdk"
    exit 1
fi

JAVA_VERSION=$(java -version 2>&1 | head -1)
echo "Using Java: ${JAVA_VERSION}"

# --- Check system deps ---
MISSING_DEPS=()
for pkg in git zip unzip autoconf libtool cmake; do
    if ! command -v "$pkg" &>/dev/null; then
        MISSING_DEPS+=("$pkg")
    fi
done

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo
    echo "ERROR: Missing system packages: ${MISSING_DEPS[*]}"
    echo "Install with:"
    echo "  sudo apt-get install -y build-essential git zip unzip autoconf libtool \\"
    echo "      pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev cmake \\"
    echo "      libffi-dev libssl-dev automake openjdk-17-jdk"
    exit 1
fi

# --- Create venv ---
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

echo "Activating virtual environment..."
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

echo "Installing buildozer and dependencies..."
pip install --upgrade pip
# setuptools<78 provides the distutils compat shim that buildozer 1.5.0
# imports (`from distutils.version import LooseVersion`). Python 3.12 removed
# stdlib distutils, so without this pin the build fails on import.
pip install 'setuptools<78' buildozer==1.5.0 cython==3.0.10

echo
echo "=== Building Android APK (${BUILD_TYPE}) ==="
echo
echo "NOTE: First build downloads Android SDK/NDK (~1.5 GB) and takes 15-30 min."
echo

if [ "$BUILD_TYPE" = "release" ]; then
    buildozer android release
else
    buildozer android debug
fi

if [ $? -ne 0 ]; then
    echo
    echo "BUILD FAILED - check errors above"
    echo "Try: buildozer android clean && $0 ${BUILD_TYPE}"
    exit 1
fi

echo
echo "=== Build complete! ==="
echo

APK=$(find "${SCRIPT_DIR}/bin" -name "*.apk" -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)
if [ -n "$APK" ]; then
    echo "APK: ${APK}"
    echo "Size: $(du -h "$APK" | cut -f1)"
    echo
    echo "Install on device:"
    echo "  adb install ${APK}"
    echo
    echo "Or deploy + run + logcat:"
    echo "  buildozer android deploy run logcat"
else
    echo "APK location: bin/"
fi

if [ "$BUILD_TYPE" = "release" ]; then
    echo
    echo "=== Release signing ==="
    echo "Sign the APK with your keystore:"
    echo "  jarsigner -verbose -sigalg SHA256withRSA -digestalg SHA-256 \\"
    echo "      -keystore ~/eeg-release.keystore ${APK:-bin/*.apk} eeg"
    echo "  zipalign -v 4 ${APK:-bin/*-unsigned.apk} bin/eegmeditation-release.apk"
fi
