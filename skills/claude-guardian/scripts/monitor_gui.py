"""Native tkinter panel for the read-only monitor: no browser, no third-party dependencies."""
from collections import deque
import ctypes
import os
from pathlib import Path
import platform
import shutil
import tempfile
import threading
import time

import monitor as engine
import monitor_guide
import monitor_history

PALETTE = {
    'paper': '#f7f4ef',
    'card': '#ffffff',
    'card_hover': '#fffaf3',
    'ink': '#22262b',
    'muted': '#6b7076',
    'faint': '#9a9ea4',
    'line': '#e6e1d8',
    'accent': '#b4552f',
    'accent_dark': '#9a4726',
    'soft': '#efe9df',
    'sidebar': '#22262b',
    'sidebar_hover': '#30353c',
    'sidebar_text': '#f7f4ef',
    'sidebar_muted': '#aeb3ba',
    'line_dark': '#3a4048',
}
LABELS = {
    'proxy_core': '代理核心',
    'tun_adapter': 'TUN 网卡',
    'default_route': '默认路由',
    'firewall_block': '防火墙默认阻止',
    'guardian_rules': '放行规则',
    'core_ipv6': '核心 IPv6',
    'strict_route': '严格路由',
    'dns_hijack': 'DNS 接管',
    'dns_servers': '网卡 DNS',
    'os_ipv6': '系统 IPv6',
}
STATE_TEXT = {'ok': '正常', 'degraded': '降级', 'fail': '失效', 'unknown': '未知'}
COLORS = {'ok': '#2f6b4f', 'degraded': '#8a5a11', 'fail': '#a32a24', 'unknown': '#5d6470'}
# Light backgrounds paired with COLORS for chips, the summary banner and problem cards.
TINTS = {'ok': '#e8f1ec', 'degraded': '#f6eddc', 'fail': '#f8e4e2', 'unknown': '#eceef1'}
SEVERITY = {'fail': 0, 'degraded': 1, 'unknown': 2, 'ok': 3}
OVERALL_TEXT = {
    'ok': '防护正常',
    'degraded': '有降级项',
    'fail': '防护已失效',
    'unknown': '状态未知',
}


class LogBuffer:
    def __init__(self, limit=300):
        self.rows = deque(maxlen=limit)
        # Monotonic count of rows ever added: stays meaningful after the bounded buffer is full.
        self.total = 0

    def add(self, kind, text, level='info'):
        self.rows.append((time.strftime('%H:%M:%S'), kind, text, level))
        self.total += 1

    def snapshot(self):
        return list(self.rows)

    def clear(self):
        self.rows.clear()


def log_delta(rendered_total, log):
    """Rows the log view still has to show: (rebuild, rows).

    Appends only what is new; asks for a rebuild when the bounded buffer already dropped rows
    the view never showed, so the view never silently skips lines.
    """
    fresh = log.total - rendered_total
    rows = log.snapshot()
    if fresh <= 0:
        return False, []
    if fresh > len(rows):
        return True, rows
    return False, rows[len(rows) - fresh:]


def build_rows(state):
    rows = []
    for check in (state or {}).get('checks', []):
        rows.append({'id': check.get('id'), 'label': LABELS.get(check.get('id'), check.get('id')),
                     'state': check.get('state', 'unknown'), 'code': check.get('code') or '—'})
    return rows


def problems(rows):
    """Non-ok rows, worst first; the original order breaks ties so the list stays stable."""
    flagged = [row for row in rows if row['state'] != 'ok']
    return sorted(flagged, key=lambda row: SEVERITY.get(row['state'], SEVERITY['unknown']))


def banner_text(overall, stamp, rows):
    """Headline (the overall state) and the problem items, worst first; detail is empty when none."""
    if not stamp:
        return '正在读取…', ''
    detail = '、'.join(row['label'] + ' ' + STATE_TEXT.get(row['state'], row['state'])
                      for row in problems(rows))
    return OVERALL_TEXT.get(overall, OVERALL_TEXT['unknown']), detail


def validate_settings(interval, cooldown, notify_states):
    try:
        interval = int(interval)
        cooldown = int(cooldown)
    except (TypeError, ValueError):
        raise engine.MonitorError('采集间隔与冷却必须是整数。') from None
    if not 2 <= interval <= 3600:
        raise engine.MonitorError('采集间隔需在 2 到 3600 秒之间。')
    if not 0 <= cooldown <= 86400:
        raise engine.MonitorError('通知冷却需在 0 到 86400 秒之间。')
    states = [name for name, enabled in notify_states.items() if enabled]
    if any(name not in engine.ALERT_STATES for name in states):
        raise engine.MonitorError('通知项只能是失效、降级或未知。')
    return interval, cooldown, states


def apply_settings(cfg, interval, cooldown, notify_states, paused=False):
    interval, cooldown, states = validate_settings(interval, cooldown, notify_states)
    cfg['alerts']['interval_seconds'] = interval
    cfg['alerts']['cooldown_seconds'] = cooldown
    cfg['alerts']['notify_states'] = states
    cfg['alerts']['paused'] = bool(paused)
    return cfg


def save_config(path, cfg):
    """Validate first, then replace the file atomically, so a failed save never leaves a broken config."""
    engine.write_config(path, cfg)


def close_choices(tray_alive):
    """Hiding is only offered while a tray icon exists to bring the window back."""
    return ('hide', 'exit', None) if tray_alive else ('exit', None)


def event_text(event):
    label = LABELS.get(event['id'], event['id'])
    if event['to'] == 'ok':
        return label + ' 恢复正常'
    return label + ' → ' + STATE_TEXT.get(event['to'], event['to']) + '（原 ' + STATE_TEXT.get(event['from'], event['from']) + '）'


