"""WebView desktop panel for the read-only monitor (pywebview + Edge WebView2).

The page talks to Python only through the pywebview JS bridge (no HTTP server, no port).
When pywebview or WebView2 is unavailable the caller falls back to the tkinter panel.
"""
import base64
import os
from pathlib import Path
import platform
import shutil
import tempfile
import threading
import time

import monitor as engine
import monitor_gui as shared
import ip_score
import monitor_guide
import monitor_history

PAGE = engine.ICON_DIR / 'panel.html'
# Supplied Latin fonts the page may load (wordmark and check codes). Body text stays on the
# CSS CJK stack, so a Latin-only face never ends up under Chinese labels.
PAGE_FONT_PREFIXES = ('Anthropic Serif', 'Anthropic Mono')
PAGE_FONT_LIMIT = 4 * 1024 * 1024
INSTALL_HINT = 'python -m pip install pywebview'
DAY = 86400
HISTORY_WINDOWS = (DAY, 7 * DAY)


def set_native_icon(window, state_name):
    """Title-bar/taskbar icon from the state .ico (WinForms would show python.exe's icon)."""
    if platform.system() != 'Windows':
        return False
    try:
        import ctypes
        hwnd = int(window.native.Handle.ToInt64())
        path = str(engine.ICON_DIR / ('icon-' + state_name + '.ico'))
        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)
        for kind, size in ((0, 16), (1, 32)):  # ICON_SMALL, ICON_BIG
            handle = user32.LoadImageW(None, path, 1, size, size, 0x10)
            if handle:
                user32.SendMessageW(ctypes.c_void_p(hwnd), 0x0080, ctypes.c_void_p(kind), ctypes.c_void_p(handle))
        return True
    except Exception:
        return False


ASK_CLOSE_JS = '!!(window.CCGuard && (window.CCGuard.askClose(), true))'


def closing_handler(window, flags, start=None):
    """Handler for pywebview's `closing` event.

    pywebview runs it synchronously on the window's UI thread, while `evaluate_js` waits for that
    same thread: calling it here deadlocked the window when the user clicked close. So the handler
    only cancels the close and asks the page from another thread; the page answers through
    `PanelApi.close`. If the page cannot ask (not loaded, bridge gone), the window closes.
    """
    start = start or (lambda job: threading.Thread(target=job, daemon=True).start())

    def ask():
        try:
            asked = window.evaluate_js(ASK_CLOSE_JS)
        except Exception:
            asked = False
        if not asked:
            flags['exit'] = True
            try:
                window.destroy()
            except Exception:
                pass

    def on_closing():
        if flags['exit']:
            return True
        start(ask)
        return False

    return on_closing


class Unavailable(Exception):
    """pywebview or the Edge WebView2 runtime cannot show the panel."""


def page_fonts(files):
    """[{family, data}] for supplied wordmark/code fonts, base64 for the page's FontFace API."""
    fonts, seen = [], set()
    for path in files:
        family = shared.font_family(path)
        if not family or family in seen or not family.startswith(PAGE_FONT_PREFIXES):
            continue
        try:
            data = Path(path).read_bytes()
        except OSError:
            continue
        if len(data) > PAGE_FONT_LIMIT:
            continue
        seen.add(family)
        fonts.append({'family': family, 'data': base64.b64encode(data).decode('ascii')})
    return fonts


def row_view(row):
    return dict(row, state_text=shared.STATE_TEXT.get(row['state'], row['state']))


def fit_size(window_size, inner_size, needed_size, screen_size, margin=0.94):
    """Outer window size that gives the page exactly needed_size, kept on screen."""
    width = window_size[0] + needed_size[0] - inner_size[0]
    height = window_size[1] + needed_size[1] - inner_size[1]
    if screen_size:
        width = min(width, int(screen_size[0] * margin))
        height = min(height, int(screen_size[1] * margin))
    return int(width), int(height)


