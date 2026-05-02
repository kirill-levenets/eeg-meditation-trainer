"""Foreground service: keeps the process group at FOREGROUND priority during a session.

This script runs as a separate Python interpreter launched by python-for-android's
service template. It intentionally does nothing — its only purpose is to exist, so
that Android's OOM killer leaves the main activity process alone.

Auto-restart is INTENTIONALLY DISABLED. With `setAutoRestartService(True)` Android
revived the service after the user force-closed the app, leaving a zombie python
process that collided with the next activity launch and produced a black screen on
restart. The service should die with the activity.
"""

import time

while True:
    time.sleep(60)
