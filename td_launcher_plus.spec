# -*- mode: python ; coding: utf-8 -*-


block_cipher = None


a = Analysis(
    ['td_launcher.py'],
    pathex=[],
    binaries=[('toeexpand/toeexpand.exe', 'toeexpand'), ('test.toe', '.'), ('toeexpand/iconv.dll', 'toeexpand'), ('toeexpand/icudt59.dll', 'toeexpand'), ('toeexpand/icuuc59.dll', 'toeexpand'), ('toeexpand/libcurl.dll', 'toeexpand'), ('toeexpand/libcurl-x64.dll', 'toeexpand'), ('toeexpand/zlib1.dll', 'toeexpand')],
    datas=[('td_launcher_plus.ico', '.'), ('touchdesigner.png', '.')],
    hiddenimports=['PIL', 'PIL.Image', 'PIL.ImageOps'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='td_launcher_plus',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='td_launcher_plus.ico',
)
