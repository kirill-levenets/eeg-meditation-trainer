#!/usr/bin/env python3
"""Bluetooth diagnostic & logging tool.

Collects detailed information about:
- Local BT adapter state and capabilities
- Paired/connected devices and their metadata
- Nearby discoverable devices (scan)
- Live HCI event monitoring (optional)
- RFCOMM connection test to a specific device

Usage:
    python tools/bt_diagnostic.py                    # full report
    python tools/bt_diagnostic.py --scan             # include discovery scan (takes ~10s)
    python tools/bt_diagnostic.py --monitor 30       # monitor HCI events for 30 seconds
    python tools/bt_diagnostic.py --connect AA:BB:CC:DD:EE:FF  # test RFCOMM connection
    python tools/bt_diagnostic.py --all              # everything (scan + monitor 15s)

Output is written to both stdout and a timestamped log file in tools/bt_logs/.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple


LOG_DIR = Path(__file__).parent / "bt_logs"


def run_cmd(cmd: List[str], timeout: int = 10, sudo: bool = False) -> Tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    if sudo:
        cmd = ["sudo"] + cmd
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", f"Command timed out after {timeout}s"
    except Exception as e:
        return -3, "", str(e)


class BTDiagnostic:
    def __init__(self, log_file: Path):
        self.log_file = log_file
        self._log_handle = open(log_file, "w")
        self.timestamp = datetime.datetime.now().isoformat()

    def log(self, msg: str = "", header: bool = False):
        if header:
            line = f"\n{'='*60}\n  {msg}\n{'='*60}"
        else:
            line = msg
        print(line)
        self._log_handle.write(line + "\n")
        self._log_handle.flush()

    def close(self):
        self._log_handle.close()

    # ---- Bluetooth enabled check ----

    def check_bluetooth_enabled(self) -> bool:
        """Check if Bluetooth is present and enabled. Returns True if usable."""
        self.log("BLUETOOTH STATUS CHECK", header=True)

        # 1. Check if bluetooth service is running
        rc, out, _ = run_cmd(["systemctl", "is-active", "bluetooth"])
        service_active = rc == 0 and out.strip() == "active"
        self.log(f"  Bluetooth service: {'active' if service_active else 'INACTIVE'}")

        if not service_active:
            self.log("  Hint: try 'sudo systemctl start bluetooth'")

        # 2. Check rfkill (soft/hard block)
        bt_blocked = False
        rc, out, _ = run_cmd(["rfkill", "-J", "list", "bluetooth"])
        if rc == 0 and out:
            try:
                data = json.loads(out)
                for entry in data.get("rfkilldevices", data.get("", [])):
                    soft = entry.get("soft", "unblocked")
                    hard = entry.get("hard", "unblocked")
                    self.log(f"  rfkill {entry.get('device', '?')}: soft={soft}, hard={hard}")
                    if soft == "blocked" or hard == "blocked":
                        bt_blocked = True
            except (json.JSONDecodeError, KeyError):
                # Fallback to plain text
                rc2, out2, _ = run_cmd(["rfkill", "list", "bluetooth"])
                if rc2 == 0:
                    self.log(f"  rfkill:\n{textwrap.indent(out2, '    ')}")
                    if "Soft blocked: yes" in out2 or "Hard blocked: yes" in out2:
                        bt_blocked = True
        else:
            rc2, out2, _ = run_cmd(["rfkill", "list", "bluetooth"])
            if rc2 == 0 and out2:
                self.log(f"  rfkill:\n{textwrap.indent(out2, '    ')}")
                if "Soft blocked: yes" in out2 or "Hard blocked: yes" in out2:
                    bt_blocked = True

        if bt_blocked:
            self.log("  WARNING: Bluetooth is blocked by rfkill!")
            self.log("  Hint: try 'sudo rfkill unblock bluetooth'")

        # 3. Check for HCI adapter and its state
        adapter_up = False
        rc, out, _ = run_cmd(["hciconfig"])
        if rc == 0 and out:
            if "UP" in out and "RUNNING" in out:
                adapter_up = True
                self.log("  HCI adapter: UP RUNNING")
            elif "DOWN" in out:
                self.log("  HCI adapter: DOWN")
                self.log("  Hint: try 'sudo hciconfig hci0 up'")
            else:
                self.log(f"  HCI adapter state: {out.splitlines()[0] if out else 'unknown'}")
        else:
            self.log("  HCI adapter: NOT FOUND")
            self.log("  No Bluetooth adapter detected on this system")

        # 4. Check bluetoothctl power state
        rc, out, _ = run_cmd(["bluetoothctl", "show"])
        if rc == 0 and out:
            powered = any("Powered: yes" in line for line in out.splitlines())
            self.log(f"  Controller powered: {'yes' if powered else 'NO'}")
            if not powered:
                self.log("  Hint: try 'bluetoothctl power on'")
                adapter_up = False

        # Summary
        usable = service_active and not bt_blocked and adapter_up
        self.log("")
        if usable:
            self.log("  >>> Bluetooth is ENABLED and ready <<<")
        else:
            self.log("  >>> Bluetooth is NOT usable <<<")
            reasons = []
            if not service_active:
                reasons.append("service not running")
            if bt_blocked:
                reasons.append("blocked by rfkill")
            if not adapter_up:
                reasons.append("adapter not up/powered")
            self.log(f"  Reasons: {', '.join(reasons)}")
        self.log("")
        return usable

    # ---- Adapter info ----

    def adapter_info(self):
        self.log("BLUETOOTH ADAPTER INFO", header=True)
        self.log(f"Timestamp: {self.timestamp}\n")

        # hciconfig -a
        self.log("--- hciconfig -a ---")
        rc, out, err = run_cmd(["hciconfig", "-a"])
        if rc == 0 and out:
            self.log(out)
            self._parse_hciconfig(out)
        else:
            self.log(f"  (failed: {err})")

        # bluetoothctl show
        self.log("\n--- bluetoothctl show ---")
        rc, out, err = run_cmd(["bluetoothctl", "show"])
        if rc == 0 and out:
            self.log(out)
        else:
            self.log(f"  (failed: {err})")

        # BT service status
        self.log("\n--- Bluetooth service status ---")
        rc, out, err = run_cmd(["systemctl", "status", "bluetooth", "--no-pager", "-l"])
        if rc in (0, 3) and out:
            # Only first 30 lines to keep it readable
            lines = out.splitlines()[:30]
            self.log("\n".join(lines))
        else:
            self.log(f"  (failed: {err})")

    def _parse_hciconfig(self, text: str):
        self.log("\n--- Parsed adapter summary ---")
        for block in text.split("\n\n"):
            m = re.search(r"^(hci\d+)", block)
            if not m:
                continue
            name = m.group(1)
            addr_m = re.search(r"BD Address:\s+([0-9A-Fa-f:]+)", block)
            state_m = re.search(r"(UP|DOWN)", block)
            type_m = re.search(r"Type:\s+(\S+)", block)
            features = re.findall(r"<([^>]+)>", block)
            self.log(f"  Adapter: {name}")
            self.log(f"  Address: {addr_m.group(1) if addr_m else 'unknown'}")
            self.log(f"  State:   {state_m.group(1) if state_m else 'unknown'}")
            self.log(f"  Type:    {type_m.group(1) if type_m else 'unknown'}")
            if features:
                self.log(f"  Features: {', '.join(features)}")

    # ---- Paired devices ----

    def paired_devices(self):
        self.log("PAIRED DEVICES", header=True)

        rc, out, err = run_cmd(["bluetoothctl", "paired-devices"])
        if rc != 0:
            rc, out, err = run_cmd(["bluetoothctl", "devices", "Paired"])

        if rc == 0 and out:
            devices = self._parse_device_list(out)
            self.log(f"Found {len(devices)} paired device(s)\n")
            for dev in devices:
                self._device_detail(dev["address"], dev["name"])
        else:
            self.log(f"  No paired devices or command failed: {err}")

    def connected_devices(self):
        self.log("CONNECTED DEVICES", header=True)

        rc, out, err = run_cmd(["bluetoothctl", "devices", "Connected"])
        if rc == 0 and out:
            devices = self._parse_device_list(out)
            self.log(f"Found {len(devices)} connected device(s)\n")
            for dev in devices:
                self.log(f"  {dev['name']} ({dev['address']})")
        else:
            self.log("  No connected devices")

    def _parse_device_list(self, text: str) -> List[Dict[str, str]]:
        devices = []
        for line in text.splitlines():
            parts = line.strip().split(" ", 2)
            if len(parts) >= 3 and parts[0] == "Device":
                devices.append({"address": parts[1], "name": parts[2]})
        return devices

    def _device_detail(self, address: str, name: str):
        self.log(f"  [{name}] {address}")
        rc, out, err = run_cmd(["bluetoothctl", "info", address])
        if rc == 0 and out:
            for line in out.splitlines():
                line = line.strip()
                if any(line.startswith(k) for k in [
                    "Name:", "Alias:", "Class:", "Icon:", "Paired:", "Bonded:",
                    "Trusted:", "Blocked:", "Connected:", "UUID:", "RSSI:",
                    "TxPower:", "ManufacturerData", "ServiceData",
                    "Modalias:", "Battery",
                ]):
                    self.log(f"    {line}")
        self.log("")

    # ---- Discovery scan ----

    def discovery_scan(self, duration: int = 10):
        self.log(f"DISCOVERY SCAN ({duration}s)", header=True)
        self.log("Starting scan...\n")

        # Use bluetoothctl with timeout
        try:
            proc = subprocess.Popen(
                ["bluetoothctl"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            proc.stdin.write("scan on\n")
            proc.stdin.flush()
            time.sleep(duration)
            proc.stdin.write("scan off\n")
            proc.stdin.write("devices\n")
            proc.stdin.flush()
            time.sleep(1)
            proc.stdin.write("quit\n")
            proc.stdin.flush()
            out, err = proc.communicate(timeout=5)

            # Parse discovered devices from output
            seen = set()
            for line in out.splitlines():
                if "Device" in line and ":" in line:
                    m = re.search(r"([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\s*(.*)", line)
                    if m and m.group(1) not in seen:
                        seen.add(m.group(1))
                        dev_name = m.group(2).strip() or "(unnamed)"
                        self.log(f"  {m.group(1)}  {dev_name}")

            if not seen:
                self.log("  No devices discovered")
            else:
                self.log(f"\n  Total: {len(seen)} device(s)")

                # Get details for each discovered device
                self.log("\n--- Discovered device details ---")
                for addr in seen:
                    rc, info_out, _ = run_cmd(["bluetoothctl", "info", addr])
                    if rc == 0 and info_out:
                        self.log(f"\n  {addr}:")
                        for line in info_out.splitlines():
                            line = line.strip()
                            if any(line.startswith(k) for k in [
                                "Name:", "Alias:", "Class:", "Icon:",
                                "Paired:", "RSSI:", "TxPower:",
                                "ManufacturerData", "UUID:", "Modalias:",
                            ]):
                                self.log(f"    {line}")

        except Exception as e:
            self.log(f"  Scan failed: {e}")

    # ---- HCI event monitor ----

    def hci_monitor(self, duration: int = 15):
        self.log(f"HCI EVENT MONITOR ({duration}s)", header=True)
        self.log("Capturing btmon output (may require sudo)...\n")

        try:
            proc = subprocess.Popen(
                ["sudo", "btmon", "-t"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            time.sleep(duration)
            proc.terminate()
            try:
                out, err = proc.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, err = proc.communicate()

            if out:
                lines = out.splitlines()
                self.log(f"  Captured {len(lines)} lines of HCI traffic")
                self.log("")
                # Log all, but summarize event types
                event_types: Dict[str, int] = {}
                for line in lines:
                    self.log(f"  {line}")
                    m = re.search(r"(HCI (?:Command|Event|ACL)[^(]*)", line)
                    if m:
                        evt = m.group(1).strip()
                        event_types[evt] = event_types.get(evt, 0) + 1

                if event_types:
                    self.log("\n--- HCI event summary ---")
                    for evt, count in sorted(event_types.items(), key=lambda x: -x[1]):
                        self.log(f"  {count:4d}x  {evt}")
            else:
                self.log("  No output captured")
                if err:
                    self.log(f"  stderr: {err}")

        except FileNotFoundError:
            self.log("  btmon not found. Install with: sudo apt install bluez")
        except Exception as e:
            self.log(f"  Monitor failed: {e}")

    # ---- RFCOMM connection test ----

    def test_rfcomm(self, address: str):
        self.log(f"RFCOMM CONNECTION TEST: {address}", header=True)

        import socket

        # Check if device is reachable
        self.log("\n--- L2CAP ping (l2ping) ---")
        rc, out, err = run_cmd(["sudo", "l2ping", "-c", "3", "-t", "5", address], timeout=20)
        if rc == 0:
            self.log(out)
        else:
            self.log(f"  l2ping failed: {err or out}")

        # SDP service browsing
        self.log("\n--- SDP service browse ---")
        rc, out, err = run_cmd(["sdptool", "browse", address], timeout=15)
        if rc == 0 and out:
            self.log(out)
        else:
            self.log(f"  SDP browse failed: {err}")
            self.log("  Trying sdptool records...")
            rc2, out2, err2 = run_cmd(["sdptool", "records", address], timeout=15)
            if rc2 == 0:
                self.log(out2 or "  (no records)")
            else:
                self.log(f"  SDP records failed: {err2}")

        # Attempt RFCOMM connection
        self.log("\n--- RFCOMM socket connect (channel 1) ---")
        BTPROTO_RFCOMM = 3
        try:
            sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, BTPROTO_RFCOMM)
            sock.settimeout(10.0)
            self.log(f"  Connecting to {address} channel 1...")
            t0 = time.time()
            sock.connect((address, 1))
            elapsed = time.time() - t0
            self.log(f"  Connected in {elapsed:.2f}s")

            # Try reading a few bytes
            self.log("  Reading data (5s)...")
            sock.settimeout(5.0)
            total_bytes = 0
            packets_seen = 0
            t_start = time.time()
            while time.time() - t_start < 5.0:
                try:
                    data = sock.recv(512)
                    if data:
                        total_bytes += len(data)
                        packets_seen += 1
                        if packets_seen <= 5:
                            hex_preview = data[:32].hex(" ")
                            self.log(f"    recv #{packets_seen}: {len(data)} bytes: {hex_preview}...")
                except socket.timeout:
                    break
                except Exception as e:
                    self.log(f"    read error: {e}")
                    break

            self.log(f"  Total: {total_bytes} bytes in {packets_seen} recv() calls ({time.time()-t_start:.1f}s)")
            sock.close()
            self.log("  Socket closed cleanly")

        except socket.timeout:
            self.log("  Connection timed out (10s)")
        except OSError as e:
            self.log(f"  Connection failed: {e}")
            self.log(f"  errno: {e.errno}")
        except Exception as e:
            self.log(f"  Unexpected error: {e}")

    # ---- System BT info ----

    def system_info(self):
        self.log("SYSTEM BLUETOOTH INFO", header=True)

        self.log("--- Kernel modules ---")
        rc, out, _ = run_cmd(["lsmod"])
        if rc == 0:
            bt_modules = [l for l in out.splitlines() if "bluetooth" in l.lower() or "btusb" in l.lower() or "rfcomm" in l.lower() or "bnep" in l.lower() or "hci" in l.lower()]
            if bt_modules:
                self.log("  " + bt_modules[0].split()[0].ljust(24) + bt_modules[0].split()[1].rjust(8) if bt_modules else "")
                for m in bt_modules:
                    parts = m.split()
                    self.log(f"  {parts[0]:24s} {parts[1]:>8s}  {parts[3] if len(parts) > 3 else ''}")
            else:
                self.log("  No Bluetooth kernel modules loaded")

        self.log("\n--- USB Bluetooth devices ---")
        rc, out, _ = run_cmd(["lsusb"])
        if rc == 0:
            bt_usb = [l for l in out.splitlines() if "bluetooth" in l.lower()]
            for l in bt_usb:
                self.log(f"  {l}")
            if not bt_usb:
                self.log("  No USB Bluetooth adapters found (may be built-in)")

        self.log("\n--- rfkill status ---")
        rc, out, _ = run_cmd(["rfkill", "list", "bluetooth"])
        if rc == 0 and out:
            self.log(out)
        else:
            self.log("  rfkill not available or no bluetooth devices")

        self.log("\n--- BlueZ version ---")
        rc, out, _ = run_cmd(["bluetoothctl", "version"])
        if rc == 0:
            self.log(f"  {out}")
        rc, out, _ = run_cmd(["bluetoothd", "--version"])
        if rc == 0:
            self.log(f"  bluetoothd: {out}")

        self.log("\n--- D-Bus bluetooth service ---")
        rc, out, _ = run_cmd(["busctl", "tree", "org.bluez"], timeout=5)
        if rc == 0 and out:
            lines = out.splitlines()[:40]
            self.log("\n".join(f"  {l}" for l in lines))
            if len(out.splitlines()) > 40:
                self.log(f"  ... ({len(out.splitlines())} lines total)")


def main():
    parser = argparse.ArgumentParser(
        description="Bluetooth diagnostic & logging tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python tools/bt_diagnostic.py                        # basic report
              python tools/bt_diagnostic.py --scan                 # + discovery scan
              python tools/bt_diagnostic.py --monitor 30           # + HCI monitor 30s
              python tools/bt_diagnostic.py --connect AA:BB:...    # test RFCOMM
              python tools/bt_diagnostic.py --all                  # everything
        """),
    )
    parser.add_argument("--scan", action="store_true", help="Include discovery scan (~10s)")
    parser.add_argument("--scan-duration", type=int, default=10, help="Scan duration in seconds (default: 10)")
    parser.add_argument("--monitor", type=int, nargs="?", const=15, default=0,
                        help="Monitor HCI events for N seconds (default: 15)")
    parser.add_argument("--connect", type=str, metavar="ADDR",
                        help="Test RFCOMM connection to device address")
    parser.add_argument("--all", action="store_true", help="Run all diagnostics")
    parser.add_argument("-o", "--output", type=str, help="Custom output file path")

    args = parser.parse_args()

    # Setup log file
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(args.output) if args.output else LOG_DIR / f"bt_diag_{ts}.log"

    diag = BTDiagnostic(log_path)

    try:
        bt_enabled = diag.check_bluetooth_enabled()
        diag.system_info()
        diag.adapter_info()

        if not bt_enabled:
            diag.log("\nSkipping device queries — Bluetooth is not usable.")
            diag.log("Fix the issues above and re-run.")
            diag.log(f"\nLOG SAVED", header=True)
            diag.log(f"  {log_path.resolve()}")
            diag.close()
            print(f"\nLog saved to: {log_path.resolve()}")
            sys.exit(1)

        diag.paired_devices()
        diag.connected_devices()

        if args.scan or args.all:
            diag.discovery_scan(args.scan_duration)

        if args.monitor or args.all:
            duration = args.monitor if args.monitor else 15
            diag.hci_monitor(duration)

        if args.connect:
            diag.test_rfcomm(args.connect)
        elif args.all:
            # Auto-detect NeuroSky from paired devices
            rc, out, _ = run_cmd(["bluetoothctl", "paired-devices"])
            if rc == 0:
                for line in out.splitlines():
                    if "MindWave" in line or "NeuroSky" in line:
                        parts = line.strip().split(" ", 2)
                        if len(parts) >= 2:
                            diag.log(f"\nAuto-detected NeuroSky device: {parts[1]}")
                            diag.test_rfcomm(parts[1])
                            break

        diag.log(f"\nLOG SAVED", header=True)
        diag.log(f"  {log_path.resolve()}")

    finally:
        diag.close()

    print(f"\nLog saved to: {log_path.resolve()}")


if __name__ == "__main__":
    main()