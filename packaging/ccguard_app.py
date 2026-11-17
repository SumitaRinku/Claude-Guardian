"""Entry point of CCGuard.exe (PyInstaller, windowed).

  CCGuard.exe                      first run writes the config, then opens the panel with the tray
  CCGuard.exe gui --config ... --tray --start-hidden   what autostart and shortcuts run
  CCGuard.exe --self-test <file>   check the bundle without opening a window; writes JSON
"""
import io
import json
import sys
from pathlib import Path

APP_NAME = 'CCGuard'


def show_error(message):
    try:
        import tkinter.messagebox as messagebox
        messagebox.showerror(APP_NAME, message)
    except Exception:
        pass


def self_test(output):
    """Everything the panel needs at runtime, checked without a window or the network."""
    import monitor
    from version import __version__
    report = {'frozen': monitor.FROZEN, 'version': __version__, 'checks': {}}
    checks = report['checks']
    for name in ('monitor_webview', 'monitor_gui', 'monitor_history', 'monitor_guide', 'ip_score', 'app_update',
                 'version', 'webview', 'tkinter'):
        try:
            __import__(name)
            checks['import ' + name] = True
        except Exception as error:
            checks['import ' + name] = 'error: %s' % error
    for relative in ('panel.html', 'panel.css', 'panel.js', 'release-notes.json', 'fonts/NotoSansSC-VF.ttf', 'fonts/OFL.txt',
                     'tray.ps1', 'notifier-shortcut.ps1',
                     'icon-ok.ico', 'icon-fail.ico', 'logo-ok.png', 'logo-unknown.png'):
        checks['asset ' + relative] = (monitor.ICON_DIR / relative).is_file()
    try:
        import webview.platforms.winforms  # noqa: F401  (needs pythonnet and the .NET runtime)
        checks['import webview.platforms.winforms'] = True
    except Exception as error:
        checks['import webview.platforms.winforms'] = 'error: %s' % error
    import app_update
    notes = app_update.release_notes()
    checks['release notes match version'] = bool(notes) and notes[0]['version'] == __version__
    report['ok'] = all(value is True for value in checks.values())
    Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    return 0 if report['ok'] else 1


def main(argv):
    # Windowed builds have no console: give print() somewhere to go and keep errors to show.
    errors = io.StringIO()
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = errors
    try:
        if argv[:1] == ['--self-test']:
            return self_test(argv[1] if len(argv) > 1 else 'ccguard-self-test.json')
        import monitor
        if argv:
            code = monitor.main(argv)
            if code and errors.getvalue().strip():
                show_error(errors.getvalue().strip())
            return code
        cfg, config_path, _created = monitor.quickstart_config()
        from monitor_webview import launch
        launch(cfg, config_path, tray=True)
        return 0
    except Exception as error:
        show_error('CCGuard 启动失败：' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
