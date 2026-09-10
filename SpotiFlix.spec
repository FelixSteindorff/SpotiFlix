# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # Die NVDA-Controller-DLLs müssen mit ins Bundle: nvda.py sucht sie neben
    # der Exe bzw. im _MEIPASS-Ordner, sonst bleibt die Sprachausgabe stumm,
    # falls NVDA sie nicht über den PATH bereitstellt.
    datas=[
        ('librespot.exe', '.'),
        # Lizenz und Drittanbieter-Hinweise müssen mit ausgeliefert werden.
        ('LICENSE', '.'),
        ('THIRD_PARTY_NOTICES.md', '.'),
        # Übersetzungskataloge: i18n.locale_dir() sucht sie im Bundle-Ordner.
        ('locale', 'locale'),
        ('nvdaControllerClient32.dll', '.'),
        ('nvdaControllerClient64.dll', '.'),
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
    name='SpotiFlix',
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
    name='SpotiFlix',
)
