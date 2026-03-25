#!/usr/bin/env python3
"""EEG stream splitter — clones one NeuroSky BT/COM source to two outputs.

Allows running two applications simultaneously on the same EEG device stream
(e.g. original NeuroSky app + this trainer for metrics comparison).

Linux:  reads from BT RFCOMM socket, fans out to two pseudo-terminals (PTYs)
Windows: reads from real COM port, fans out to two virtual COM ports (com0com)

Usage:
    Linux:   python tools/splitter.py --bt AA:BB:CC:DD:EE:FF
    Windows: python tools/splitter.py --serial COM5 --out1 COM10 --out2 COM12
"""
import argparse
import os
import platform
import sys
import time

IS_WINDOWS = platform.system() == "Windows"


def run_linux(bt_addr: str, channel: int = 1, use_socat: bool = False,
              record_file: str = None) -> None:
    """Read from BT RFCOMM, write to two virtual serial ports.

    With --socat: creates proper virtual serial devices via socat (needed for
    Wine/thinkgear.dll which requires full serial ioctl support).
    Without: uses simple PTYs (fine for apps that just read raw bytes).
    """
    import select
    import signal
    import socket
    import subprocess

    BTPROTO_RFCOMM = 3
    socat_procs = []

    if use_socat:
        # Create two socat virtual serial pairs:
        #   /tmp/mindwave_a_master <-> /tmp/mindwave_a  (app A reads from _a)
        #   /tmp/mindwave_b_master <-> /tmp/mindwave_b  (app B reads from _b)
        pairs = [
            ("/tmp/mindwave_a_master", "/tmp/mindwave_a"),
            ("/tmp/mindwave_b_master", "/tmp/mindwave_b"),
        ]
        for master_link, slave_link in pairs:
            # Clean up stale symlinks
            for p in (master_link, slave_link):
                if os.path.exists(p) or os.path.islink(p):
                    os.unlink(p)
            proc = subprocess.Popen(
                [
                    "socat", "-d",
                    f"pty,raw,echo=0,link={master_link}",
                    f"pty,raw,echo=0,link={slave_link}",
                ],
                stderr=subprocess.PIPE,
            )
            socat_procs.append(proc)

        # Wait for socat to create the links
        for _ in range(20):
            if all(os.path.exists(p[1]) for p in pairs):
                break
            time.sleep(0.1)
        else:
            print("ERROR: socat failed to create virtual serial ports")
            for p in socat_procs:
                p.terminate()
            sys.exit(1)

        # Open the master side for writing (non-blocking to avoid stalling)
        import fcntl
        master1_fd = os.open(pairs[0][0], os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
        master2_fd = os.open(pairs[1][0], os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
        name1 = pairs[0][1]
        name2 = pairs[1][1]
        slave1_fd = None
        slave2_fd = None
    else:
        # Simple PTY mode
        master1_fd, slave1_fd = os.openpty()
        master2_fd, slave2_fd = os.openpty()
        name1 = os.ttyname(slave1_fd)
        name2 = os.ttyname(slave2_fd)

    print(f"Connecting to {bt_addr} channel {channel}...")
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, BTPROTO_RFCOMM)
    sock.connect((bt_addr, channel))
    sock.setblocking(False)
    print(f"Connected to {bt_addr}")
    print()
    print(f"  Port A (original app): {name1}")
    print(f"  Port B (your app):     {name2}")
    if use_socat:
        print()
        print("  These are proper serial devices (socat). For Wine:")
        print(f"    ln -sf {name1} ~/.wine/dosdevices/com1")
    print()
    rec_fh = None
    if record_file:
        rec_fh = open(record_file, "wb")
        print(f"  Recording raw stream to: {record_file}")

    print()
    print("Press Ctrl+C to stop.")
    print()

    bytes_total = 0
    t_start = time.time()
    try:
        while True:
            ready, _, _ = select.select([sock], [], [], 1.0)
            if ready:
                try:
                    data = sock.recv(1024)
                except BlockingIOError:
                    continue
                except (TimeoutError, ConnectionError, OSError) as e:
                    print(f"\nDevice disconnected: {e}")
                    break
                if not data:
                    print("Device disconnected.")
                    break
                try:
                    os.write(master1_fd, data)
                except (OSError, BlockingIOError):
                    pass  # reader not connected or buffer full
                try:
                    os.write(master2_fd, data)
                except (OSError, BlockingIOError):
                    pass
                if rec_fh:
                    # Write timestamp + length + data for accurate replay
                    elapsed = time.time() - t_start
                    import struct as _struct
                    rec_fh.write(_struct.pack("<dH", elapsed, len(data)))
                    rec_fh.write(data)
                bytes_total += len(data)
                if bytes_total % 10240 < len(data):
                    print(f"  [{bytes_total} bytes forwarded]", end="\r")
    except KeyboardInterrupt:
        print(f"\nStopped. Total bytes forwarded: {bytes_total}")
    finally:
        sock.close()
        os.close(master1_fd)
        os.close(master2_fd)
        if slave1_fd is not None:
            os.close(slave1_fd)
        if slave2_fd is not None:
            os.close(slave2_fd)
        if rec_fh:
            rec_fh.close()
            print(f"Recording saved: {record_file}")
        for p in socat_procs:
            p.terminate()
            p.wait()


def run_windows(source_port: str, out1: str, out2: str, baudrate: int = 57600) -> None:
    """Read from real COM port, write to two virtual COM ports (com0com)."""
    try:
        import serial
    except ImportError:
        print("ERROR: pyserial is required. Install with: pip install pyserial")
        sys.exit(1)

    print(f"Opening source: {source_port} at {baudrate} baud")
    src = serial.Serial(source_port, baudrate=baudrate, timeout=1)

    print(f"Opening output: {out1}")
    dst1 = serial.Serial(out1, baudrate=baudrate)

    print(f"Opening output: {out2}")
    dst2 = serial.Serial(out2, baudrate=baudrate)

    print()
    print(f"  Source (real device):   {source_port}")
    print(f"  Port A (original app): pair of {out1}")
    print(f"  Port B (your app):     pair of {out2}")
    print()
    print("Point each application at the OTHER end of each com0com pair.")
    print("Press Ctrl+C to stop.")
    print()

    bytes_total = 0
    try:
        while True:
            waiting = src.in_waiting
            if waiting > 0:
                data = src.read(waiting)
            else:
                data = src.read(1)
            if data:
                dst1.write(data)
                dst2.write(data)
                bytes_total += len(data)
                if bytes_total % 10240 < len(data):
                    print(f"  [{bytes_total} bytes forwarded]", end="\r")
    except KeyboardInterrupt:
        print(f"\nStopped. Total bytes forwarded: {bytes_total}")
    finally:
        src.close()
        dst1.close()
        dst2.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clone a NeuroSky EEG stream to two outputs for simultaneous apps"
    )
    parser.add_argument(
        "--bt", metavar="ADDRESS",
        help="(Linux) Bluetooth MAC address of MindWave, e.g. AA:BB:CC:DD:EE:FF"
    )
    parser.add_argument(
        "--channel", type=int, default=1,
        help="(Linux) RFCOMM channel number (default: 1)"
    )
    parser.add_argument(
        "--serial", metavar="PORT",
        help="(Windows) Source COM port, e.g. COM5"
    )
    parser.add_argument(
        "--out1", default="COM10",
        help="(Windows) First output virtual COM port (default: COM10)"
    )
    parser.add_argument(
        "--out2", default="COM12",
        help="(Windows) Second output virtual COM port (default: COM12)"
    )
    parser.add_argument(
        "--baudrate", type=int, default=57600,
        help="(Windows) Serial baud rate (default: 57600)"
    )
    parser.add_argument(
        "--socat", action="store_true",
        help="(Linux) Use socat virtual serial devices instead of PTYs. "
             "Required for Wine/thinkgear.dll which needs full serial ioctl support."
    )
    parser.add_argument(
        "--record", metavar="FILE",
        help="Record raw BT stream to file for later replay"
    )
    args = parser.parse_args()

    if args.bt:
        if IS_WINDOWS:
            print("ERROR: --bt (Bluetooth RFCOMM) is only supported on Linux.")
            print("On Windows, use --serial COMx instead.")
            sys.exit(1)
        run_linux(args.bt, args.channel, use_socat=args.socat,
                  record_file=args.record)
    elif args.serial:
        if not IS_WINDOWS:
            print("NOTE: --serial mode is intended for Windows with com0com.")
            print("On Linux, prefer --bt for direct Bluetooth RFCOMM.")
        run_windows(args.serial, args.out1, args.out2, args.baudrate)
    else:
        if IS_WINDOWS:
            print("Usage (Windows): python tools/splitter.py --serial COM5 --out1 COM10 --out2 COM12")
        else:
            print("Usage (Linux):   python tools/splitter.py --bt AA:BB:CC:DD:EE:FF")
        sys.exit(1)


if __name__ == "__main__":
    main()