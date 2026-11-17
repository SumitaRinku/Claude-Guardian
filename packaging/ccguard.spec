# PyInstaller spec for CCGuard.exe: windowed, folder build (the installer packs the folder).
# Build with: python tools/build_windows.py  (writes build/version_info.txt first)
import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
SKILL = ROOT / 'skills' / 'claude-guardian'
SCRIPTS = SKILL / 'scripts'
VERSION_FILE = ROOT / 'build' / 'version_info.txt'

a = Analysis(
    [str(ROOT / 'packaging' / 'ccguard_app.py')],
    pathex=[str(SCRIPTS)],
    datas=[(str(SKILL / 'assets' / 'monitor'), 'claude-guardian/assets/monitor')],
    # Imported lazily by monitor.py / the panel, so name them for the analysis.
    hiddenimports=['monitor', 'monitor_webview', 'monitor_gui', 'monitor_history', 'monitor_guide',
                   'ip_score', 'webview.platforms.winforms', 'webview.platforms.edgechromium', 'clr'],
    excludes=['yaml', 'unittest', 'pydoc', 'doctest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CCGuard',
    icon=str(SKILL / 'assets' / 'monitor' / 'icon-ok.ico'),
    version=str(VERSION_FILE) if VERSION_FILE.is_file() else None,
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name='CCGuard', upx=False)
