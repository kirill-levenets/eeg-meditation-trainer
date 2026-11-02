"""The app's SessionWatch wired to an app built with __new__, as build() wires it: the callbacks read the app when they
run; the streams, screens and audio are the app's at construction."""
from app.ui.session_watch import SessionWatch


def make_watch(app, **deps) -> SessionWatch:
    defaults = {"on_main": lambda fn: app._on_main(fn),
                "end_session": lambda run, reason, alert: app._end_from_tick(run, reason, alert)}
    return SessionWatch(app._real_stream, app._session_manager, app._audio, app._live_screen,
                        getattr(app, "_headset", None), **{**defaults, **deps})
