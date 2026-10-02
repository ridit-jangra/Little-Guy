# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path('.').resolve()
src_path = root / 'src'
assets_path = root / 'assets'
server_path = root / 'server'
tools_path = root / 'tools'

a = Analysis(
    [str(src_path / 'main.py')],
    pathex=[str(src_path)],
    binaries=[],
    datas=[
        (str(assets_path), 'assets'),
        (str(server_path), 'server'),
        (str(tools_path), 'tools'),
        (str(root / 'templates'), 'templates'),
    ],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'keyring',
        'keyring.backends',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'watchfiles',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LittleGuy',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