class PanelApi:
    """Methods the page calls. Everything else is private so pywebview does not expose it."""

    def __init__(self, cfg, config_path, store, tray_alive=lambda: False, autostart=None,
                 open_file=None, clock=time.time, history=None, screen=None,
                 score_check=None, open_url=None):
        self._cfg = cfg
        self._score_check = score_check or ip_score.check
        self._open_url = open_url
        self._ip = None
        self._ip_lock = threading.Lock()
        self._history = history
        self._screen = screen
        self._config_path = Path(config_path)
        self._store = store
        self._tray_alive = tray_alive
        self._autostart = autostart or {
            'status': engine.autostart_status,
            'enable': lambda: engine.enable_autostart(self._config_path),
            'disable': engine.disable_autostart,
        }
        self._open_file = open_file or getattr(os, 'startfile', None)
        self._clock = clock
        self._log = shared.LogBuffer()
        self._states = {}
        self._lock = threading.Lock()
        self._window = None
        self._on_close = None
        self._notice = None

    # ---- called from Python ----
    def _bind(self, window, on_close):
        self._window, self._on_close = window, on_close

    def _observe(self):
        """Turn state changes into log rows; returns the events for the caller to surface."""
        current = engine.states_of(self._store.read())
        with self._lock:
            events = engine.transitions(self._states, current)
            for event in events:
                self._log.add('状态', shared.event_text(event), event['to'])
            self._states = current
        return events

    def _note(self, kind, text, level='info'):
        with self._lock:
            self._log.add(kind, text, level)

    def _record(self):
        state = self._store.read()
        if self._history is not None and state.get('checked_at'):
            self._history.record(engine.states_of(state))

    def _records(self, window):
        if self._history is None:
            return []
        return self._history.snapshot(self._clock() - window)

    # ---- called from the page ----
    def snapshot(self, since=0):
        self._observe()
        state = self._store.read()
        rows = [row_view(row) for row in shared.build_rows(state)]
        stamp = state.get('checked_at') or 0
        overall = state.get('overall', 'unknown') if stamp else 'unknown'
        headline, detail = shared.banner_text(overall, stamp, rows)
        flagged = shared.problems(rows)
        with self._lock:
            total = self._log.total
            rows_log = self._log.snapshot()
        fresh = total - int(since or 0)
        rebuild = fresh > len(rows_log) or fresh < 0
        tail = rows_log if rebuild else (rows_log[len(rows_log) - fresh:] if fresh > 0 else [])
        notice, self._notice = self._notice, None
        return {
            'overall': overall,
            'checked_at': stamp,
            'rows': rows,
            'headline': headline,
            'detail': detail,
            'problems': len(flagged),
            'worst': flagged[0]['state'] if flagged else 'ok',
            'log': {'total': total, 'rebuild': rebuild,
                    'rows': [{'time': t, 'kind': k, 'text': x, 'level': lv} for t, k, x, lv in tail]},
            'notice': notice,
        }

    def detail(self, check_id):
        """Card detail: what is checked, what to do now, and the last 24 hours of this check."""
        if check_id not in engine.CHECK_IDS:
            return None
        state = self._store.read()
        row = next((item for item in shared.build_rows(state) if item['id'] == check_id),
                   {'id': check_id, 'label': shared.LABELS[check_id], 'state': 'unknown', 'code': '—'})
        raw = next((item for item in state.get('checks', []) if item.get('id') == check_id), {})
        records = self._records(DAY)
        now = self._clock()
        return dict(row_view(row), **monitor_guide.guide(check_id, row['state'], row['code']),
                    source=raw.get('source', ''), evidence=list(raw.get('evidence') or []),
                    now=now, window=DAY,
                    segments=monitor_history.timeline(records, now, DAY, [check_id])[check_id],
                    changed_at=monitor_history.last_change(records, check_id))

    def timeline(self, span=DAY):
        # Parameter names become JS parameter names in pywebview's generated stub; one named
        # `window` would shadow the global and break the call.
        span = int(span) if int(span or 0) in HISTORY_WINDOWS else DAY
        now = self._clock()
        segments = monitor_history.timeline(self._records(span), now, span, engine.CHECK_IDS)
        return {'now': now, 'window': span,
                'rows': [{'id': check_id, 'label': shared.LABELS[check_id], 'segments': segments[check_id]}
                         for check_id in engine.CHECK_IDS]}

    def fit(self, needed_width, needed_height, inner_width, inner_height):
        """Resize the window so the page content fits exactly (sizes in CSS pixels)."""
        window = self._window
        if window is None:
            return {'ok': False}
        try:
            width, height = fit_size((window.width, window.height), (inner_width, inner_height),
                                     (needed_width, needed_height), self._screen)
            window.resize(width, height)
        except Exception:
            return {'ok': False}
        return {'ok': True, 'width': width, 'height': height}

    def check_ip(self):
        """Exit IP trust score, only on the user's click (two requests, neither to Claude)."""
        if not self._ip_lock.acquire(blocking=False):
            return {'busy': True}
        try:
            result = self._score_check()
        finally:
            self._ip_lock.release()
        self._ip = result
        if result.get('ok'):
            self._note('出口', '信任分 %s（%s）' % (result['score'], result['label']), result['level'])
        else:
            self._note('出口', '出口评分检测失败：' + str(result.get('error')), 'unknown')
        return result

    def ip_result(self):
        return self._ip

    def open_ip_detail(self):
        """Open the full check in the user's own browser; the panel never loads that page."""
        opener = self._open_url
        if opener is None:
            import webbrowser
            opener = webbrowser.open
        try:
            opened = opener(ip_score.DETAIL_URL)
        except Exception:
            opened = False
        if opened is False:
            return {'ok': False, 'message': '无法打开浏览器：' + ip_score.DETAIL_URL}
        return {'ok': True, 'message': '已在浏览器打开详情'}

    def settings(self):
        alerts = self._cfg['alerts']
        return {'interval': alerts['interval_seconds'], 'cooldown': alerts['cooldown_seconds'],
                'notify': {name: name in alerts['notify_states'] for name in ('fail', 'degraded', 'unknown')},
                'paused': bool(alerts.get('paused'))}

    def apply(self, form, save=False):
        form = form or {}
        try:
            shared.apply_settings(self._cfg, form.get('interval'), form.get('cooldown'),
                                  dict(form.get('notify') or {}), bool(form.get('paused')))
        except engine.MonitorError as error:
            return {'ok': False, 'message': '设置未生效：' + str(error)}
        alerts = self._cfg['alerts']
        self._note('设置', '间隔 %ss，冷却 %ss%s' % (alerts['interval_seconds'], alerts['cooldown_seconds'],
                                                 '，提醒已暂停' if alerts['paused'] else ''))
        if save:
            try:
                shared.save_config(self._config_path, self._cfg)
            except (OSError, engine.MonitorError) as error:
                return {'ok': False, 'message': '保存失败，原配置未改动：' + str(error)}
        self._store.refresh_async()
        return {'ok': True, 'message': '已写入配置文件' if save else '设置已生效（本次运行）'}

    def refresh(self):
        started = self._store.refresh_async()
        return {'ok': started, 'message': '已触发一次采集' if started else '上一次采集尚未完成'}

    def autostart_status(self):
        try:
            return {'enabled': bool(self._autostart['status']().get('enabled'))}
        except Exception:
            return {'enabled': False}

    def set_autostart(self, enabled):
        try:
            self._autostart['enable' if enabled else 'disable']()
        except engine.MonitorError as error:
            return {'ok': False, 'enabled': not enabled, 'message': '开机自启未变更：' + str(error)}
        self._note('启动', '已开启开机自启' if enabled else '已关闭开机自启')
        return {'ok': True, 'enabled': bool(enabled),
                'message': '已开启开机自启' if enabled else '已关闭开机自启'}

    def open_config(self):
        try:
            if self._open_file is None:
                raise OSError
            self._open_file(str(self._config_path))
        except OSError:
            return {'ok': False, 'message': '无法打开配置文件：' + str(self._config_path)}
        return {'ok': True, 'message': '已打开配置文件'}

    def clear_log(self):
        with self._lock:
            self._log.clear()
            return {'ok': True, 'total': self._log.total, 'message': '日志已清空'}

    def log_text(self):
        with self._lock:
            return '\n'.join('%s  [%s]  %s' % row[:3] for row in self._log.snapshot())

    def fonts(self):
        return page_fonts(shared.font_files())

    def close_choices(self):
        return list(shared.close_choices(self._tray_alive()))

    def close(self, choice):
        if choice not in self.close_choices() or choice is None:
            return {'ok': False}
        if choice == 'hide':
            self._note('面板', '已隐藏到托盘，监测继续')
        if self._on_close is not None:
            self._on_close(choice)
        return {'ok': True}


