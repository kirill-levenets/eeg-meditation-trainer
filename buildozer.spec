[app]

# (str) Title of your application
title = EEG Meditation Trainer

# (str) Package name
package.name = eegmeditation

# (str) Package domain (needed for android/ios packaging)
package.domain = org.eeg

# (str) Source code where the main.py live
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,wav

# (list) Source files to exclude (let empty to not exclude anything)
source.exclude_exts =

# (list) List of directory to exclude (let empty to not exclude anything)
source.exclude_dirs = tests,venv,.git,__pycache__,.buildozer

# (list) List of exclusions using pattern matching
source.exclude_patterns = *.db,*.db-shm,*.db-wal,*.csv,*.pyc

# (str) Application versioning
version = 1.0.0

# (list) Application requirements
requirements = python3,kivy==2.3.0,android

# (str) Supported orientation (landscape, sensorLandscape, portrait, sensorPortrait, all)
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (list) Permissions
android.permissions = BLUETOOTH,BLUETOOTH_ADMIN,BLUETOOTH_CONNECT,BLUETOOTH_SCAN,ACCESS_FINE_LOCATION

# (int) Target Android API
android.api = 33

# (int) Minimum API your APK / AAB will support.
android.minapi = 21

# (str) Android NDK version to use
android.ndk = 25b

# (int) Android NDK API to use
android.ndk_api = 21

# (str) The Android arch to build for
android.archs = arm64-v8a,armeabi-v7a

# (bool) Enable AndroidX support
android.enable_androidx = True

# (str) python-for-android branch to use
p4a.branch = master

# (str) Bootstrap to use for android builds
p4a.bootstrap = sdl2

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, is the default)
warn_on_root = 1
