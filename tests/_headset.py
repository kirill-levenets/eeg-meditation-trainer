"""A Headset wired to an app built with __new__, as build() wires it; any dependency, or a context field, can be given
instead. The phone's paired devices, faked for every Headset scan."""
from types import SimpleNamespace

import app.ui.headset as headset
from app.eeg.neurosky_stream import NeuroSkyStream
from app.ui.headset import Headset
from tests._context import context_fields, make_context


def make_headset(app, **deps) -> Headset:
    """The app's db, headset stream, Settings device section and Session screen; its user, session refusal and BT wait
    read when they are needed."""
    ctx = make_context(app, **context_fields(deps))
    defaults = {"serial_override": lambda: getattr(app, "serial_device_override", None)}
    return Headset(ctx, app._real_stream, app._settings_screen.device, app._live_screen, **{**defaults, **deps})


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
