#!/usr/bin/env python3
"""Minimal MindWave Mobile 2 connection test.

Tests raw RFCOMM connection and ThinkGear packet parsing with no app code.
Usage:
    python tools/bt_test.py C4:64:E3:E8:CC:CA
    python tools/bt_test.py              # uses default MAC
"""
import socket
import struct
import sys
import time

DEFAULT_MAC = "C4:64:E3:E8:CC:CA"
RFCOMM_CHANNEL = 1
CONNECT_TIMEOUT = 30.0
READ_TIMEOUT = 5.0

SYNC = 0xAA
CODE_SIGNAL = 0x02
CODE_ATTENTION = 0x04
CODE_MEDITATION = 0x05
CODE_RAW = 0x80
CODE_EEG_POWER = 0x83

BAND_NAMES = ("delta", "theta", "alpha1", "alpha2", "beta1", "beta2", "gamma1", "gamma2")


def connect(mac: str) -> socket.socket:
    """Connect to MindWave via RFCOMM."""
    print(f"Connecting to {mac} channel {RFCOMM_CHANNEL}...")
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, 3)  # BTPROTO_RFCOMM
    sock.settimeout(CONNECT_TIMEOUT)
    t0 = time.time()
    sock.connect((mac, RFCOMM_CHANNEL))
    print(f"Connected in {time.time() - t0:.1f}s")
    sock.settimeout(READ_TIMEOUT)
    return sock


def read_byte(sock: socket.socket) -> int:
    """Read a single byte."""
    data = sock.recv(1)
    if not data:
        raise ConnectionError("Socket closed")
    return data[0]


def parse_packets(sock: socket.socket, duration: float = 30.0) -> None:
    """Read and parse ThinkGear packets for `duration` seconds."""
    t0 = time.time()
    packet_count = 0
    byte_count = 0
    last_report = t0

    print(f"Reading packets for {duration:.0f}s...\n")

    while time.time() - t0 < duration:
        try:
            # Sync: find two consecutive 0xAA bytes
            b = read_byte(sock)
            byte_count += 1
            if b != SYNC:
                continue
            b = read_byte(sock)
            byte_count += 1
            if b != SYNC:
                continue

            # Read payload length
            plen = read_byte(sock)
            byte_count += 1
            if plen > 169:
                continue

            # Read payload
            payload = bytearray()
            for _ in range(plen):
                payload.append(read_byte(sock))
                byte_count += 1

            # Read checksum
            chksum = read_byte(sock)
            byte_count += 1

            # Verify checksum
            calc = (~sum(payload) & 0xFF)
            if calc != chksum:
                continue

            packet_count += 1

            # Parse payload
            i = 0
            sq = None
            att = None
            med = None
            bands = None
            while i < len(payload):
                code = payload[i]
                i += 1
                if code >= 0x80:
                    vlen = payload[i]
                    i += 1
                    if code == CODE_EEG_POWER and vlen == 24:
                        bands = {}
                        for bi, name in enumerate(BAND_NAMES):
                            val = struct.unpack(">I", b"\x00" + payload[i + bi * 3:i + bi * 3 + 3])[0]
                            bands[name] = val
                    i += vlen
                else:
                    val = payload[i]
                    i += 1
                    if code == CODE_SIGNAL:
                        sq = val
                    elif code == CODE_ATTENTION:
                        att = val
                    elif code == CODE_MEDITATION:
                        med = val

            # Report
            elapsed = time.time() - t0
            parts = [f"t={elapsed:5.1f}s pkt#{packet_count:4d}"]
            if sq is not None:
                parts.append(f"sq={sq:3d}")
            if att is not None:
                parts.append(f"att={att:3d}")
            if med is not None:
                parts.append(f"med={med:3d}")
            if bands:
                total = sum(bands.values())
                parts.append(f"total={total:>10d}")
                parts.append(f"alpha1={bands['alpha1']:>8d}")
            print("  ".join(parts))

        except socket.timeout:
            elapsed = time.time() - t0
            print(f"  t={elapsed:5.1f}s  [read timeout — no data for {READ_TIMEOUT}s]")

        # Periodic summary
        now = time.time()
        if now - last_report > 10:
            elapsed = now - t0
            rate = byte_count / elapsed if elapsed > 0 else 0
            print(f"\n  --- {elapsed:.0f}s: {packet_count} packets, {byte_count} bytes ({rate:.0f} bytes/s) ---\n")
            last_report = now

    elapsed = time.time() - t0
    print(f"\nDone. {packet_count} packets, {byte_count} bytes in {elapsed:.1f}s")


def main():
    mac = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MAC
    print(f"MindWave BT Test — {mac}")
    print("=" * 50)

    try:
        sock = connect(mac)
    except Exception as e:
        print(f"CONNECT FAILED: {e}")
        sys.exit(1)

    try:
        parse_packets(sock, duration=30.0)
    except KeyboardInterrupt:
        print("\nInterrupted")
    except Exception as e:
        print(f"\nERROR: {e}")
    finally:
        sock.close()
        print("Socket closed")


if __name__ == "__main__":
    main()
