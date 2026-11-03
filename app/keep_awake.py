"""What keeps a session running on Android with the screen off: a partial wake lock (the CPU), the keep-screen-on flag,
and the session's foreground service, which runs in this process so the OS keeps the process up. No-ops off Android."""
from app import android_jni
from app.logger import logger

_SERVICE = "org.eeg.eegmeditation.SessionForegroundService"


class KeepAwake:
    """Held from a session's setup to its ending (`hold` / `release`); `stop_service` alone when the app closes."""

    def __init__(self) -> None:
        self._wake_lock = None

    def hold(self) -> None:
        self._acquire_wake_lock()
        self._start_service()

    def release(self) -> None:
        self._release_wake_lock()
        self.stop_service()

    def _acquire_wake_lock(self) -> None:
        """Keep CPU running + screen on during session (Android only)."""
        if not android_jni.on_android():
            return
        try:
            from android.runnable import run_on_ui_thread

            @run_on_ui_thread
            def _set_flag():
                from jnius import autoclass
                activity = android_jni.activity()
                WindowManager = autoclass("android.view.WindowManager$LayoutParams")
                activity.getWindow().addFlags(WindowManager.FLAG_KEEP_SCREEN_ON)
            _set_flag()

            # Partial wake lock keeps CPU alive when screen is off.
            from jnius import autoclass
            Context = autoclass("android.content.Context")
            PowerManager = autoclass("android.os.PowerManager")
            pm = android_jni.activity().getSystemService(Context.POWER_SERVICE)
            self._wake_lock = pm.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK, "eegmeditation:session"
            )
            self._wake_lock.acquire()
            logger.info("Wake lock acquired (partial + screen-on).")
        except Exception as e:
            logger.warning(f"Failed to acquire wake lock: {e}")

    def _release_wake_lock(self) -> None:
        """Release wake locks (Android only)."""
        if not android_jni.on_android():
            return
        try:
            if self._wake_lock is not None:
                try:
                    self._wake_lock.release()
                except Exception as e:  # already released by Android; the flag still clears below
                    logger.warning(f"Wake lock release failed: {e}")
                self._wake_lock = None
            from android.runnable import run_on_ui_thread

            @run_on_ui_thread
            def _clear_flag():
                from jnius import autoclass
                activity = android_jni.activity()
                WindowManager = autoclass("android.view.WindowManager$LayoutParams")
                activity.getWindow().clearFlags(WindowManager.FLAG_KEEP_SCREEN_ON)
            _clear_flag()
            logger.info("Wake lock released.")
        except Exception as e:
            logger.warning(f"Failed to release wake lock: {e}")

    def _start_service(self) -> None:
        """Start the session's foreground service: it runs in this process, so the OS keeps this process up."""
        if not android_jni.on_android():
            return
        try:
            from jnius import autoclass
            autoclass(_SERVICE).start(android_jni.activity(), "EEG Meditation", "Meditation session in progress")
            logger.info("Session foreground service started.")
        except Exception as e:
            logger.warning(f"Failed to start the session foreground service: {e}")

    def stop_service(self) -> None:
        if not android_jni.on_android():
            return
        try:
            from jnius import autoclass
            autoclass(_SERVICE).stop(android_jni.activity())
            logger.info("Session foreground service stopped.")
        except Exception as e:
            logger.warning(f"Failed to stop the session foreground service: {e}")
