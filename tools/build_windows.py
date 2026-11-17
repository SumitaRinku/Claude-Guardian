#!/usr/bin/env python3
"""Build CCGuard.exe (PyInstaller) and, optionally, the per-user installer (Inno Setup 6).

  python tools/build_windows.py --version 0.5.0                     exe folder + self-test
  python tools/build_windows.py --version 0.5.0 --installer         + dist/CCGuard-Setup-0.5.0.exe
  python tools/build_windows.py --version 0.5.0 --installer --verify-installer
        + silent install into a temporary folder, self-test the installed exe, silent uninstall
        (CI runners only: it creates and removes a real per-user installation)

Outputs go to build/ and dist/ (both ignored by git). Windows only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'
DIST = ROOT / 'dist'
SPEC = ROOT / 'packaging' / 'ccguard.spec'
ISS = ROOT / 'packaging' / 'ccguard.iss'
APP_DIR = DIST / 'CCGuard'
ISCC_PATHS = (r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe', r'C:\Program Files\Inno Setup 6\ISCC.exe')


class BuildError(Exception):
    pass


def parse_version(text):
    """'0.5.0' or 'v0.5.0' -> ('0.5.0', (0, 5, 0, 0)); anything else is refused."""
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', str(text or '').strip())
    if not match:
        raise BuildError('版本号必须是 X.Y.Z：%r' % text)
    numbers = tuple(int(part) for part in match.groups())
    return '.'.join(map(str, numbers)), numbers + (0,)


def version_info(version, numbers):
    """PyInstaller version resource: shows up in the exe's Properties > Details."""
    strings = {
        'CompanyName': 'CCGuard', 'FileDescription': 'CCGuard', 'FileVersion': version,
        'InternalName': 'CCGuard', 'LegalCopyright': 'GPL-3.0-only', 'OriginalFilename': 'CCGuard.exe',
        'ProductName': 'CCGuard', 'ProductVersion': version,
    }
    entries = ',\n'.join('          StringStruct(%r, %r)' % item for item in strings.items())
    return '''VSVersionInfo(
  ffi=FixedFileInfo(filevers=%(n)r, prodvers=%(n)r, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('080404b0', [
%(entries)s])]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
''' % {'n': numbers, 'entries': entries}


def run(argv, **kwargs):
    print('$ ' + subprocess.list2cmdline([str(item) for item in argv]), flush=True)
    return subprocess.run([str(item) for item in argv], check=True, **kwargs)


def self_test(exe, report):
    """Run the exe's own bundle check and fail the build unless every item passed."""
    if report.exists():
        report.unlink()
    subprocess.run([str(exe), '--self-test', str(report)], timeout=180)
    if not report.is_file():
        raise BuildError('自检没有写出报告：' + str(exe))
    result = json.loads(report.read_text(encoding='utf-8'))
    failed = {key: value for key, value in result.get('checks', {}).items() if value is not True}
    if not result.get('ok') or not result.get('frozen') or failed:
        raise BuildError('自检未通过：%s' % (failed or result))
    print('self-test ok: %d checks' % len(result['checks']), flush=True)
    return result


def find_iscc(explicit=None):
    candidates = [explicit] if explicit else []
    candidates += [shutil.which('ISCC'), shutil.which('iscc')] + list(ISCC_PATHS)
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise BuildError('找不到 Inno Setup 6 的 ISCC.exe；安装 Inno Setup 6 或用 --iscc 指定')


def build_exe(version, numbers):
    BUILD.mkdir(exist_ok=True)
    (BUILD / 'version_info.txt').write_text(version_info(version, numbers), encoding='utf-8')
    run([sys.executable, '-m', 'PyInstaller', SPEC, '--noconfirm', '--clean',
         '--distpath', DIST, '--workpath', BUILD / 'pyinstaller'], cwd=ROOT)
    exe = APP_DIR / 'CCGuard.exe'
    if not exe.is_file():
        raise BuildError('PyInstaller 没有生成 ' + str(exe))
    self_test(exe, BUILD / 'self-test.json')
    return exe


def build_installer(version, iscc):
    run([iscc, '/Q', '/DAppVersion=' + version, '/DSourceDir=' + str(APP_DIR), ISS], cwd=ISS.parent)
    setup = DIST / ('CCGuard-Setup-%s.exe' % version)
    if not setup.is_file():
        raise BuildError('Inno Setup 没有生成 ' + str(setup))
    return setup


def wait_gone(path, seconds=90):
    deadline = time.time() + seconds
    while path.exists() and time.time() < deadline:
        time.sleep(1)
    return not path.exists()


def verify_installer(setup):
    """Silent per-user install into a temp folder, self-test it, then silent uninstall."""
    appdata = Path(os.environ['APPDATA'])
    start_menu = appdata / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'CCGuard.lnk'
    target = Path(tempfile.mkdtemp(prefix='ccguard-install-')) / 'CCGuard'
    log = BUILD / 'install.log'
    run([setup, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/TASKS=desktopicon',
         '/DIR=' + str(target), '/LOG=' + str(log)], timeout=300)
    installed = target / 'CCGuard.exe'
    if not installed.is_file():
        raise BuildError('安装后找不到 ' + str(installed))
    if not start_menu.is_file():
        raise BuildError('安装后没有开始菜单快捷方式：' + str(start_menu))
    self_test(installed, BUILD / 'installed-self-test.json')
    uninstaller = target / 'unins000.exe'
    run([uninstaller, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], timeout=300)
    if not wait_gone(installed):
        raise BuildError('卸载后程序仍在：' + str(installed))
    if not wait_gone(start_menu, 30):
        raise BuildError('卸载后开始菜单快捷方式仍在')
    print('installer verified: install, self-test, uninstall', flush=True)


def write_sums(files, version):
    lines = ['%s  %s' % (hashlib.sha256(path.read_bytes()).hexdigest(), path.name) for path in files]
    sums = DIST / ('SHA256SUMS-installer-%s.txt' % version)
    sums.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(sums.read_text(encoding='utf-8'), flush=True)
    return sums


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--version', required=True, help='X.Y.Z or vX.Y.Z')
    parser.add_argument('--installer', action='store_true', help='also build the Inno Setup installer')
    parser.add_argument('--verify-installer', action='store_true',
                        help='silently install, self-test and uninstall (CI only)')
    parser.add_argument('--iscc', help='path to ISCC.exe')
    args = parser.parse_args(argv)
    try:
        if sys.platform != 'win32':
            raise BuildError('只能在 Windows 上构建')
        version, numbers = parse_version(args.version)
        build_exe(version, numbers)
        if args.installer:
            setup = build_installer(version, find_iscc(args.iscc))
            if args.verify_installer:
                verify_installer(setup)
            write_sums([setup], version)
    except (BuildError, subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError) as error:
        sys.stderr.write('构建失败：%s\n' % error)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
