# EEG Formula Comparison: Your App vs Windows App

Compare your meditation formula output against the NeuroSky Windows app ("EEG Meditation") using the same EEG data stream.

## Overview

The MindWave headset only supports one Bluetooth connection at a time. Two approaches:

1. **Simultaneous** (recommended) — splitter feeds both apps the same live stream
2. **Record & replay** — record a session, replay to each app separately

## Prerequisites

- MindWave Mobile paired via `bluetoothctl`
- Wine installed (`wine --version`)
- `socat` installed (`sudo apt install socat`)
- Windows app at `~/eegmeditation/`
- Your MindWave MAC address (use `bluetoothctl paired-devices`)

---

## Option A: Simultaneous (One Script)

Power on the MindWave (LED should blink), then:

```bash
./tools/run_comparison.sh
```

This single script:
1. Starts the splitter (connects to MindWave via BT, records to `.eeg` file)
2. Launches your app (reads from `/tmp/mindwave_b`)
3. Launches the Wine app and fixes the COM1 symlink after Wine initializes
4. Prints **READY!** when both apps are receiving data
5. Auto-restarts the splitter if BT connection drops

Click **Start** in both apps when you see the READY message. Press **Ctrl+C** to stop everything.

You can also pass a custom MAC address:
```bash
./tools/run_comparison.sh AA:BB:CC:DD:EE:FF
```

## Option B: Simultaneous (Manual Terminals)

If you prefer to run each component separately:

**Terminal 1 — Splitter with recording:**
```bash
python3 tools/splitter.py --bt AA:BB:CC:DD:EE:FF --socat --record session.eeg
```

**Terminal 2 — Your app:**
```bash
python main.py --serial /tmp/mindwave_b
```

**Terminal 3 — Wine app:**
```bash
cd ~/eegmeditation && wine "EEG Meditation.exe" &
sleep 2
ln -sf $(readlink -f /tmp/mindwave_a) ~/.wine/dosdevices/com1
echo "COM1 -> $(readlink ~/.wine/dosdevices/com1)"
```

Click **Start** in both apps. Press Ctrl+C in Terminal 1 to stop everything.

> **Important:** Wine resets `com1 -> /dev/rfcomm0` on every startup.
> You must re-link com1 **after** launching Wine, every time.

---

## Option C: Record & Replay

Record once, then replay the same data to each app separately.

### Step 1: Record

```bash
# Terminal 1: splitter with recording
python3 tools/splitter.py --bt AA:BB:CC:DD:EE:FF --socat --record session.eeg

# Terminal 2: your app gets live data during recording
python main.py --serial /tmp/mindwave_b
```

Run a session for 3-5 minutes, then Ctrl+C both terminals.

### Step 2: Replay to Wine App

```bash
# Terminal 1: start replay (loops forever)
python3 tools/replay.py session.eeg --loop

# Terminal 2: launch Wine (must re-link com1 after start)
cd ~/eegmeditation && wine "EEG Meditation.exe" &
sleep 2
ln -sf $(readlink -f /tmp/mindwave_replay) ~/.wine/dosdevices/com1
```

Click **Start** in the Wine app.

### Step 3: Replay to Your App

```bash
# Terminal 1
python3 tools/replay.py session.eeg --loop

# Terminal 2
python main.py --serial /tmp/mindwave_replay
```

Both apps process the exact same EEG data. Compare the results.

### Replay Options

```bash
# Replay at 2x speed
python3 tools/replay.py session.eeg --loop --speed 2.0

# Single playback (no loop)
python3 tools/replay.py session.eeg

# Replay to a specific device
python3 tools/replay.py session.eeg --device /dev/rfcomm0
```

> **Note:** At each loop boundary the Wine app may briefly show "low battery"
> as the stream restarts. Use longer recordings (3-5 min) to minimize this.

---

## Running the Windows App Directly (No Splitter)

If you just want to run the Wine app on live BT data (without your app):

```bash
sudo rfcomm bind 0 AA:BB:CC:DD:EE:FF 1
ln -sf /dev/rfcomm0 ~/.wine/dosdevices/com1
cd ~/eegmeditation && wine "EEG Meditation.exe"
```

When done:
```bash
sudo rfcomm release 0
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `Device or resource busy` when starting splitter | Another app holds the BT connection. Stop your app / release rfcomm: `sudo rfcomm release 0` |
| Wine says "No headset found" | COM1 symlink is wrong. Check: `readlink ~/.wine/dosdevices/com1` — must point to a `/dev/pts/N` that exists. Re-run the `ln -sf` command **after** launching Wine |
| Wine resets com1 on launch | This always happens. Always re-link after Wine starts: `ln -sf $(readlink -f /tmp/mindwave_a) ~/.wine/dosdevices/com1` |
| Splitter dies / BT timeout | MindWave went to sleep or out of range. Power-cycle headset (off 5s, on). The `run_comparison.sh` script auto-restarts the splitter |
| Replay shows "Recording is empty" | The `.eeg` file was not written. Re-record with `--record` flag |
| MindWave won't connect | Power-cycle the headset. Check `bluetoothctl info AA:BB:CC:DD:EE:FF` — should show Paired: yes |
| Low battery warning in Wine app | Loop boundary in replay, or BT reconnect. Use longer recordings |
| Your app ignores `--serial` flag | `KIVY_NO_ARGS=1` must be set before Kivy imports (already in `main.py`) |
| Your app shows "Connecting..." but logs show connected | Wait a few seconds — band power packets arrive once/second. The UI updates after receiving the first valid EEG data |

## File Formats

The `.eeg` recording file stores raw Bluetooth bytes with timestamps:
- Each chunk: `[timestamp: float64][length: uint16][data: bytes]`
- Timestamps are seconds since recording start
- Replay preserves original timing between chunks

## Architecture

```
Simultaneous (run_comparison.sh or manual):
  MindWave (BT) -> splitter.py --socat --record
                     |-> /tmp/mindwave_a (/dev/pts/N) -> Wine COM1
                     |-> /tmp/mindwave_b (/dev/pts/M) -> your app (--serial)
                     |-> session.eeg                   (recording file)

Record & Replay:
  session.eeg -> replay.py --loop
                   |-> /tmp/mindwave_replay (/dev/pts/N)
                         |-> Wine COM1 (via dosdevices symlink)
                         |   or
                         |-> your app (via --serial)
```
