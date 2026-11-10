"""The phone's paired devices, faked for every Headset scan."""
from types import SimpleNamespace

import app.ui.headset as headset
from app.eeg.neurosky_stream import NeuroSkyStream


def fake_paired(monkeypatch) -> SimpleNamespace:
    """`devices` is what a scan lists; its result waits in `queued` until `arrive()` lets it in, as the main thread
    would run it."""
    devices: list[dict] = []
    queued: list = []
    monkeypatch.setattr(NeuroSkyStream, "scan_paired_devices", staticmethod(lambda: list(devices)))
    monkeypatch.setattr(headset, "threading", SimpleNamespace(Thread=lambda target, **k: SimpleNamespace(start=target)))
    monkeypatch.setattr(headset, "Clock", SimpleNamespace(schedule_once=lambda cb, *a, **k: queued.append(cb)))

    def arrive() -> None:
        while queued:
            queued.pop(0)(0)

    return SimpleNamespace(devices=devices, queued=queued, arrive=arrive)
