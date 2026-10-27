"""A Headset wired to an app built with __new__, as build() wires it; any dependency can be given instead. The phone's
paired devices, faked for every Headset scan."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import app.ui.headset as headset
from app.eeg.neurosky_stream import NeuroSkyStream
from app.ui.headset import Headset


def make_headset(app, **deps) -> Headset:
    """The app's db, headset stream, Settings device section and Session screen; its user, session refusal and BT wait
    read when they are needed."""
    defaults = {"user_id": lambda: app._current_user_id,
                "refused_while_session_runs": lambda doing: app._refused_while_session_runs(doing),
                "waiting_for_bt": lambda: app._waiting_for_bt,
                "session_live": lambda: app._session_pipeline_live(),
                "serial_override": lambda: getattr(app, "serial_device_override", None), "report": MagicMock()}
    return Headset(getattr(app, "_db", None) or MagicMock(), app._real_stream, app._settings_screen.device,
                   app._live_screen, **{**defaults, **deps})


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
