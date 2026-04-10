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
source.include_exts = py,png,jpg,kv,atlas,wav,ttf

# (list) Source files to exclude (let empty to not exclude anything)
source.exclude_exts =

# (list) List of directory to exclude (let empty to not exclude anything)
source.exclude_dirs = tests,venv,.git,__pycache__,.buildozer,docs,tools,.claude,bin

# (list) List of exclusions using pattern matching
source.exclude_patterns = *.db,*.db-shm,*.db-wal,*.csv,*.pyc,*.eeg,*.ods,*.md,*.sh,*.bat,*.spec,*.txt

# (str) Application versioning
version = 1.0.0

# (str) Presplash of the application
presplash.filename = app/assets/icons/presplash.png

# (str) Icon of the application
icon.filename = app/assets/icons/icon_512.png

# (list) Application requirements
requirements = python3,kivy==2.3.0,pyjnius,android

# (str) Supported orientation (landscape, sensorLandscape, portrait, sensorPortrait, all)
orientation = portrait, landscape

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (list) Permissions
# BLUETOOTH/BLUETOOTH_ADMIN: BT Classic on Android <12
# BLUETOOTH_CONNECT/BLUETOOTH_SCAN: BT on Android 12+
# ACCESS_FINE_LOCATION: required by Android 6-11 for BT scanning (not used for actual location)
# WRITE/READ_EXTERNAL_STORAGE: CSV export to /sdcard on Android <11
android.permissions = BLUETOOTH,BLUETOOTH_ADMIN,BLUETOOTH_CONNECT,BLUETOOTH_SCAN,ACCESS_FINE_LOCATION,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

# (int) Target Android API
android.api = 33

# (int) Minimum API your APK / AAB will support.
android.minapi = 21

# (str) Android NDK version to use
android.ndk = 25b

# (int) Android NDK API to use
android.ndk_api = 21

# (str) The Android arch to build for
# arm64-v8a only: cuts APK nearly in half (~18MB vs ~36MB)
# armeabi-v7a is for old 32-bit devices (pre-2017); remove if not needed
android.archs = arm64-v8a

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
