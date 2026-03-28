#!/usr/bin/env python3
"""Replay a recorded EEG stream to a serial device or RFCOMM binding.

Plays back a .eeg recording (from splitter --record) with original timing,
so that the receiving app sees the same data as during the live session.

Usage:
    # Replay to /dev/rfcomm0 (for Wine app via COM1):
    sudo rfcomm bind 0 C4:64:E3:E8:CC:CA 1   # create the device first
    # (disconnect rfcomm since we just need the device node)
    python tools/replay.py session.eeg --device /dev/rfcomm0

    # Replay to a socat virtual serial (for any serial reader):
    python tools/replay.py session.eeg

    # Replay at 2x speed:
    python tools/replay.py session.eeg --speed 2.0

The default (no --device) creates a socat virtual serial at /tmp/mindwave_replay
that you can point Wine COM1 at:
    ln -sf /tmp/mindwave_replay ~/.wine/dosdevices/com1
"""

import argparse
import os
import struct
import subprocess
import sys
import time


def read_recording(path: str):
    """Yield (timestamp, data) tuples from a .eeg recording file."""
    with open(path, "rb") as f:
        while True:
            header = f.read(10)  # double (8) + ushort (2)
            if len(header) < 10:
                break
            ts, length = struct.unpack("<dH", header)
            data = f.read(length)
            if len(data) < length:
                break
            yield ts, data


def replay(recording_path: str, device_path: str = None, speed: float = 1.0,
           loop: bool = False):
    socat_proc = None
    write_fd = None

    if device_path:
        # Write directly to a device file
        print(f"Opening device: {device_path}")
        try:
            write_fd = os.open(device_path, os.O_WRONLY | os.O_NOCTTY)
        except OSError as e:
            print(f"ERROR: Cannot open {device_path}: {e}")
            sys.exit(1)
        print(f"  Replaying to: {device_path}")
    else:
        # Create a socat virtual serial pair
        master_link = "/tmp/mindwave_replay_master"
        slave_link = "/tmp/mindwave_replay"
        for p in (master_link, slave_link):
            if os.path.exists(p) or os.path.islink(p):
                os.unlink(p)
        socat_proc = subprocess.Popen(
            [
                "socat", "-d",
                f"pty,raw,echo=0,b57600,link={master_link}",
                f"pty,raw,echo=0,b57600,link={slave_link}",
            ],
            stderr=subprocess.PIPE,
        )
        for _ in range(20):
            if os.path.exists(slave_link):
                break
            time.sleep(0.1)
        else:
            print("ERROR: socat failed to create virtual serial ports")
            socat_proc.terminate()
            sys.exit(1)

        write_fd = os.open(master_link, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
        print(f"  Replay device: {slave_link}")
        print(f"  For Wine: ln -sf {slave_link} ~/.wine/dosdevices/com1")

    # Count total packets and duration
    packets = list(read_recording(recording_path))
    if not packets:
        print("ERROR: Recording is empty")
        sys.exit(1)

    total_bytes = sum(len(d) for _, d in packets)
    duration = packets[-1][0]
    print(f"  Recording: {len(packets)} packets, {total_bytes} bytes, {duration:.1f}s")
    print(f"  Replay speed: {speed}x")
    print()
    print("Waiting 3 seconds for app to connect...")
    time.sleep(3)
    print("Replaying... Press Ctrl+C to stop.")

    bytes_sent = 0
    loop_count = 0
    replay_start = time.time()
    try:
        while True:
            loop_count += 1
            loop_start = time.time()
            print(f"  Loop {loop_count}...")
            for ts, data in packets:
                target_time = loop_start + (ts / speed)
                now = time.time()
                if target_time > now:
                    time.sleep(target_time - now)

                try:
                    os.write(write_fd, data)
                except (OSError, BlockingIOError):
                    pass
                bytes_sent += len(data)
                if bytes_sent % 10240 < len(data):
                    elapsed = time.time() - replay_start
                    print(f"  [loop {loop_count}, {bytes_sent} bytes, {elapsed:.1f}s]", end="\r")

            if not loop:
                break

        elapsed = time.time() - replay_start
        print(f"\nReplay complete: {bytes_sent} bytes in {elapsed:.1f}s")
    except KeyboardInterrupt:
        elapsed = time.time() - replay_start
        print(f"\nStopped at {elapsed:.1f}s. Sent {bytes_sent}/{total_bytes} bytes")
    finally:
        os.close(write_fd)
        if socat_proc:
            socat_proc.terminate()
            socat_proc.wait()


def main():
    parser = argparse.ArgumentParser(
        description="Replay a recorded EEG stream with original timing"
    )
    parser.add_argument("recording", help="Path to .eeg recording file (from splitter --record)")
    parser.add_argument("--device", metavar="PATH",
                        help="Serial device to write to (e.g. /dev/rfcomm0). "
                             "Default: create socat virtual serial at /tmp/mindwave_replay")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="Playback speed multiplier (default: 1.0)")
    parser.add_argument("--loop", action="store_true",
                        help="Loop replay infinitely until Ctrl+C")
    args = parser.parse_args()

    if not os.path.exists(args.recording):
        print(f"ERROR: Recording file not found: {args.recording}")
        sys.exit(1)

    replay(args.recording, device_path=args.device, speed=args.speed,
           loop=args.loop)


if __name__ == "__main__":
    main()