FONT_DIRS = (engine.ROOT.parent.parent / 'fonts', engine.ROOT / 'assets/monitor/fonts')
# Almost every string in the panel is Chinese, so body text needs a family with full CJK
# coverage: a Latin-only face makes Tk fall back glyph by glyph and mixes two typefaces with
# different baselines in one label. Best first; a family wins if the user dropped it into fonts/
# or it is installed. MiSans and HarmonyOS Sans SC are screen-first UI faces (free to use,
# not bundled); Noto Sans SC / Source Han Sans SC are OFL; Microsoft YaHei UI ships with Windows.
FONT_PREFERENCES = {
    'ui': ('Noto Sans SC', 'MiSans', 'HarmonyOS Sans SC', 'Source Han Sans SC',
           'Microsoft YaHei UI', 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC'),
    # Only the Latin "CCGuard" wordmark uses the serif role.
    'serif': ('Anthropic Serif Web Text', 'Anthropic Serif Text', 'Georgia', 'Segoe UI Semibold'),
    # Check codes are ASCII identifiers.
    'mono': ('Anthropic Mono Variable', 'Anthropic Mono', 'Cascadia Mono', 'Consolas'),
}
# Used when the installed families cannot be listed: present on every supported Windows.
FONT_DEFAULTS = {'ui': 'Microsoft YaHei UI', 'serif': 'Georgia', 'mono': 'Consolas'}


def font_files(folders=FONT_DIRS):
    """User-supplied fonts: every .ttf/.otf under the folders, subfolders included."""
    files = []
    for folder in folders:
        if folder.is_dir():
            files.extend(sorted(p for p in folder.rglob('*') if p.suffix.lower() in ('.ttf', '.otf')))
    return files


def font_family(path):
    """Family name (name ID 1, Windows English) from the font's own name table; None if unreadable."""
    import struct
    try:
        data = Path(path).read_bytes()
        count = struct.unpack('>H', data[4:6])[0]
        for index in range(count):
            tag, _, offset, _ = struct.unpack('>4sIII', data[12 + 16 * index:28 + 16 * index])
            if tag != b'name':
                continue
            _, records, strings = struct.unpack('>HHH', data[offset:offset + 6])
            for record in range(records):
                start = offset + 6 + 12 * record
                pid, _, lang, nid, length, off = struct.unpack('>HHHHHH', data[start:start + 12])
                if pid == 3 and lang == 0x409 and nid == 1:
                    begin = offset + strings + off
                    return data[begin:begin + length].decode('utf-16-be')
    except (OSError, struct.error, UnicodeDecodeError):
        return None
    return None


def register_font_files(files):
    registered = []
    if platform.system() != 'Windows':
        return registered
    for path in files:
        try:
            if ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, 0):
                registered.append(path)
        except Exception:
            pass
    return registered


def font_families(registered, installed=None):
    """Resolve each role to the first preferred family that is supplied or installed."""
    supplied = {font_family(path) for path in registered} - {None}
    # A variable font's name table carries its default instance ("Noto Sans SC Thin"); GDI exposes
    # the family itself as "Noto Sans SC".
    supplied |= {'Noto Sans SC' for name in supplied if name.startswith('Noto Sans SC')}
    available = supplied | set(installed or ())
    chosen = {}
    for role, preferred in FONT_PREFERENCES.items():
        chosen[role] = next((name for name in preferred if name in available), FONT_DEFAULTS[role])
    # Log lines mix Chinese and ASCII; the CJK UI family keeps them on one baseline.
    chosen['log'] = chosen['ui']
    return chosen


def logo_subsample(width, scale, target=44):
    """Integer shrink factor so the header logo is about target px at 100 % scaling."""
    return max(1, int(round(width / (target * max(scale, 1.0)))))


def set_app_id():
    """Own taskbar identity: the window groups as CCGuard (name and icon from the Start menu
    shortcut when registered) instead of under python.exe."""
    if platform.system() != 'Windows':
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(engine.APP_ID)
    except Exception:
        pass


def enable_dpi():
    if platform.system() != 'Windows':
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def rounded_points(x1, y1, x2, y2, radius):
    return [x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1]


_INSTANCE_MUTEX = None


INSTANCE_MUTEX_NAME = 'Local\\CCGuard.Monitor.Instance'


def acquire_single_instance(name=INSTANCE_MUTEX_NAME):
    """Windows named mutex: a second double-click must not create another window/tray."""
    global _INSTANCE_MUTEX
    if platform.system() != 'Windows':
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.SetLastError(0)
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            return True
        if kernel32.GetLastError() == 183:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            return False
        _INSTANCE_MUTEX = handle
        return True
    except Exception:
        return True


def release_single_instance():
    """Give the mutex back, e.g. before the WebView panel falls back to this one in-process."""
    global _INSTANCE_MUTEX
    handle, _INSTANCE_MUTEX = _INSTANCE_MUTEX, None
    if handle and platform.system() == 'Windows':
        try:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        except Exception:
            pass


def already_running():
    try:
        from tkinter import messagebox
        messagebox.showinfo(engine.APP_NAME, 'CCGuard 已在运行。请双击托盘图标或从托盘菜单打开面板。')
    except Exception:
        pass


