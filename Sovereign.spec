# -*- mode: python ; coding: utf-8 -*-
"""Freeze the whole Sovereign desktop into one windowed executable.

The Cockpit is primary and does the switching between topics, with S-Initiative
and S-Team mounted alongside it - the arrangement `all3_config.json`
described before the repository split.

Build from a checkout of this repository, with the other applications
installed from their own clones:

    pip install -e .[desktop]
    pip install -e ../s-initiative -e ../s-team
    pip install pyinstaller
    pyinstaller Sovereign.spec

The macOS CI job checks out the application repositories beside this one and
installs them from source before running this spec.

Licensing. Every Sovereign application is Apache-2.0, so combining them
crosses no boundary. `sovereign` is LGPL-3.0-or-later, so passing this
executable to anyone else carries that licence's notice and relinking
obligations. Building it for yourself is not distribution and carries none
of that.
"""
import sys

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
    "sovereign", "s_cockpit", "s_initiative", "s_team",
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

icon = (
    "packaging/sovereign.icns"
    if sys.platform == "darwin"
    else "packaging/sovereign.ico"
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Sovereign",
    # Without this PyInstaller stamps its own default. Both platform formats
    # use the aggregator's four squares, generated from the same geometry the
    # in-app header uses by tools/make_icon.py.
    icon=icon,
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

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="Sovereign.app",
        icon="packaging/sovereign.icns",
        bundle_identifier="org.sovereignprotocol.sovereign",
        info_plist={
            "CFBundleDisplayName": "Sovereign",
            "NSHighResolutionCapable": True,
        },
    )
