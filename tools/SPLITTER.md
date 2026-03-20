# EEG Stream Splitter

Clone the NeuroSky MindWave data stream to two applications simultaneously — useful for running the original NeuroSky app and this trainer side by side to compare/calibrate metrics.

---

## Linux Setup

### Prerequisites

- MindWave paired via Bluetooth (`bluetoothctl` → `pair AA:BB:CC:DD:EE:FF`)
- Python 3.10+

### Steps

1. **Find your MindWave MAC address:**
   ```bash
   bluetoothctl paired-devices
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
   - EEG Meditation Trainer → `/dev/pts/4`

   For this trainer, modify the device address in settings to use the PTY path, or connect via the serial port directly by updating `neurosky_stream.py` to accept a serial device path.

4. **Stop:** Press `Ctrl+C`

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

   In the com0com GUI, click "Add Pair" and set the port names. Make sure "enable buffer overrun" is checked for both sides.

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

The splitter writes to COM10 and COM12. Each app reads from the **other end** of the pair:

```
MindWave (COM5) → splitter reads
    ├→ writes to COM10 → original app connects to COM11
    └→ writes to COM12 → your app connects to COM13
```

- **Original NeuroSky app** → set its COM port to **COM11**
- **EEG Meditation Trainer** → set its COM port to **COM13**

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


##   splitter_linux.sh — one command does everything:
  1. Checks Python and bluetoothctl are installed
  2. Checks bluetooth service is running
  3. Scans paired devices, auto-detects MindWave by name
  4. Lets you pick a device if not auto-detected
  5. Launches the splitter with two PTY outputs

##  splitter_windows.bat — one command does everything:
  1. Checks Python is installed
  2. Installs pyserial if missing
  3. Checks com0com driver is installed (prints full setup instructions if not)
  4. Scans for MindWave COM port via WMI, auto-detects by name
  5. Shows the port mapping (COM10→COM11, COM12→COM13)
  6. Prints instructions for redirecting apps that auto-detect a fixed port
  7. Launches the splitter

##  Usage:
### Linux
./tools/splitter_linux.sh

### Windows
tools\splitter_windows.bat
