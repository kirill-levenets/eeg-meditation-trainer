"""The app's BtWait wired to an app built with __new__, as build() wires it: the callbacks read the app when they run;
the stream and the Session screen are the app's at construction."""
from app.ui.bt_wait import BtWait


def make_bt_wait(app, **deps) -> BtWait:
    defaults = {"headset_name": lambda: app._headset.name(), "on_main_for": lambda run, fn: app._on_main_for(run, fn),
                "start_session": lambda: app._start_on_first_data(),
                "on_connected": lambda name: app._on_session_connected(name), "abort": lambda: app._abort_bt_wait(),
                "undo_setup": lambda: app._undo_session_setup()}
    return BtWait(app._real_stream, app._live_screen, **{**defaults, **deps})
