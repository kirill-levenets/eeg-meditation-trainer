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


def run_linux(bt_addr: str, channel: int = 1) -> None:
    """Read from BT RFCOMM, write to two PTYs."""
    import select
    import socket

    BTPROTO_RFCOMM = 3

    # Create two pseudo-terminal pairs
    master1, slave1 = os.openpty()
    master2, slave2 = os.openpty()
    name1 = os.ttyname(slave1)
    name2 = os.ttyname(slave2)

    print(f"Connecting to {bt_addr} channel {channel}...")
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, BTPROTO_RFCOMM)
    sock.connect((bt_addr, channel))
    sock.setblocking(False)
    print(f"Connected to {bt_addr}")
    print()
    print(f"  Port A (original app): {name1}")
    print(f"  Port B (your app):     {name2}")
    print()
    print("Point each application at the corresponding /dev/pts/N path.")
    print("Press Ctrl+C to stop.")
    print()

    bytes_total = 0
    try:
        while True:
            ready, _, _ = select.select([sock], [], [], 1.0)
            if ready:
                try:
                    data = sock.recv(1024)
                except BlockingIOError:
                    continue
                if not data:
                    print("Device disconnected.")
                    break
                os.write(master1, data)
                os.write(master2, data)
                bytes_total += len(data)
                if bytes_total % 10240 < len(data):
                    print(f"  [{bytes_total} bytes forwarded]", end="\r")
    except KeyboardInterrupt:
        print(f"\nStopped. Total bytes forwarded: {bytes_total}")
    finally:
        sock.close()
        os.close(master1)
        os.close(master2)
        os.close(slave1)
        os.close(slave2)


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
    args = parser.parse_args()

    if args.bt:
        if IS_WINDOWS:
            print("ERROR: --bt (Bluetooth RFCOMM) is only supported on Linux.")
            print("On Windows, use --serial COMx instead.")
            sys.exit(1)
        run_linux(args.bt, args.channel)
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