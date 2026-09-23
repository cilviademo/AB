# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the AB engine.

onedir, not onefile: onefile unpacks to %TEMP% on every launch and is a
reliable way to get flagged by antivirus. console=True because the shell talks
to it over stdio; the shell spawns it with CREATE_NO_WINDOW so no window shows.

    cd engine && python -m PyInstaller ab-engine.spec --noconfirm
"""
from pathlib import Path

ROOT = Path(SPECPATH)
PACKAGE = ROOT / "ab_engine"

datas = [(str(PACKAGE / "contracts" / "schemas"), "ab_engine/contracts/schemas")]
hiddenimports = ["jsonschema", "jsonschema_specifications", "referencing", "rpds", "sqlite3", "winreg"]

a = Analysis([str(PACKAGE / "__main__.py")], pathex=[str(ROOT)], binaries=[], datas=datas,
             hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
             excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "pytest", "_pytest", "setuptools", "pip"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ab-engine", debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ab-engine")