def webview_module():
    try:
        import webview
    except ImportError:
        raise Unavailable('未安装 pywebview（' + INSTALL_HINT + '）') from None
    return webview


def run(cfg, config_path, tray=False, start_hidden=False, webview=None):
    """Show the WebView panel; raises Unavailable before any window exists if it cannot."""
    webview = webview or webview_module()
    if not PAGE.is_file():
        raise Unavailable('缺少面板页面 ' + str(PAGE))
    if not shared.acquire_single_instance():
        shared.already_running()
        return
    shared.set_app_id()

    state_dir = Path(tempfile.mkdtemp(prefix='guardian-monitor-web-'))
    state_path = state_dir / 'state.json'
    show_path = state_dir / 'show.request'
    store = engine.Store(cfg, state_path)
    box = {'child': engine.spawn_tray(state_path, '', cfg, show_file=show_path)
           if tray and platform.system() == 'Windows' else None}

    def tray_alive():
        return box['child'] is not None and box['child'].poll() is None

    history = monitor_history.History(monitor_history.history_path(config_path)).open()
    try:
        screen = (webview.screens[0].width, webview.screens[0].height)
    except Exception:
        screen = None
    api = PanelApi(cfg, config_path, store, tray_alive=tray_alive, history=history, screen=screen)
    hidden = bool(start_hidden and tray_alive())
    window = webview.create_window(
        engine.APP_NAME, url=PAGE.as_uri(), js_api=api, width=980, height=700,
        min_size=(720, 460), background_color='#f7f4ef', hidden=hidden, text_select=True)
    flags = {'exit': False, 'visible': not hidden, 'shown': False}

    def on_shown():
        flags['shown'] = True
        flags['icon'] = None

    window.events.shown += on_shown

    def stop_everything():
        store.stop.set()
        history.close()
        if box['child'] is not None:
            box['child'].terminate()
            box['child'] = None
        shutil.rmtree(state_dir, ignore_errors=True)

    def on_close(choice):
        if choice == 'hide':
            flags['visible'] = False
            window.hide()
        elif choice == 'exit':
            flags['exit'] = True
            window.destroy()

    api._bind(window, on_close)

    window.events.closing += closing_handler(window, flags)

    def watcher():
        api._note('启动', '监测已启动')
        if hidden:
            api._note('面板', '已隐藏到托盘，监测继续')
        threading.Thread(target=store.loop, daemon=True).start()
        while not store.stop.is_set():
            api._observe()
            api._record()
            overall = store.read().get('overall', 'unknown')
            if flags['shown'] and flags.get('icon') != overall:
                if set_native_icon(window, overall if overall in engine.STATES else 'unknown'):
                    flags['icon'] = overall
            if show_path.exists():
                try:
                    show_path.unlink()
                except OSError:
                    pass
                flags['visible'] = True
                window.show()
                window.restore()
            if box['child'] is not None and box['child'].poll() is not None:
                box['child'] = None
                if not flags['visible']:
                    flags['visible'] = True
                    window.show()
                    api._notice = '托盘已退出，面板已恢复显示'
            store.stop.wait(1.0)

    try:
        webview.start(watcher, gui='edgechromium' if platform.system() == 'Windows' else None,
                      private_mode=True)
    except Exception as error:
        stop_everything()
        shared.release_single_instance()
        if not flags['shown']:
            raise Unavailable('WebView 无法启动：' + str(error)) from None
        raise
    stop_everything()


def launch(cfg, config_path, tray=False, start_hidden=False, ui='auto', web=run, tk=None):
    """Prefer the WebView panel; fall back to tkinter when it is unavailable (ui='auto')."""
    tk = tk or shared.run
    if ui == 'tk':
        return tk(cfg, config_path, tray=tray, start_hidden=start_hidden)
    try:
        return web(cfg, config_path, tray=tray, start_hidden=start_hidden)
    except Unavailable as error:
        if ui == 'web':
            raise engine.MonitorError(str(error)) from None
        return tk(cfg, config_path, tray=tray, start_hidden=start_hidden)
