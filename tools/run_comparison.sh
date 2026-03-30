#!/bin/bash
# Run both EEG apps simultaneously on the same live MindWave stream.
# Usage: ./tools/run_comparison.sh [MAC_ADDRESS]

BT_ADDR="${1:-AA:BB:CC:DD:EE:FF}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
WINE_APP_DIR="${WINE_APP_DIR:-$HOME/eegmeditation}"
LOG_FILE="$PROJECT_DIR/tools/bt_logs/comparison_$(date +%Y%m%d_%H%M%S).log"
SESSION_FILE="$PROJECT_DIR/session_$(date +%Y%m%d_%H%M%S).eeg"

mkdir -p "$PROJECT_DIR/tools/bt_logs"

log() {
    echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

cleanup() {
    log "Cleaning up..."
    [ -n "$SPLITTER_PID" ] && kill "$SPLITTER_PID" 2>/dev/null && log "Splitter stopped"
    [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null && log "Your app stopped"
    wineserver -k 2>/dev/null && log "Wine stopped"
    log "Done. Recording: $SESSION_FILE"
    log "Log: $LOG_FILE"
}
trap cleanup EXIT

log "=== EEG Comparison Session ==="
log "MindWave: $BT_ADDR"
log "Recording: $SESSION_FILE"
log ""

# 1. Check prerequisites
log "Checking prerequisites..."
command -v wine >/dev/null || { log "ERROR: wine not found"; exit 1; }
command -v socat >/dev/null || { log "ERROR: socat not found (sudo apt install socat)"; exit 1; }
[ -f "$WINE_APP_DIR/EEG Meditation.exe" ] || { log "ERROR: Wine app not found at $WINE_APP_DIR"; exit 1; }

# Release any existing rfcomm binding
sudo rfcomm release 0 2>/dev/null || true

# 2. Start splitter
log "Starting splitter (BT -> socat + recording)..."
cd "$PROJECT_DIR"
python3 tools/splitter.py --bt "$BT_ADDR" --socat --record "$SESSION_FILE" > /tmp/splitter_stdout.log 2>&1 &
SPLITTER_PID=$!
sleep 4

if ! kill -0 "$SPLITTER_PID" 2>/dev/null; then
    log "ERROR: Splitter failed to start. Check MindWave is on."
    cat /tmp/splitter_stdout.log | tee -a "$LOG_FILE"
    exit 1
fi
log "Splitter running (PID $SPLITTER_PID)"

# 3. Start your app
log "Starting your app (reading from /tmp/mindwave_b)..."
cd "$PROJECT_DIR"
python3 main.py --serial /tmp/mindwave_b > /tmp/eeg_app_stdout.log 2>&1 &
APP_PID=$!
sleep 2
log "Your app running (PID $APP_PID)"

# 4. Start Wine app
log "Starting Wine app..."
cd "$WINE_APP_DIR"
wine "EEG Meditation.exe" > /tmp/wine_eeg_stdout.log 2>&1 &
WINE_PID=$!

# Wait for Wine to initialize and reset COM ports, then fix the symlink
sleep 3
REAL_PTY=$(readlink -f /tmp/mindwave_a 2>/dev/null)
if [ -z "$REAL_PTY" ]; then
    log "WARNING: /tmp/mindwave_a not found. Wine app may not receive data."
else
    ln -sf "$REAL_PTY" ~/.wine/dosdevices/com1
    log "Wine COM1 -> $REAL_PTY"
fi
log "Wine app running (PID $WINE_PID)"

log ""
log "============================================"
log "  READY! Both apps should be receiving data."
log "  Click Start in both apps now."
log "============================================"
log ""
log "Press Ctrl+C to stop everything."

# Keep running until Ctrl+C — monitor all processes
while true; do
    if ! kill -0 "$SPLITTER_PID" 2>/dev/null; then
        log "WARNING: Splitter died. Check MindWave connection."
        log "Restarting splitter in 3 seconds..."
        sleep 3
        cd "$PROJECT_DIR"
        python3 tools/splitter.py --bt "$BT_ADDR" --socat --record "$SESSION_FILE" > /tmp/splitter_stdout.log 2>&1 &
        SPLITTER_PID=$!
        sleep 3
        if kill -0 "$SPLITTER_PID" 2>/dev/null; then
            log "Splitter restarted (PID $SPLITTER_PID)"
            # Re-fix Wine COM1 symlink since socat created new PTYs
            REAL_PTY=$(readlink -f /tmp/mindwave_a 2>/dev/null)
            [ -n "$REAL_PTY" ] && ln -sf "$REAL_PTY" ~/.wine/dosdevices/com1
            log "Wine COM1 -> $REAL_PTY"
        else
            log "ERROR: Splitter failed to restart. Exiting."
            break
        fi
    fi
    sleep 2
done