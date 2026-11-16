"""Double-click launcher for CCGuard: no console, no command line, quickstart by default."""
import sys
from pathlib import Path

APP_NAME = 'CCGuard'


def locate_scripts(base=None):
    """Find monitor.py in the repository layout or the extracted release package."""
    here = Path(base) if base is not None else Path(__file__).resolve().parent
    candidates = (
        here / 'skills' / 'claude-guardian' / 'scripts',
        here / 'scripts',
        here / 'claude-guardian' / 'scripts',
    )
    for candidate in candidates:
        if (candidate / 'monitor.py').is_file():
            return candidate
    return None


def notify(message, error=False):
    try:
        import tkinter.messagebox as messagebox
        (messagebox.showerror if error else messagebox.showinfo)(APP_NAME, message)
    except Exception:
        pass


def main():
    scripts = locate_scripts()
    if scripts is None:
        notify('找不到 CCGuard 的 scripts 目录。请完整解压压缩包，或从仓库根目录运行。', True)
        return 1
    sys.path.insert(0, str(scripts))
    try:
        import monitor
        cfg, config_path, _created = monitor.quickstart_config()
        from monitor_gui import run
        run(cfg, config_path, tray=True)
        return 0
    except Exception as error:
        notify('CCGuard 启动失败：' + str(error), True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
