"""What the app calls a headset: the name its user gave it, else its Bluetooth name. Every MindWave advertises the same
Bluetooth name, so lists show the address too."""

from collections.abc import Mapping

MAX_DEVICE_ALIAS = 24  # with the address, still one line in the device list


def device_label(address: str, name: str, aliases: Mapping[str, str]) -> str:
    return aliases.get(address) or name or address


def device_row_text(label: str, address: str) -> str:
    return f"{label}  ({address})"
