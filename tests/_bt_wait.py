"""The app's BtWait wired to an app built with __new__, as build() wires it: its name and main thread read the app when
used; the stream and the Session screen are the app's at construction."""
from app.ui.bt_wait import BtWait


def make_bt_wait(app, **deps) -> BtWait:
    defaults = {"headset_name": lambda: app._headset.name(), "on_main_for": lambda run, fn: app._on_main_for(run, fn)}
    return BtWait(app._real_stream, app._live_screen, **{**defaults, **deps})
