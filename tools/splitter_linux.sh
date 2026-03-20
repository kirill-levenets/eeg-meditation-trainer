#!/usr/bin/env bash
# ============================================================
#  EEG Stream Splitter — Linux Setup & Run
#  Finds paired MindWave, launches splitter with two PTY outputs
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SPLITTER="${SCRIPT_DIR}/splitter.py"

echo "=== EEG Stream Splitter — Linux ==="
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
echo "Python: $($PYTHON --version)"

# --- Check Bluetooth ---
if ! command -v bluetoothctl &>/dev/null; then
    echo "ERROR: bluetoothctl not found."
    echo "Install with: sudo apt-get install -y bluez"
    exit 1
fi

# Check bluetooth service is running
if ! systemctl is-active --quiet bluetooth 2>/dev/null; then
    echo "WARNING: bluetooth service is not running."
    echo "Start with: sudo systemctl start bluetooth"
    echo
fi

# --- Find MindWave in paired devices ---
echo "Scanning paired Bluetooth devices..."
echo

PAIRED_OUTPUT=""
for cmd in "bluetoothctl paired-devices" "bluetoothctl devices Paired"; do
    PAIRED_OUTPUT=$($cmd 2>/dev/null || true)
    if [ -n "$PAIRED_OUTPUT" ]; then
        break
    fi
done

if [ -z "$PAIRED_OUTPUT" ]; then
    echo "ERROR: No paired Bluetooth devices found."
    echo
    echo "Pair your MindWave first:"
    echo "  1. Turn on MindWave"
    echo "  2. Run: bluetoothctl"
    echo "  3. In bluetoothctl: scan on"
    echo "  4. Wait for MindWave MAC to appear"
    echo "  5. pair AA:BB:CC:DD:EE:FF"
    echo "  6. trust AA:BB:CC:DD:EE:FF"
    echo "  7. exit"
    echo
    echo "Then re-run this script."
    exit 1
fi

# Display paired devices and find MindWave
echo "Paired devices:"
DEVICE_ADDR=""
DEVICE_NAME=""
INDEX=0
declare -a ADDRS=()
declare -a NAMES=()

while IFS= read -r line; do
    PARTS=($line)
    if [ "${PARTS[0]:-}" = "Device" ] && [ ${#PARTS[@]} -ge 3 ]; then
        ADDR="${PARTS[1]}"
        NAME="${PARTS[*]:2}"
        INDEX=$((INDEX + 1))
        ADDRS+=("$ADDR")
        NAMES+=("$NAME")
        echo "  [$INDEX] $NAME ($ADDR)"

        # Auto-detect MindWave
        if echo "$NAME" | grep -qi "mindwave\|neurosky\|mindset"; then
            DEVICE_ADDR="$ADDR"
            DEVICE_NAME="$NAME"
        fi
    fi
done <<< "$PAIRED_OUTPUT"

echo

if [ $INDEX -eq 0 ]; then
    echo "ERROR: No paired devices found. Pair your MindWave first."
    exit 1
fi

if [ -n "$DEVICE_ADDR" ]; then
    echo "Auto-detected MindWave: $DEVICE_NAME ($DEVICE_ADDR)"
    read -rp "Use this device? [Y/n] " CONFIRM
    if [[ "$CONFIRM" =~ ^[nN] ]]; then
        DEVICE_ADDR=""
    fi
fi

if [ -z "$DEVICE_ADDR" ]; then
    read -rp "Enter device number [1-$INDEX]: " CHOICE
    if [ -z "$CHOICE" ] || [ "$CHOICE" -lt 1 ] || [ "$CHOICE" -gt "$INDEX" ] 2>/dev/null; then
        echo "ERROR: Invalid choice."
        exit 1
    fi
    DEVICE_ADDR="${ADDRS[$((CHOICE - 1))]}"
    DEVICE_NAME="${NAMES[$((CHOICE - 1))]}"
fi

echo
echo "=== Starting splitter ==="
echo "Device: $DEVICE_NAME ($DEVICE_ADDR)"
echo
echo "Two virtual serial ports will be created."
echo "Point each application at the printed /dev/pts/N path."
echo "Press Ctrl+C to stop."
echo

exec "$PYTHON" "$SPLITTER" --bt "$DEVICE_ADDR"