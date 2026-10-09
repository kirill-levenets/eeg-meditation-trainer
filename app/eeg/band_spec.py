"""The headset's bands (key, name, Hz range) in its ASIC_EEG_POWER (0x83) order, ranges per NeuroSky's ThinkGear protocol."""

from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class Band:
    key: str
    name: str
    low_hz: float
    high_hz: float
    group: str  # the grouped band's key


# The app's names (Alpha 1 for NeuroSky's "low-alpha", ...): the custom-formula variables and the manuals use them.
BANDS: tuple[Band, ...] = (
    Band("delta", "Delta", 0.5, 2.75, "delta"),
    Band("theta", "Theta", 3.5, 6.75, "theta"),
    Band("alpha1", "Alpha 1", 7.5, 9.25, "alpha"),
    Band("alpha2", "Alpha 2", 10.0, 11.75, "alpha"),
    Band("beta1", "Beta 1", 13.0, 16.75, "beta"),
    Band("beta2", "Beta 2", 18.0, 29.75, "beta"),
    Band("gamma1", "Gamma 1", 31.0, 39.75, "gamma"),
    Band("gamma2", "Gamma 2", 41.0, 49.75, "gamma"),
)

_GROUP_NAMES = {"delta": "Delta", "theta": "Theta", "alpha": "Alpha", "beta": "Beta", "gamma": "Gamma"}

# A grouped band spans its sub-bands, the usual way to show one, though the hardware's leave gaps (9.25-10 Hz, ...).
GROUPS: tuple[Band, ...] = tuple(
    Band(key, name, min(b.low_hz for b in BANDS if b.group == key), max(b.high_hz for b in BANDS if b.group == key),
         key)
    for key, name in _GROUP_NAMES.items()
)

BAND_KEYS: tuple[str, ...] = tuple(b.key for b in BANDS)
GROUP_KEYS: tuple[str, ...] = tuple(g.key for g in GROUPS)
GROUP_NAMES = MappingProxyType({g.key: g.name for g in GROUPS})


def range_text(band: Band) -> str:
    return f"{band.low_hz:g}–{band.high_hz:g} Hz"


def group_powers(power_of: Callable[[str], float]) -> dict[str, float]:
    """Each grouped band's power, the sum of its sub-bands', with `power_of(band_key)` read from wherever they're kept."""
    out = dict.fromkeys(GROUP_KEYS, 0.0)
    for band in BANDS:
        out[band.group] += power_of(band.key)
    return out
