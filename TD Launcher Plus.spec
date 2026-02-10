# -*- mode: python ; coding: utf-8 -*-

# Configured for Apple Silicon (arm64) architecture.
# This is the current and future Mac architecture.

a = Analysis(
    ['td_launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('test.toe', '.'),
        ('td_launcher_plus.icns', '.'),
        ('td_launcher_plus.ico', '.'),
        ('touchdesigner.png', '.')
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TD Launcher Plus',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['td_launcher_plus.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TD Launcher Plus',
)
app = BUNDLE(
    coll,
    name='TD Launcher Plus.app',
    icon='td_launcher_plus.icns',
    bundle_identifier='com.function-store.td-launcher-plus',
    info_plist={
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeName': 'TouchDesigner Environment File',
                'CFBundleTypeRole': 'Editor',
                'LSHandlerRank': 'Alternate',
                'CFBundleTypeIconFile': 'td_launcher_plus.icns',
                'LSItemContentTypes': ['ca.derivative.toe'],
                'LSTypeIsPackage': False,
                'CFBundleTypeExtensions': ['toe']
            }
        ],
        'UTImportedTypeDeclarations': [
            {
                'UTTypeIdentifier': 'ca.derivative.toe',
                'UTTypeDescription': 'TouchDesigner Environment File',
                'UTTypeConformsTo': ['public.audiovisual-content', 'public.data'],
                'UTTypeTagSpecification': {
                    'public.filename-extension': ['toe']
                }
            }
        ],
        'CFBundleDisplayName': 'TD Launcher Plus',
        'CFBundleGetInfoString': 'TD Launcher Plus - TouchDesigner Project Launcher',
        'CFBundleShortVersionString': '2.1.2',
        'CFBundleVersion': '2.1.2',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.9.0'
    }
)
