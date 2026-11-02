"""The app's SessionWatch wired to an app built with __new__, as build() wires it: its main thread reads the app when
used; the stream, audio, Session screen and headset are the app's at construction."""
from app.ui.session_watch import SessionWatch


def make_watch(app, **deps) -> SessionWatch:
    return SessionWatch(app._real_stream, app._audio, app._live_screen, getattr(app, "_headset", None),
                        **{"on_main": lambda fn: app._on_main(fn), **deps})
