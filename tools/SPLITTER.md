# EEG Stream Splitter

Clone the NeuroSky MindWave data stream to two applications simultaneously — useful for running the original NeuroSky app and this trainer side by side to compare/calibrate metrics.

Other options: `--channel N` (Linux RFCOMM channel, default 1), `--baudrate N` (Windows, default 57600), `--record FILE` (Linux: save the stream for `tools/replay.py`).

---

## Linux Setup

### Prerequisites

- MindWave paired via Bluetooth (`bluetoothctl` → `pair AA:BB:CC:DD:EE:FF`)
- Python 3.10+

### Steps

1. **Find your MindWave MAC address:**
   ```bash
   bluetoothctl paired-devices   # or: bluetoothctl devices Paired
   # Example output: Device AA:BB:CC:DD:EE:FF MindWave Mobile
   ```

2. **Run the splitter:**
   ```bash
   python tools/splitter.py --bt AA:BB:CC:DD:EE:FF
   ```
   Output:
   ```
   Connected to AA:BB:CC:DD:EE:FF
     Port A (original app): /dev/pts/3
     Port B (your app):     /dev/pts/4
   ```

3. **Point each app at its port:**
   - Original app → `/dev/pts/3`
   - EEG Meditation Trainer → `/dev/pts/4`: `python main.py --serial /dev/pts/4`

   An app that needs full serial ioctl support (Wine) needs `--socat`, which creates `/tmp/mindwave_a` and `/tmp/mindwave_b` instead: see [COMPARISON.md](COMPARISON.md).

4. **Stop:** Press `Ctrl+C`

`./tools/splitter_linux.sh` does steps 1-2 in one command:
it checks Python, `bluetoothctl` and the bluetooth service, finds the paired MindWave by name (or lets you pick a paired device) and starts the splitter with two PTY outputs.

---

## Windows Setup

### Prerequisites

- MindWave paired in Windows Bluetooth settings (note which COM port it uses, e.g. COM5)
- Python 3.10+ with `pyserial`:
  ```
  pip install pyserial
  ```
- **com0com** virtual COM port driver

### Step 1: Install com0com

1. Download from https://com0com.sourceforge.net/
2. Run the installer
3. Open **com0com Setup** (from Start Menu)
4. Create **two virtual port pairs:**
   - Pair 1: `COM10 ↔ COM11`
   - Pair 2: `COM12 ↔ COM13`

   In the com0com GUI, click "Add Pair" and set the port names.
   Make sure "enable buffer overrun" is checked for both sides.

### Step 2: Run the splitter

```
python tools\splitter.py --serial COM5 --out1 COM10 --out2 COM12
```

Replace `COM5` with your actual MindWave COM port number (check Device Manager → Ports).

Output:
```
  Source (real device):   COM5
  Port A (original app): pair of COM10
  Port B (your app):     pair of COM12
```

### Step 3: Point each app at its paired port

The splitter writes to COM10 and COM12.
Each app reads from the **other end** of the pair:

```
MindWave (COM5) → splitter reads
    ├→ writes to COM10 → original app connects to COM11
    └→ writes to COM12 → your app connects to COM13
```

- **Original NeuroSky app** → set its COM port to **COM11**
- **EEG Meditation Trainer** → set its COM port to **COM13** (`python main.py --serial COM13`)

### How to redirect the original app to COM11

If the app has a port selector in settings, just pick COM11.

If the app auto-detects the MindWave on a fixed port (e.g. it always uses COM5):
1. Turn off / unpair the real MindWave from Windows Bluetooth
2. In com0com Setup, rename the output side of Pair 1 from COM11 to **COM5**
3. Now the app thinks COM5 is the real device, but it's receiving cloned data from the splitter
4. Run the splitter with the real device on its actual new port:
   ```
   python tools\splitter.py --serial COM7 --out1 COM10 --out2 COM12
   ```
   (the real device may move to a different port after re-pairing — check Device Manager)

### Step 4: Stop

Press `Ctrl+C` in the splitter terminal.

`tools\splitter_windows.bat` does steps 2-3 in one command:
it checks Python, installs pyserial if missing, checks the com0com driver (and prints its setup if it's missing) and finds the MindWave's COM port by name;
then it shows the port mapping (COM10→COM11, COM12→COM13) and how to redirect an app that auto-detects a fixed port, and starts the splitter.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `Access denied` on COM port | Close any app already using that port. Run as Administrator if needed |
| com0com ports not showing | Reboot after installing com0com. Check Device Manager → Ports |
| Data lag / stuttering | Increase buffer: check "enable buffer overrun" in com0com Setup for both sides |
| `pyserial` not found | `pip install pyserial` |
| Linux: `Permission denied` on BT | `sudo usermod -aG bluetooth $USER` then re-login |
| Linux: `Connection refused` | Make sure MindWave is turned on and paired (`bluetoothctl connect AA:BB:...`) |
