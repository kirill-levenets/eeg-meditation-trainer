#!/usr/bin/env python3
"""Scan MindWave Mobile 2 BLE services for battery level.

The MindWave Mobile 2 has a dual-mode BT module (Classic + BLE).
This script connects via BLE and enumerates all GATT services
to check if a Battery Service (0x180F) is available.

Usage:
    pip install bleak
    python tools/ble_battery_scan.py C4:64:E3:E8:CC:CA
    python tools/ble_battery_scan.py   # scans for MindWave first
"""
import asyncio
import sys

BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
DEFAULT_MAC = "C4:64:E3:E8:CC:CA"


async def scan_for_mindwave():
    """Scan for MindWave devices."""
    from bleak import BleakScanner
    print("Scanning for BLE devices (10s)...")
    devices = await BleakScanner.discover(timeout=10.0)
    mindwave = None
    for d in devices:
        name = d.name or ""
        print(f"  {d.address}  {name}  RSSI={d.rssi}")
        if "mindwave" in name.lower() or "neurosky" in name.lower():
            mindwave = d
    return mindwave


async def enumerate_services(address: str):
    """Connect via BLE and list all GATT services and characteristics."""
    from bleak import BleakClient
    print(f"\nConnecting to {address} via BLE...")
    async with BleakClient(address, timeout=15.0) as client:
        print(f"Connected: {client.is_connected}")
        print(f"\nGATT Services ({len(client.services.services)} total):")
        print("=" * 60)

        battery_found = False
        for service in client.services:
            # Highlight known services
            svc_name = ""
            svc_uuid_short = service.uuid[:8]
            if "180f" in service.uuid:
                svc_name = " ** BATTERY SERVICE **"
                battery_found = True
            elif "180a" in service.uuid:
                svc_name = " (Device Information)"
            elif "1800" in service.uuid:
                svc_name = " (Generic Access)"
            elif "1801" in service.uuid:
                svc_name = " (Generic Attribute)"

            print(f"\n  Service: {service.uuid}{svc_name}")
            for char in service.characteristics:
                props = ", ".join(char.properties)
                print(f"    Char: {char.uuid}  [{props}]")

                # Try to read readable characteristics
                if "read" in char.properties:
                    try:
                        value = await client.read_gatt_char(char.uuid)
                        if len(value) == 1:
                            print(f"           Value: {value[0]} (0x{value[0]:02x})")
                        elif len(value) <= 20:
                            text = value.decode("utf-8", errors="replace")
                            print(f"           Value: {value.hex()} = '{text}'")
                        else:
                            print(f"           Value: {value[:20].hex()}... ({len(value)} bytes)")
                    except Exception as e:
                        print(f"           Read error: {e}")

        print("\n" + "=" * 60)
        if battery_found:
            print("BATTERY SERVICE FOUND!")
            try:
                level = await client.read_gatt_char(BATTERY_LEVEL_UUID)
                print(f"Battery Level: {level[0]}%")
            except Exception as e:
                print(f"Could not read battery level: {e}")
        else:
            print("No Battery Service (0x180F) found.")
            print("Battery level is not available via BLE on this device.")


async def main():
    address = sys.argv[1] if len(sys.argv) > 1 else None

    if not address:
        device = await scan_for_mindwave()
        if device:
            address = device.address
            print(f"\nFound MindWave: {device.name} ({address})")
        else:
            address = DEFAULT_MAC
            print(f"\nNo MindWave found in scan, trying default: {address}")

    try:
        await enumerate_services(address)
    except Exception as e:
        print(f"\nBLE connection failed: {e}")
        print("Make sure the headset is on and not connected via Classic BT.")


if __name__ == "__main__":
    asyncio.run(main())
