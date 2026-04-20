"""Foreground service: keeps the process group at FOREGROUND priority during a session.

This script runs as a separate Python interpreter launched by python-for-android's
service template. It intentionally does nothing — its only purpose is to exist, so
that Android's OOM killer leaves the main activity process alone.
"""

import time

try:
    from jnius import autoclass
    PythonService = autoclass("org.kivy.android.PythonService")
    PythonService.mService.setAutoRestartService(True)
except Exception:
    pass

while True:
    time.sleep(60)
