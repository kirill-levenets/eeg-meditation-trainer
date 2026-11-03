"""A short non-blocking confirmation: the theme's panel above any popup, or Android's own toast while the app is
leaving, the one thing still seen then."""
from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp

from app import android_jni
from app.logger import logger
from app.ui.theme import C, F, ThemedLabel, paint_panel


def show_toast(message: str) -> None:
    """The message on the theme's modal panel, above any popup, gone after a moment."""
    lbl = ThemedLabel(text=message, font_size=F.BODY, color=C.TEXT, size_hint=(None, None), padding=(dp(16), dp(10)))
    lbl.texture_update()
    lbl.size = lbl.texture_size
    lbl.pos = ((Window.width - lbl.width) / 2, Window.height * 0.12)
    paint_panel(lbl)
    Window.add_widget(lbl)
    fade = Animation(opacity=0, duration=0.4)
    fade.bind(on_complete=lambda *_a: Window.remove_widget(lbl))
    Clock.schedule_once(lambda _dt: fade.start(lbl), 1.6)


def android_toast(message: str) -> None:
    """Android's own short toast; a logged no-op off Android."""
    if not android_jni.on_android():
        logger.debug(f"toast: {message}")
        return
    try:
        from android.runnable import run_on_ui_thread

        @run_on_ui_thread
        def _show():
            from jnius import autoclass
            Toast = autoclass("android.widget.Toast")
            Toast.makeText(android_jni.activity(), android_jni.java_string(message), Toast.LENGTH_SHORT).show()
        _show()
    except Exception as e:
        logger.warning(f"Toast failed: {e}")
