# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for EEG Meditation Trainer (Windows build).

Run on Windows:
    python -m PyInstaller eeg_meditation.spec
"""

import os
import sys
from pathlib import Path

from kivy_deps import sdl2, glew
from kivy.tools.packaging.pyinstaller_hooks import (
    runtime_hooks as kivy_runtime_hooks,
)
from kivy.tools.packaging.pyinstaller_hooks import datas as kivy_datas
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

PROJECT_ROOT = SPECPATH

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
    runtime_hooks=kivy_runtime_hooks(),
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