def run(cfg, config_path, tray=False, start_hidden=False):
    try:
        import tkinter as tk
        from tkinter import font as tkfont
        from tkinter import ttk
    except ImportError:
        raise engine.MonitorError('本机缺少 tkinter，无法打开独立面板；可改用 serve 网页版。') from None

    if not acquire_single_instance():
        already_running()
        return

    enable_dpi()
    set_app_id()
    registered = register_font_files(font_files())

    state_dir = Path(tempfile.mkdtemp(prefix='guardian-monitor-gui-'))
    state_path = state_dir / 'state.json'
    show_path = state_dir / 'show.request'
    store = engine.Store(cfg, state_path)
    history = monitor_history.History(monitor_history.history_path(config_path)).open()
    # The first collection runs in the loop thread so the window appears without waiting for PowerShell.
    threading.Thread(target=store.loop, daemon=True).start()
    box = {'child': engine.spawn_tray(state_path, '', cfg, show_file=show_path)
           if tray and platform.system() == 'Windows' else None}

    root = tk.Tk()
    root.title(engine.APP_NAME)
    root.configure(bg=PALETTE['paper'])
    try:
        root.tk.call('tk', 'scaling', root.winfo_fpixels('1i') / 72.0)
    except Exception:
        pass
    scale = 1.0
    try:
        scale = max(1.0, root.winfo_fpixels('1i') / 96.0)
    except Exception:
        pass

    def px(value):
        return int(value * scale)

    families = font_families(registered, set(tkfont.families(root)))
    ui, serif, mono, log_font = families['ui'], families['serif'], families['mono'], families['log']
    for name, size, weight in (('TkDefaultFont', 10, 'normal'), ('TkTextFont', 10, 'normal'),
                               ('TkMenuFont', 10, 'normal'), ('TkHeadingFont', 11, 'bold'),
                               ('TkTooltipFont', 9, 'normal')):
        try:
            tkfont.nametofont(name).configure(family=ui, size=size, weight=weight)
        except Exception:
            pass
    try:
        tkfont.nametofont('TkFixedFont').configure(family=mono, size=9)
    except Exception:
        pass
    chip_font = tkfont.Font(root, family=ui, size=9, weight='bold')
    style = ttk.Style(root)
    try:
        if 'clam' in style.theme_names():
            style.theme_use('clam')
    except Exception:
        pass
    style.configure('TSpinbox', fieldbackground=PALETTE['soft'], background=PALETTE['soft'],
                    foreground=PALETTE['ink'], bordercolor=PALETTE['line'],
                    lightcolor=PALETTE['soft'], darkcolor=PALETTE['soft'],
                    arrowcolor=PALETTE['muted'], padding=(px(6), px(3)), font=(ui, 10))
    style.configure('TCheckbutton', background=PALETTE['card'], foreground=PALETTE['ink'],
                    font=(ui, 10), padding=(0, px(3)), indicatorbackground=PALETTE['card'],
                    indicatorforeground='#ffffff', upperbordercolor=PALETTE['faint'],
                    lowerbordercolor=PALETTE['faint'], indicatormargin=(0, 0, px(8), 0))
    style.map('TCheckbutton', background=[('active', PALETTE['card'])],
              foreground=[('active', PALETTE['ink'])],
              indicatorbackground=[('selected', PALETTE['accent']), ('active', PALETTE['soft'])],
              upperbordercolor=[('selected', PALETTE['accent'])],
              lowerbordercolor=[('selected', PALETTE['accent'])])
    for orient in ('Vertical', 'Horizontal'):
        style.configure(orient + '.TScrollbar', background=PALETTE['line'],
                        troughcolor=PALETTE['paper'], bordercolor=PALETTE['paper'],
                        lightcolor=PALETTE['line'], darkcolor=PALETTE['line'],
                        arrowcolor=PALETTE['muted'], gripcount=0)
        style.map(orient + '.TScrollbar', background=[('active', PALETTE['faint'])])
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    width = min(px(1000), max(760, screen_w - 80))
    height = min(px(760), max(560, screen_h - 80))
    root.geometry('%dx%d+%d+%d' % (width, height, max(0, (screen_w - width) // 2),
                                   max(0, (screen_h - height) // 3)))
    root.minsize(min(px(840), width), min(px(600), height))
    log = LogBuffer()
    rendered = {'log': 0, 'states': {}, 'icon': None, 'rows': [], 'stamp': 0, 'target': '—'}

    def button(parent, text, command, primary=False, bg=None):
        base = bg or PALETTE['soft']
        options = dict(text=text, command=command, relief='flat', bd=0, padx=px(16),
                       pady=px(6), font=(ui, 10), cursor='hand2', highlightthickness=0)
        if primary:
            options.update(bg=PALETTE['accent'], fg='#ffffff', activebackground=PALETTE['accent_dark'],
                           activeforeground='#ffffff')
            hover = PALETTE['accent_dark']
            base = PALETTE['accent']
        else:
            options.update(bg=base, fg=PALETTE['ink'],
                           activebackground=PALETTE['line'], activeforeground=PALETTE['ink'])
            hover = PALETTE['line']
        widget = tk.Button(parent, **options)
        widget.bind('<Enter>', lambda _event: widget.configure(bg=hover))
        widget.bind('<Leave>', lambda _event: widget.configure(bg=base))
        return widget

    # Shield logo and window icons. Title-bar/taskbar icons come from the same PNGs via iconphoto:
    # Tk's iconbitmap cannot read the PNG-compressed 256 px frame of the .ico.
    logos, window_icons = {}, {}
    for state_name in engine.STATES:
        try:
            image = tk.PhotoImage(file=str(engine.ICON_DIR / ('logo-' + state_name + '.png')))
            factor = logo_subsample(image.width(), scale)
            logos[state_name] = image.subsample(factor) if factor > 1 else image
            window_icons[state_name] = (image, image.subsample(4), image.subsample(8))
        except Exception:
            pass

    def set_window_icon(state_name):
        # default=True only replaces Tk's class icon (used by later dialogs); default=False sends
        # WM_SETICON to this window, which is what the title bar and taskbar actually show.
        if window_icons.get(state_name):
            try:
                root.iconphoto(True, *window_icons[state_name])
                root.iconphoto(False, *window_icons[state_name])
                return True
            except Exception:
                pass
        return False

    set_window_icon('unknown')

    shell = tk.Frame(root, bg=PALETTE['paper'])
    shell.pack(fill='both', expand=True)
    sidebar = tk.Frame(shell, bg=PALETTE['sidebar'], width=px(212))
    sidebar.pack(side='left', fill='y')
    sidebar.pack_propagate(False)
    content = tk.Frame(shell, bg=PALETTE['paper'])
    content.pack(side='left', fill='both', expand=True)

    brand = tk.Frame(sidebar, bg=PALETTE['sidebar'], padx=px(18), pady=px(18))
    brand.pack(fill='x')
    logo = tk.Label(brand, bg=PALETTE['sidebar'], bd=0)
    if logos.get('unknown'):
        logo.configure(image=logos['unknown'])
        logo.pack(side='left', padx=(0, px(10)))
    brand_text = tk.Frame(brand, bg=PALETTE['sidebar'])
    brand_text.pack(side='left')
    tk.Label(brand_text, text=engine.APP_NAME, bg=PALETTE['sidebar'], fg=PALETTE['sidebar_text'],
             font=(serif, 15)).pack(anchor='w')

    header = tk.Frame(content, bg=PALETTE['paper'], padx=px(26), pady=px(18))
    header.pack(fill='x')
    header_left = tk.Frame(header, bg=PALETTE['paper'])
    header_left.pack(side='left')
    tk.Label(header_left, text='本机防护', bg=PALETTE['paper'], fg=PALETTE['ink'],
             font=(ui, 18, 'bold')).pack(anchor='w')
    subtitle = tk.Label(header_left, text='正在读取…', bg=PALETTE['paper'],
                        fg=PALETTE['muted'], font=(ui, 9))
    subtitle.pack(anchor='w', pady=(3, 0))

    # Transient messages only; empty when idle.
    status_label = tk.Label(content, text='', anchor='w', padx=px(26), pady=px(4),
                            bg=PALETTE['paper'], fg=PALETTE['muted'], font=(ui, 9))
    status_label.pack(side='bottom', fill='x')

    body = tk.Frame(content, bg=PALETTE['paper'], padx=px(18), pady=px(2))
    body.pack(fill='both', expand=True)
    body.grid_rowconfigure(0, weight=1)
    body.grid_columnconfigure(0, weight=1)

    # Sidebar navigation: each item is a row with an optional problem-count badge.
    nav = tk.Frame(sidebar, bg=PALETTE['sidebar'], padx=px(12), pady=px(8))
    nav.pack(fill='x')
    pages, nav_items = {}, {}
    active_tab = {'value': '状态', 'hover': None}

    def paint_nav():
        for name, (row, label, badge) in nav_items.items():
            if name == active_tab['value']:
                bg, fg = PALETTE['accent'], '#ffffff'
            elif name == active_tab['hover']:
                bg, fg = PALETTE['sidebar_hover'], PALETTE['sidebar_text']
            else:
                bg, fg = PALETTE['sidebar'], PALETTE['sidebar_text']
            row.configure(bg=bg)
            label.configure(bg=bg, fg=fg)

    def select(key):
        active_tab['value'] = key
        paint_nav()
        pages[key].tkraise()

    def hover_nav(name):
        active_tab['hover'] = name
        paint_nav()

    for key in ('状态', '日志', '设置'):
        row = tk.Frame(nav, bg=PALETTE['sidebar'], cursor='hand2')
        row.pack(fill='x', pady=(0, px(3)))
        label = tk.Label(row, text=key, anchor='w', padx=px(12), pady=px(9), font=(ui, 11),
                         bg=PALETTE['sidebar'], fg=PALETTE['sidebar_text'], cursor='hand2')
        label.pack(side='left', fill='x', expand=True)
        badge = tk.Label(row, text='', font=(ui, 8, 'bold'), fg='#ffffff', padx=px(7), pady=0,
                         bg=COLORS['fail'], cursor='hand2')
        for widget in (row, label, badge):
            widget.bind('<Button-1>', lambda _event, name=key: select(name))
            widget.bind('<Enter>', lambda _event, name=key: hover_nav(name))
        row.bind('<Leave>', lambda _event: hover_nav(None))
        nav_items[key] = (row, label, badge)
        page = tk.Frame(body, bg=PALETTE['paper'])
        page.grid(row=0, column=0, sticky='nsew')
        pages[key] = page

    def set_badge(count, worst):
        badge = nav_items['状态'][2]
        if count:
            badge.configure(text=str(count), bg=COLORS.get(worst, COLORS['unknown']))
            if not badge.winfo_ismapped():
                badge.pack(side='right', padx=(0, px(10)))
        elif badge.winfo_ismapped():
            badge.pack_forget()

    footer = tk.Frame(sidebar, bg=PALETTE['sidebar'], padx=px(18), pady=px(16))
    footer.pack(side='bottom', fill='x')
    autostart_var = tk.BooleanVar(value=False)
    autostart_state = {'checked': False, 'enabled': False, 'applied': False}

    def toggle_autostart():
        want = autostart_var.get()
        autostart_state['applied'] = True
        try:
            if want:
                engine.enable_autostart(config_path)
            else:
                engine.disable_autostart()
        except engine.MonitorError as error:
            autostart_var.set(not want)
            status('开机自启未变更：' + str(error))
            return
        log.add('启动', '已开启开机自启' if want else '已关闭开机自启')
        status('已开启开机自启' if want else '已关闭开机自启')

    def check_autostart():
        try:
            enabled = bool(engine.autostart_status().get('enabled'))
        except Exception:
            enabled = False
        autostart_state.update(checked=True, enabled=enabled)

    threading.Thread(target=check_autostart, daemon=True).start()

    class Switch(tk.Canvas):
        """Pill toggle bound to a BooleanVar; a plain Checkbutton's tick was invisible on the
        dark sidebar (white mark on a white box)."""

        def __init__(self, parent, variable, command, bg):
            super().__init__(parent, width=px(36), height=px(20), bg=bg, highlightthickness=0,
                             cursor='hand2')
            self.variable, self.command = variable, command
            self.bind('<Button-1>', lambda _event: self.flip())
            variable.trace_add('write', lambda *_args: self.draw())
            self.draw()

        def flip(self):
            self.variable.set(not self.variable.get())
            self.command()

        def draw(self):
            self.delete('all')
            on = self.variable.get()
            w, h = px(36), px(20)
            self.create_polygon(rounded_points(0, 0, w - 1, h - 1, h // 2), smooth=True,
                                fill=PALETTE['accent'] if on else PALETTE['line_dark'])
            knob = h - px(6)
            x = w - px(3) - knob if on else px(3)
            self.create_oval(x, px(3), x + knob, px(3) + knob, fill='#ffffff', outline='')

    autostart_row = tk.Frame(footer, bg=PALETTE['sidebar'])
    autostart_row.pack(fill='x')
    autostart_label = tk.Label(autostart_row, text='开机自启', bg=PALETTE['sidebar'],
                               fg=PALETTE['sidebar_text'], font=(ui, 10), cursor='hand2')
    autostart_label.pack(side='left')
    autostart_switch = Switch(autostart_row, autostart_var, toggle_autostart, PALETTE['sidebar'])
    autostart_switch.pack(side='right')
    autostart_label.bind('<Button-1>', lambda _event: autostart_switch.flip())

    # Status page: summary banner and check cards share one scrolling canvas.
    cards_page = pages['状态']
    canvas = tk.Canvas(cards_page, bg=PALETTE['paper'], highlightthickness=0)
    card_scroll = ttk.Scrollbar(cards_page, orient='vertical', command=canvas.yview)
    def card_scroll_set(first, last):
        # Show the scrollbar only when the cards do not fit (the window is sized so they do).
        card_scroll.set(first, last)
        needed = float(first) > 0 or float(last) < 1
        if needed and not card_scroll.winfo_ismapped():
            card_scroll.pack(side='right', fill='y', pady=px(6), before=canvas)
        elif not needed and card_scroll.winfo_ismapped():
            card_scroll.pack_forget()

    canvas.configure(yscrollcommand=card_scroll_set)
    canvas.pack(side='left', fill='both', expand=True)
    cards_grid = tk.Frame(canvas, bg=PALETTE['paper'], padx=px(4), pady=px(4))
    grid_window = canvas.create_window((0, 0), window=cards_grid, anchor='nw')
    cards_grid.bind('<Configure>', lambda _event: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda event: canvas.itemconfigure(grid_window, width=event.width))

    def chip(target, right, top, text, state):
        """Rounded state label drawn on a canvas; returns nothing, drawn right-aligned at x=right."""
        width = chip_font.measure(text) + px(16)
        height = px(22)
        target.create_polygon(rounded_points(right - width, top, right, top + height, height // 2),
                              smooth=True, fill=TINTS.get(state, TINTS['unknown']))
        target.create_text(right - width // 2, top + height // 2, text=text, font=chip_font,
                           fill=COLORS.get(state, COLORS['unknown']))

    class Banner(tk.Canvas):
        def __init__(self, parent):
            super().__init__(parent, bg=PALETTE['paper'], highlightthickness=0, height=px(52))
            self.state, self.headline, self.detail = 'unknown', '正在读取…', ''
            self.bind('<Configure>', lambda _event: self.draw())

        def set(self, state, headline, detail):
            if (state, headline, detail) == (self.state, self.headline, self.detail):
                return
            self.state, self.headline, self.detail = state, headline, detail
            self.draw()

        def draw(self):
            self.delete('all')
            width = max(self.winfo_width(), px(200))
            height = max(self.winfo_height(), px(40))
            color = COLORS.get(self.state, COLORS['unknown'])
            self.create_polygon(rounded_points(1, 1, width - 2, height - 2, px(12)), smooth=True,
                                fill=TINTS.get(self.state, TINTS['unknown']), outline='')
            self.create_rectangle(px(1), px(14), px(5), height - px(14), fill=color, outline='')
            title = self.create_text(px(22), height // 2, text=self.headline, anchor='w',
                                     font=(ui, 12, 'bold'), fill=color)
            left = self.bbox(title)[2] + px(14)
            self.create_text(left, height // 2, text=self.detail, anchor='w', font=(ui, 9),
                             fill=PALETTE['ink'])

    class Card(tk.Canvas):
        def __init__(self, parent, check_id):
            super().__init__(parent, bg=PALETTE['paper'], highlightthickness=0, height=px(54),
                             cursor='hand2')
            self.check_id = check_id
            self.title = LABELS[check_id]
            self.state = 'unknown'
            self.code = '—'
            self.hover = False
            self.bind('<Configure>', lambda _event: self.draw())
            self.bind('<Enter>', lambda _event: self.set_hover(True))
            self.bind('<Leave>', lambda _event: self.set_hover(False))
            self.bind('<Button-1>', lambda _event: show_guide(self.check_id, self.state, self.code))

        def set_hover(self, value):
            self.hover = value
            self.draw()

        def set_state(self, state, code):
            if (state, code) == (self.state, self.code):
                return
            self.state = state
            self.code = code
            self.draw()

        def draw(self):
            self.delete('all')
            width = max(self.winfo_width(), px(60))
            height = max(self.winfo_height(), px(40))
            color = COLORS.get(self.state, COLORS['unknown'])
            problem = self.state != 'ok'
            fill = PALETTE['card_hover'] if self.hover else PALETTE['card']
            self.create_polygon(rounded_points(1, 1, width - 2, height - 2, px(10)), smooth=True,
                                fill=fill, outline=color if self.state == 'fail' else PALETTE['line'])
            if problem:
                self.create_rectangle(px(1), px(14), px(4), height - px(14), fill=color, outline='')
            self.create_text(px(18), height // 2, text=self.title, anchor='w',
                             font=(ui, 11, 'bold'), fill=PALETTE['ink'])
            chip(self, width - px(14), height // 2 - px(11), STATE_TEXT.get(self.state, self.state),
                 self.state)

    banner = Banner(cards_grid)
    banner.grid(row=0, column=0, columnspan=2, sticky='ew', padx=px(6), pady=(0, px(6)))
    cards = {}
    for index, check_id in enumerate(engine.CHECK_IDS):
        card = Card(cards_grid, check_id)
        card.grid(row=1 + index // 2, column=index % 2, sticky='nsew', padx=px(6), pady=px(6))
        cards[check_id] = card
    cards_grid.columnconfigure(0, weight=1, uniform='cards')
    cards_grid.columnconfigure(1, weight=1, uniform='cards')

    def scroll_cards(event):
        if active_tab['value'] == '状态':
            canvas.yview_scroll(int(-event.delta / 120), 'units')

    canvas.bind_all('<MouseWheel>', scroll_cards)

    # Log page: toolbar, then a read-only text view coloured by event level.
    log_page = pages['日志']
    log_bar = tk.Frame(log_page, bg=PALETTE['paper'])
    log_bar.pack(fill='x', pady=(px(6), 0))
    log_frame = tk.Frame(log_page, bg=PALETTE['card'], highlightthickness=1,
                         highlightbackground=PALETTE['line'])
    log_frame.pack(fill='both', expand=True, pady=px(6))
    log_text = tk.Text(log_frame, height=12, state='disabled', wrap='word', bg=PALETTE['card'],
                       fg=PALETTE['ink'], relief='flat', padx=px(14), pady=px(10),
                       spacing1=px(3), spacing3=px(3), highlightthickness=0,
                       font=(log_font, 10), bd=0, selectbackground=PALETTE['soft'],
                       selectforeground=PALETTE['ink'])
    log_scroll = ttk.Scrollbar(log_frame, command=log_text.yview)
    log_scroll.pack(fill='y', side='right')
    log_text.pack(fill='both', expand=True, side='left')
    log_text.configure(yscrollcommand=log_scroll.set)
    log_text.tag_configure('time', foreground=PALETTE['faint'], font=(mono, 9))
    log_text.tag_configure('kind', foreground=PALETTE['muted'])
    for level, color in COLORS.items():
        log_text.tag_configure(level, foreground=color)
    log_text.tag_configure('info', foreground=PALETTE['ink'])

    def write_log_rows(rows, rebuild):
        log_text.configure(state='normal')
        if rebuild:
            log_text.delete('1.0', 'end')
        for moment, kind, text, level in rows:
            log_text.insert('end', moment + '  ', 'time')
            log_text.insert('end', '[' + kind + ']  ', 'kind')
            log_text.insert('end', text + '\n', level if level in COLORS else 'info')
        # Keep the view no longer than the buffer.
        extra = int(log_text.index('end-1c').split('.')[0]) - 1 - log.rows.maxlen
        if extra > 0:
            log_text.delete('1.0', '%d.0' % (extra + 1))
        log_text.see('end')
        log_text.configure(state='disabled')

    def on_copy_log():
        text = '\n'.join('%s  [%s]  %s' % row[:3] for row in log.snapshot())
        root.clipboard_clear()
        root.clipboard_append(text)
        status('已复制 %d 条日志到剪贴板' % len(log.snapshot()))

    def on_clear_log():
        log.clear()
        write_log_rows([], True)
        rendered['log'] = log.total
        status('日志已清空')

    button(log_bar, '清空', on_clear_log).pack(side='right')
    button(log_bar, '复制全部', on_copy_log).pack(side='right', padx=(0, px(8)))

    # Settings page.
    settings_page = pages['设置']
    settings = tk.Frame(settings_page, bg=PALETTE['card'], padx=px(26), pady=px(20),
                        highlightthickness=1, highlightbackground=PALETTE['line'])
    settings.pack(fill='both', expand=True, pady=px(6))
    settings.columnconfigure(2, weight=1)
    interval_var = tk.StringVar(value=str(cfg['alerts']['interval_seconds']))
    cooldown_var = tk.StringVar(value=str(cfg['alerts']['cooldown_seconds']))
    notify_vars = {name: tk.BooleanVar(value=name in cfg['alerts']['notify_states'])
                   for name in ('fail', 'degraded', 'unknown')}
    pause_var = tk.BooleanVar(value=bool(cfg['alerts'].get('paused', False)))

    def field(row, text, widget, hint):
        tk.Label(settings, text=text, bg=PALETTE['card'], fg=PALETTE['ink'], anchor='w',
                 font=(ui, 10)).grid(row=row, column=0, sticky='w', pady=px(5),
                                     padx=(0, px(16)))
        widget.grid(row=row, column=1, sticky='w', pady=px(5))
        tk.Label(settings, text=hint, bg=PALETTE['card'], fg=PALETTE['muted'], anchor='w',
                 font=(ui, 9)).grid(row=row, column=2, sticky='w', padx=(px(12), 0))

    field(1, '采集间隔', ttk.Spinbox(settings, from_=2, to=3600, width=7,
                                     textvariable=interval_var, font=(ui, 10)), '秒')
    field(2, '通知冷却', ttk.Spinbox(settings, from_=0, to=86400, width=7,
                                     textvariable=cooldown_var, font=(ui, 10)), '秒')
    tk.Label(settings, text='提醒', bg=PALETTE['card'], fg=PALETTE['ink'], anchor='w',
             font=(ui, 10)).grid(row=3, column=0, sticky='w', pady=px(5))
    checks_row = tk.Frame(settings, bg=PALETTE['card'])
    checks_row.grid(row=3, column=1, columnspan=2, sticky='w')
    for name in ('fail', 'degraded', 'unknown'):
        ttk.Checkbutton(checks_row, text=STATE_TEXT[name], variable=notify_vars[name]).pack(
            side='left', padx=(0, px(22)))
    ttk.Checkbutton(settings, text='暂停提醒', variable=pause_var).grid(
        row=4, column=1, columnspan=2, sticky='w', pady=(px(4), 0))

    status_token = {'value': 0}

    def status(text):
        status_token['value'] += 1
        token = status_token['value']
        status_label.configure(text=text)

        def reset():
            if status_token['value'] == token:
                status_label.configure(text='')
        root.after(4000, reset)

    def apply_from_form():
        try:
            apply_settings(cfg, interval_var.get(), cooldown_var.get(),
                           {name: var.get() for name, var in notify_vars.items()}, pause_var.get())
        except engine.MonitorError as error:
            status('设置未生效：' + str(error))
            return False
        log.add('设置', '间隔 ' + str(cfg['alerts']['interval_seconds']) + 's，冷却 ' +
                str(cfg['alerts']['cooldown_seconds']) + 's' + ('，提醒已暂停' if cfg['alerts']['paused'] else ''))
        return True

    def on_apply():
        if apply_from_form():
            store.refresh_async()
            status('设置已生效（本次运行）')

    def on_save():
        if not apply_from_form():
            return
        try:
            save_config(config_path, cfg)
        except (OSError, engine.MonitorError) as error:
            status('保存失败，原配置未改动：' + str(error))
            return
        store.refresh_async()
        status('已写入配置文件')

    def on_refresh():
        status('已触发一次采集' if store.refresh_async() else '上一次采集尚未完成')

    def on_open_config():
        try:
            if hasattr(os, 'startfile'):
                os.startfile(config_path)
            else:
                raise OSError
        except OSError:
            status('无法打开配置文件：' + str(config_path))

    tk.Frame(settings, bg=PALETTE['line'], height=1).grid(row=7, column=0, columnspan=3,
                                                         sticky='ew', pady=(px(20), px(16)))
    actions = tk.Frame(settings, bg=PALETTE['card'])
    actions.grid(row=8, column=0, columnspan=3, sticky='w')
    button(actions, '应用', on_apply, primary=True).pack(side='left', padx=(0, px(8)))
    button(actions, '保存到配置', on_save).pack(side='left', padx=(0, px(8)))
    button(actions, '打开配置文件', on_open_config).pack(side='left')
    from version import __version__
    tk.Label(actions, text='CCGuard ' + __version__, bg=PALETTE['card'], fg=PALETTE['faint'],
             font=(ui, 9)).pack(side='right')
    actions.grid_configure(sticky='ew')

    refresh_button = button(header, '立即采集', on_refresh, bg=PALETTE['soft'])
    refresh_button.pack(side='right', padx=(0, px(12)))
    select('状态')

    def render(state):
        value = state.get('overall', 'unknown')
        stamp = state.get('checked_at')
        rendered['stamp'] = stamp or 0
        rows_now = build_rows(state)
        rendered['raw'] = {item.get('id'): item for item in state.get('checks', [])}
        flagged = problems(rows_now)
        headline, detail = banner_text(value, stamp, rows_now)
        banner.set(value if stamp else 'unknown', headline, detail)
        set_badge(len(flagged), flagged[0]['state'] if flagged else 'ok')
        if rendered['icon'] != value:
            set_window_icon(value)
            rendered['icon'] = value
            if logos.get(value):
                logo.configure(image=logos[value])
        for row_data in rows_now:
            card = cards.get(row_data['id'])
            if card is not None:
                card.set_state(row_data['state'], row_data['code'])

        current = engine.states_of(state)
        for event in engine.transitions(rendered['states'], current):
            log.add('状态', event_text(event), event['to'])
            if event['to'] in cfg['alerts']['notify_states'] and not cfg['alerts'].get('paused'):
                status(event_text(event))
        rendered['states'] = current
        if stamp:
            history.record(current)

        rebuild, fresh = log_delta(rendered['log'], log)
        if rebuild or fresh:
            write_log_rows(fresh, rebuild)
        rendered['log'] = log.total

    def render_subtitle():
        stamp = rendered['stamp']
        subtitle.configure(text='上次采集 ' + time.strftime('%H:%M:%S', time.localtime(stamp))
                           if stamp else '正在读取…')

    def show_guide(check_id, state_name, code):
        """What the check looks at and what to do now (the history view is in the WebView panel)."""
        info = monitor_guide.guide(check_id, state_name, code)
        dialog = tk.Toplevel(root)
        dialog.title(LABELS[check_id])
        dialog.configure(bg=PALETTE['card'])
        dialog.resizable(False, False)
        dialog.transient(root)
        head = tk.Frame(dialog, bg=PALETTE['card'])
        head.pack(fill='x', padx=px(24), pady=(px(20), px(6)))
        tk.Label(head, text=LABELS[check_id], bg=PALETTE['card'], fg=PALETTE['ink'],
                 font=(ui, 13, 'bold')).pack(side='left')
        tk.Label(head, text=STATE_TEXT.get(state_name, state_name),
                 bg=TINTS.get(state_name, TINTS['unknown']), fg=COLORS.get(state_name, COLORS['unknown']),
                 font=chip_font, padx=px(8)).pack(side='left', padx=(px(10), 0))
        tk.Label(dialog, text=info['checks'], bg=PALETTE['card'], fg=PALETTE['muted'], font=(ui, 9),
                 wraplength=px(380), justify='left').pack(anchor='w', padx=px(24))
        for index, step in enumerate(info['steps'], 1):
            tk.Label(dialog, text='%d. %s' % (index, step.replace('`', '')), bg=PALETTE['card'],
                     fg=PALETTE['ink'], font=(ui, 10), wraplength=px(380), justify='left').pack(
                anchor='w', padx=px(24), pady=(px(8) if index == 1 else px(3), 0))
        raw = rendered.get('raw', {}).get(check_id, {})
        if raw.get('evidence'):
            tk.Label(dialog, text='检测过程', bg=PALETTE['card'], fg=PALETTE['muted'],
                     font=(ui, 9, 'bold')).pack(anchor='w', padx=px(24), pady=(px(14), px(2)))
            if raw.get('source'):
                tk.Label(dialog, text='数据来源：' + raw['source'], bg=PALETTE['card'], fg=PALETTE['faint'],
                         font=(mono, 8)).pack(anchor='w', padx=px(24))
            for line in raw['evidence']:
                tk.Label(dialog, text=line, bg=PALETTE['card'], fg=PALETTE['ink'], font=(ui, 9),
                         wraplength=px(380), justify='left').pack(anchor='w', padx=px(24))
        tk.Label(dialog, text=code, bg=PALETTE['card'], fg=PALETTE['faint'], font=(mono, 8)).pack(
            anchor='w', padx=px(24), pady=(px(12), 0))
        button(dialog, '关闭', dialog.destroy).pack(anchor='e', padx=px(20), pady=px(16))
        dialog.bind('<Escape>', lambda _event: dialog.destroy())
        dialog.update_idletasks()
        dialog.geometry('+%d+%d' % (root.winfo_rootx() + px(160), root.winfo_rooty() + px(80)))
        dialog.focus_set()

    def show_window():
        try:
            if root.state() == 'withdrawn':
                root.deiconify()
            root.lift()
            root.focus_force()
        except Exception:
            pass

    def ask_close(choices):
        dialog = tk.Toplevel(root)
        dialog.title('关闭 ' + engine.APP_NAME)
        dialog.configure(bg=PALETTE['card'])
        dialog.resizable(False, False)
        dialog.transient(root)
        choice = {'value': None}
        question = '隐藏到托盘继续监测，还是退出？' if 'hide' in choices else '退出后监测会停止。'
        tk.Label(dialog, text=question, bg=PALETTE['card'],
                 fg=PALETTE['ink'], font=(ui, 11, 'bold'),
                 wraplength=px(400), justify='left').pack(
            anchor='w', padx=px(26), pady=(px(22), px(18)))
        row = tk.Frame(dialog, bg=PALETTE['card'])
        row.pack(fill='x', padx=px(20), pady=(0, px(20)))

        def pick(value):
            choice['value'] = value
            dialog.destroy()

        button(row, '取消', lambda: pick(None), bg=PALETTE['soft']).pack(side='right', padx=px(6))
        button(row, '退出', lambda: pick('exit'), primary='hide' not in choices).pack(
            side='right', padx=px(6))
        if 'hide' in choices:
            button(row, '隐藏到托盘', lambda: pick('hide'), primary=True).pack(side='right',
                                                                           padx=px(6))
        dialog.protocol('WM_DELETE_WINDOW', lambda: pick(None))
        dialog.bind('<Escape>', lambda _event: pick(None))
        dialog.grab_set()
        dialog.update_idletasks()
        width = max(px(460), dialog.winfo_reqwidth())
        height = dialog.winfo_reqheight()
        dialog.geometry('%dx%d+%d+%d' % (width, height,
                                         root.winfo_rootx() + px(120),
                                         root.winfo_rooty() + px(90)))
        root.wait_window(dialog)
        return choice['value']

    def shutdown():
        store.stop.set()
        history.close()
        if box['child'] is not None:
            box['child'].terminate()
        root.destroy()
        shutil.rmtree(state_dir, ignore_errors=True)

    def tray_alive():
        return box['child'] is not None and box['child'].poll() is None

    def on_close():
        choice = ask_close(close_choices(tray_alive()))
        if choice == 'hide':
            root.withdraw()
            log.add('面板', '已隐藏到托盘，监测继续')
        elif choice == 'exit':
            shutdown()

    def fit_to_content():
        """Size the window so the status page shows every card without scrolling."""
        root.update_idletasks()
        needed = (header.winfo_reqheight() + cards_grid.winfo_reqheight() + px(4) * 2
                  + status_label.winfo_reqheight() + px(12))
        side = sum(child.winfo_reqheight() for child in sidebar.winfo_children()) + px(80)
        width, height = px(900), min(max(needed, side), screen_h - 80)
        root.minsize(min(px(720), width), min(px(460), height))
        root.geometry('%dx%d+%d+%d' % (width, height, max(0, (screen_w - width) // 2),
                                       max(0, (screen_h - height) // 3)))

    def tick():
        if autostart_state['checked'] and not autostart_state['applied']:
            autostart_var.set(autostart_state['enabled'])
            autostart_state['applied'] = True
        state = store.read()
        rendered['rows'] = build_rows(state)
        render(state)
        render_subtitle()
        if show_path.exists():
            try:
                show_path.unlink()
            except OSError:
                pass
            show_window()
        if box['child'] is not None and box['child'].poll() is not None:
            box['child'] = None
            if root.state() == 'withdrawn':
                show_window()
                status('托盘已退出，面板已恢复显示')
        root.after(1000, tick)

    root.protocol('WM_DELETE_WINDOW', on_close)
    root.bind('<F5>', lambda _event: on_refresh())
    log.add('启动', '监测已启动')
    if start_hidden and tray_alive():
        root.withdraw()
        log.add('面板', '已隐藏到托盘，监测继续')
    tick()
    fit_to_content()
    root.mainloop()
