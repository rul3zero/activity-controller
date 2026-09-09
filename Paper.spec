# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('ui/index.html', 'ui')],
    hiddenimports=['pynput.keyboard._darwin', 'pynput.mouse._darwin'],
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
    name='Paper',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Paper',
)
app = BUNDLE(
    coll,
    name='Paper.app',
    icon='assets/Paper.icns',
    bundle_identifier='com.rul3zero.paper',
    info_plist={
        'CFBundleDisplayName': 'Paper',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1',
        'LSUIElement': True,
        'NSHighResolutionCapable': True,
        'NSPrincipalClass': 'NSApplication',
    },
)
