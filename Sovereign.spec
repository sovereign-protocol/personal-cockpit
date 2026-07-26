# -*- mode: python ; coding: utf-8 -*-
"""Freeze the whole Sovereign desktop into one windowed executable.

The Cockpit is primary and does the switching between topics, with S-Kanban
and S-Agreement mounted alongside it - the arrangement `all3_config.json`
described before the repository split.

Build from a checkout of this repository, with the other applications
installed from their own clones:

    pip install -e .[desktop]
    pip install -e ../s-kanban -e ../s-agreement
    pip install pyinstaller
    pyinstaller Sovereign.spec

This is deliberately not a CI job. Neither S-Kanban nor S-Agreement resolves
from an index yet, so a runner cannot build it; S-Kanban's own repository
keeps a single-application spec that CI does exercise, which is what stops
the spec format rotting.

Licensing. Every Sovereign application is Apache-2.0, so combining them
crosses no boundary. `sovereign` is LGPL-3.0-or-later, so passing this
executable to anyone else carries that licence's notice and relinking
obligations. Building it for yourself is not distribution and carries none
of that.
"""
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
# webview pulls its platform backend in dynamically, so static analysis alone
# leaves the frozen build without a window to draw into. The applications are
# named here rather than discovered, because the host imports them by name at
# runtime and PyInstaller cannot see through that.
for package in (
    "uvicorn", "webview",
    "sovereign", "personal_cockpit", "s_kanban", "s_agreement",
):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports


a = Analysis(
    ["desktop_main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name="Sovereign",
    # Without this PyInstaller stamps its own default, which is why the build
    # showed a diskette. The mark is the aggregator's four squares, generated
    # from the same geometry the in-app header uses by tools/make_icon.py.
    # On Windows the window and taskbar take their icon from the executable,
    # so this covers the titlebar too.
    icon="packaging/sovereign.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # The point of this build: its own window, and no console behind it.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
