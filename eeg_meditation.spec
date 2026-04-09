# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for EEG Meditation Trainer (Windows build).

Run on Windows:
    python -m PyInstaller eeg_meditation.spec
"""

import os
import sys
from os.path import dirname, join, basename
from pathlib import Path

# Prevent Kivy from initializing GL (fails on headless CI)
os.environ['KIVY_DOC'] = '1'

from kivy_deps import sdl2, glew
import kivy
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

PROJECT_ROOT = SPECPATH

# --- Kivy data: style.kv, fonts, shaders, modules ---
# Replicate what kivy.tools.packaging.pyinstaller_hooks.datas provides,
# without importing that module (it requires KIVY_DOC unset → GL init → crash on CI).
kivy_datas = [
    (kivy.kivy_data_dir, join('kivy_install', basename(kivy.kivy_data_dir))),
    (kivy.kivy_modules_dir, join('kivy_install', basename(kivy.kivy_modules_dir))),
]

# Runtime hook that sets KIVY_DATA_DIR / KIVY_MODULES_DIR in the frozen app
kivy_hooks_dir = join(dirname(kivy.__file__), 'tools', 'packaging', 'pyinstaller_hooks')
kivy_runtime_hooks = [join(kivy_hooks_dir, 'pyi_rth_kivy.py')]

# Collect all app submodules
app_hiddenimports = collect_submodules('app')

# Kivy hidden imports — collect safe subpackages individually
# (collect_submodules('kivy') fails because kivy.garden has non-standard path)
kivy_hiddenimports = []
for pkg in ['kivy.core', 'kivy.graphics', 'kivy.uix', 'kivy.input',
            'kivy.lang', 'kivy.lib', 'kivy.modules', 'kivy.network',
            'kivy.storage']:
    kivy_hiddenimports += collect_submodules(pkg)
kivy_hiddenimports += [
    'kivy.weakmethod',
    'kivy._clock',
    'kivy.cache',
    'kivy.context',
    'kivy.properties',
    'kivy.event',
    'kivy.factory',
    'kivy.clock',
    'kivy.base',
    'kivy.app',
    'win32timezone',
]

all_hiddenimports = app_hiddenimports + kivy_hiddenimports

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'main.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        (os.path.join(PROJECT_ROOT, 'app'), 'app'),
    ] + kivy_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=kivy_runtime_hooks,
    excludes=['tkinter', '_tkinter', 'unittest', 'pytest'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EEG_Meditation_Trainer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    *[Tree(p) for p in (sdl2.dep_bins + glew.dep_bins)],
    strip=False,
    upx=False,
    upx_exclude=[],
    name='EEG_Meditation_Trainer',
    contents_directory='.',
)