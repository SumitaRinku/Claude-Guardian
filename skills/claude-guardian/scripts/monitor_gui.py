"""Native tkinter panel for the read-only monitor: no browser, no third-party dependencies."""
from collections import deque
import copy
import ctypes
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile
import threading
import time

import monitor as engine

PALETTE = {
    'paper': '#f7f4ef',
    'card': '#ffffff',
    'card_hover': '#fffaf3',
    'ink': '#22262b',
    'muted': '#6b7076',
    'line': '#e6e1d8',
    'accent': '#b4552f',
    'accent_dark': '#9a4726',
    'soft': '#efe9df',
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

    def add(self, kind, text):
        self.rows.append((time.strftime('%H:%M:%S'), kind, text))
        self.total += 1

    def snapshot(self):
        return list(self.rows)


def build_rows(state):
    rows = []
    for check in (state or {}).get('checks', []):
        rows.append({'id': check.get('id'), 'label': LABELS.get(check.get('id'), check.get('id')),
                     'state': check.get('state', 'unknown'), 'code': check.get('code') or '—'})
    return rows


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
    engine.validate_config(copy.deepcopy(cfg))
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    try:
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def close_choices(tray_alive):
    """Hiding is only offered while a tray icon exists to bring the window back."""
    return ('hide', 'exit', None) if tray_alive else ('exit', None)


def event_text(event):
    label = LABELS.get(event['id'], event['id'])
    if event['to'] == 'ok':
        return label + ' 恢复正常'
    return label + ' → ' + STATE_TEXT.get(event['to'], event['to']) + '（原 ' + STATE_TEXT.get(event['from'], event['from']) + '）'


FONT_DIRS = (engine.ROOT.parent.parent / 'fonts', engine.ROOT / 'assets/monitor/fonts')
# Preferred family names, best first; the first one actually registered wins.
FONT_PREFERENCES = {
    'ui': ('Anthropic Sans Text', 'Anthropic Sans Web Text'),
    'serif': ('Anthropic Serif Web Text', 'Anthropic Serif Text'),
    'mono': ('Anthropic Mono Variable', 'Anthropic Mono'),
}
FONT_FALLBACKS = {'ui': 'Microsoft YaHei UI', 'serif': 'Georgia', 'mono': 'Consolas'}


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


def font_families(registered):
    available = {font_family(path) for path in registered} - {None}
    chosen = {}
    for role, preferred in FONT_PREFERENCES.items():
        chosen[role] = next((name for name in preferred if name in available), FONT_FALLBACKS[role])
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


def run(cfg, config_path, tray=False):
    try:
        import tkinter as tk
        from tkinter import font as tkfont
    except ImportError:
        raise engine.MonitorError('本机缺少 tkinter，无法打开独立面板；可改用 serve 网页版。') from None

    families = font_families(register_font_files(font_files()))
    ui, serif, mono = families['ui'], families['serif'], families['mono']
    enable_dpi()
    set_app_id()

    state_dir = Path(tempfile.mkdtemp(prefix='guardian-monitor-gui-'))
    state_path = state_dir / 'state.json'
    show_path = state_dir / 'show.request'
    store = engine.Store(cfg, state_path)
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
    root.geometry('%dx%d' % (int(920 * scale), int(700 * scale)))
    root.minsize(int(740 * scale), int(520 * scale))
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
        try:
            tkfont.nametofont(name).configure(family=ui, size=10)
        except Exception:
            pass
    try:
        tkfont.nametofont('TkFixedFont').configure(family=mono, size=9)
    except Exception:
        pass
    log = LogBuffer()
    rendered = {'log': 0, 'states': {}, 'icon': None}

    def button(parent, text, command, primary=False):
        options = dict(text=text, command=command, relief='flat', bd=0, padx=16 * scale,
                       pady=6 * scale, font=(ui, 10), cursor='hand2', highlightthickness=0)
        if primary:
            options.update(bg=PALETTE['accent'], fg='#ffffff', activebackground=PALETTE['accent_dark'],
                           activeforeground='#ffffff')
        else:
            options.update(bg=PALETTE['soft'], fg=PALETTE['ink'],
                           activebackground=PALETTE['line'], activeforeground=PALETTE['ink'])
        return tk.Button(parent, **options)

    header = tk.Frame(root, bg=PALETTE['paper'], padx=int(22 * scale), pady=int(16 * scale))
    header.pack(fill='x')
    # Shield logo in the header, recoloured with the overall state like the tray icon.
    # Title-bar/taskbar icons come from the same PNGs via iconphoto: Tk's iconbitmap cannot read
    # the PNG-compressed 256 px frame of the .ico and silently left the default window icon.
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
    logo = tk.Label(header, bg=PALETTE['paper'], bd=0)
    if logos.get('unknown'):
        logo.configure(image=logos['unknown'])
        logo.pack(side='left', padx=(0, int(12 * scale)))
    titles = tk.Frame(header, bg=PALETTE['paper'])
    titles.pack(side='left')
    tk.Label(titles, text=engine.APP_NAME, bg=PALETTE['paper'], fg=PALETTE['ink'],
             font=(serif, 17)).pack(anchor='w')
    subtitle = tk.Label(titles, text='只读监测 · 不联网 · 不改系统', bg=PALETTE['paper'],
                        fg=PALETTE['muted'], font=(ui, 9))
    subtitle.pack(anchor='w', pady=(2, 0))

    pill = tk.Canvas(header, width=int(150 * scale), height=int(38 * scale),
                     bg=PALETTE['paper'], highlightthickness=0)
    pill.pack(side='right')
    pill_shape = pill.create_polygon(
        rounded_points(0, 0, int(150 * scale), int(38 * scale), int(12 * scale)),
        smooth=True, fill=COLORS['unknown'])
    pill_text = pill.create_text(int(75 * scale), int(19 * scale), text='正在读取…',
                                 fill='#ffffff', font=(ui, 10, 'bold'))

    counts = tk.Label(root, text='', bg=PALETTE['paper'], fg=PALETTE['muted'], anchor='w',
                      padx=int(22 * scale), font=(ui, 9))
    counts.pack(fill='x')

    nav = tk.Frame(root, bg=PALETTE['paper'], padx=int(20 * scale))
    nav.pack(fill='x', pady=(int(8 * scale), 0))
    body = tk.Frame(root, bg=PALETTE['paper'])
    body.pack(fill='both', expand=True, padx=int(16 * scale), pady=(int(6 * scale), int(6 * scale)))
    body.grid_rowconfigure(0, weight=1)
    body.grid_columnconfigure(0, weight=1)

    pages, tabs = {}, {}
    active_tab = {'value': '状态'}

    def select(key):
        active_tab['value'] = key
        for name, (label, underline) in tabs.items():
            active = name == key
            label.configure(fg=PALETTE['ink'] if active else PALETTE['muted'])
            underline.configure(bg=PALETTE['accent'] if active else PALETTE['paper'])
        pages[key].tkraise()

    for key in ('状态', '日志', '设置'):
        holder = tk.Frame(nav, bg=PALETTE['paper'])
        holder.pack(side='left', padx=(0, int(6 * scale)))
        label = tk.Label(holder, text=key, bg=PALETTE['paper'], fg=PALETTE['muted'],
                         font=(ui, 10, 'bold'), padx=int(10 * scale), pady=int(6 * scale),
                         cursor='hand2')
        label.pack()
        underline = tk.Frame(holder, height=max(2, int(2 * scale)), bg=PALETTE['paper'])
        underline.pack(fill='x')
        label.bind('<Button-1>', lambda _event, name=key: select(name))
        tabs[key] = (label, underline)
        page = tk.Frame(body, bg=PALETTE['paper'])
        page.grid(row=0, column=0, sticky='nsew')
        pages[key] = page

    cards_page = pages['状态']
    canvas = tk.Canvas(cards_page, bg=PALETTE['paper'], highlightthickness=0)
    card_scroll = tk.Scrollbar(cards_page, orient='vertical', command=canvas.yview)
    canvas.configure(yscrollcommand=card_scroll.set)
    card_scroll.pack(side='right', fill='y', pady=int(6 * scale))
    canvas.pack(side='left', fill='both', expand=True)
    cards_grid = tk.Frame(canvas, bg=PALETTE['paper'], padx=int(4 * scale), pady=int(8 * scale))
    grid_window = canvas.create_window((0, 0), window=cards_grid, anchor='nw')
    cards_grid.bind('<Configure>', lambda _event: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda event: canvas.itemconfigure(grid_window, width=event.width))

    class Card(tk.Canvas):
        def __init__(self, parent, title):
            super().__init__(parent, bg=PALETTE['paper'], highlightthickness=0,
                             height=int(104 * scale))
            self.title = title
            self.state = 'unknown'
            self.code = '—'
            self.hover = False
            self.bind('<Configure>', lambda _event: self.draw())
            self.bind('<Enter>', lambda _event: self.set_hover(True))
            self.bind('<Leave>', lambda _event: self.set_hover(False))

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
            width = max(self.winfo_width(), int(60 * scale))
            height = max(self.winfo_height(), int(40 * scale))
            fill = PALETTE['card_hover'] if self.hover else PALETTE['card']
            self.create_polygon(rounded_points(1, 1, width - 2, height - 2, 14), smooth=True,
                                fill=fill, outline=PALETTE['line'])
            color = COLORS.get(self.state, COLORS['unknown'])
            dot_x, dot_y = int(20 * scale), int(30 * scale)
            self.create_oval(dot_x - int(5 * scale), dot_y - int(5 * scale),
                             dot_x + int(5 * scale), dot_y + int(5 * scale), fill=color, outline='')
            self.create_text(int(36 * scale), int(26 * scale), text=self.title, anchor='w',
                             font=(ui, 10, 'bold'), fill=PALETTE['ink'])
            self.create_text(int(36 * scale), int(52 * scale),
                             text=STATE_TEXT.get(self.state, self.state), anchor='w',
                             font=(ui, 10), fill=color)
            self.create_text(int(36 * scale), int(78 * scale), text=self.code, anchor='w',
                             font=(mono, 8), fill=PALETTE['muted'])

    cards = {}
    for index, check_id in enumerate(engine.CHECK_IDS):
        card = Card(cards_grid, LABELS[check_id])
        card.grid(row=index // 2, column=index % 2, sticky='nsew',
                  padx=int(7 * scale), pady=int(7 * scale))
        cards[check_id] = card
    cards_grid.columnconfigure(0, weight=1)
    cards_grid.columnconfigure(1, weight=1)

    def scroll_cards(event):
        if active_tab['value'] == '状态':
            canvas.yview_scroll(int(-event.delta / 120), 'units')

    canvas.bind_all('<MouseWheel>', scroll_cards)

    log_page = pages['日志']
    log_text = tk.Text(log_page, height=12, state='disabled', wrap='word', bg=PALETTE['card'],
                       fg=PALETTE['ink'], relief='flat', padx=int(12 * scale), pady=int(10 * scale),
                       spacing1=2, highlightthickness=1, highlightbackground=PALETTE['line'],
                       font=(mono, 9), bd=0)
    log_text.pack(fill='both', expand=True, side='left', pady=int(6 * scale))
    log_scroll = tk.Scrollbar(log_page, command=log_text.yview)
    log_scroll.pack(fill='y', side='right', pady=int(6 * scale))
    log_text.configure(yscrollcommand=log_scroll.set)

    settings = tk.Frame(pages['设置'], bg=PALETTE['card'], padx=int(22 * scale), pady=int(20 * scale))
    settings.pack(fill='both', expand=True, pady=int(6 * scale))
    interval_var = tk.StringVar(value=str(cfg['alerts']['interval_seconds']))
    cooldown_var = tk.StringVar(value=str(cfg['alerts']['cooldown_seconds']))
    notify_vars = {name: tk.BooleanVar(value=name in cfg['alerts']['notify_states'])
                   for name in ('fail', 'degraded', 'unknown')}
    pause_var = tk.BooleanVar(value=bool(cfg['alerts'].get('paused', False)))

    def section(row, text):
        tk.Label(settings, text=text, bg=PALETTE['card'], fg=PALETTE['muted'], anchor='w',
                 font=(ui, 9, 'bold')).grid(row=row, column=0, columnspan=2, sticky='w',
                                            pady=(int(12 * scale), int(4 * scale)))

    def field(row, text, widget):
        tk.Label(settings, text=text, bg=PALETTE['card'], fg=PALETTE['ink'], anchor='w',
                 font=(ui, 10)).grid(row=row, column=0, sticky='w',
                                     pady=int(5 * scale), padx=(0, int(16 * scale)))
        widget.grid(row=row, column=1, sticky='w', pady=int(5 * scale))

    section(0, '采集与通知')
    field(1, '采集间隔（秒，2–3600）',
          tk.Spinbox(settings, from_=2, to=3600, width=9, textvariable=interval_var,
                     bg=PALETTE['soft'], relief='flat', font=(ui, 10), bd=0,
                     highlightthickness=0))
    field(2, '通知冷却（秒，0–86400）',
          tk.Spinbox(settings, from_=0, to=86400, width=9, textvariable=cooldown_var,
                     bg=PALETTE['soft'], relief='flat', font=(ui, 10), bd=0,
                     highlightthickness=0))
    section(3, '通知条件')
    row_cursor = 4
    for name, text in (('fail', '失效'), ('degraded', '降级'), ('unknown', '未知')):
        tk.Checkbutton(settings, text=text, variable=notify_vars[name], bg=PALETTE['card'],
                       activebackground=PALETTE['card'], anchor='w', bd=0,
                       highlightthickness=0, font=(ui, 10)).grid(row=row_cursor, column=0,
                                                                 sticky='w')
        row_cursor += 1
    tk.Checkbutton(settings, text='暂停提醒（托盘与面板同时生效）', variable=pause_var,
                   bg=PALETTE['card'], activebackground=PALETTE['card'], bd=0,
                   highlightthickness=0, font=(ui, 10)).grid(row=row_cursor, column=0,
                                                              columnspan=2, sticky='w',
                                                              pady=(int(8 * scale), int(4 * scale)))
    row_cursor += 1

    status_token = {'value': 0}

    def status(text):
        status_token['value'] += 1
        token = status_token['value']
        status_label.configure(text=text)

        def reset():
            if status_token['value'] == token:
                status_label.configure(text='只读监测 · 不联网 · 不改系统')
        root.after(6000, reset)

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

    actions = tk.Frame(settings, bg=PALETTE['card'])
    actions.grid(row=row_cursor, column=0, columnspan=2, sticky='w', pady=(int(10 * scale), 0))
    button(actions, '应用', on_apply, primary=True).pack(side='left', padx=(0, int(8 * scale)))
    button(actions, '保存到配置', on_save).pack(side='left', padx=(0, int(8 * scale)))
    button(actions, '立即采集', on_refresh).pack(side='left')
    row_cursor += 1
    tk.Label(settings, text='配置文件：' + str(config_path), bg=PALETTE['card'],
             fg=PALETTE['muted'], font=(mono, 8), wraplength=int(600 * scale),
             justify='left').grid(row=row_cursor, column=0, columnspan=2, sticky='w',
                                  pady=(int(14 * scale), 0))

    status_label = tk.Label(root, text='只读监测 · 不联网 · 不改系统', anchor='w',
                            padx=int(22 * scale), pady=int(8 * scale), bg=PALETTE['paper'],
                            fg=PALETTE['muted'], font=(ui, 9))
    status_label.pack(fill='x', side='bottom')
    select('状态')

    def render(state):
        value = state.get('overall', 'unknown')
        stamp = state.get('checked_at')
        pill.itemconfigure(pill_shape, fill=COLORS.get(value, COLORS['unknown']))
        pill.itemconfigure(pill_text, text=OVERALL_TEXT.get(value, '状态未知') if stamp else '正在读取…')
        subtitle.configure(text='上次采集：' + (time.strftime('%H:%M:%S', time.localtime(stamp)) if stamp else '—') +
                           ' · 目标 ' + str(state.get('target_ref', '—')))
        rows_now = build_rows(state)
        tally = {'ok': 0, 'degraded': 0, 'fail': 0, 'unknown': 0}
        for row_data in rows_now:
            tally[row_data['state']] = tally.get(row_data['state'], 0) + 1
        counts.configure(text='正常 %d · 降级 %d · 失效 %d · 未知 %d' %
                              (tally['ok'], tally['degraded'], tally['fail'], tally['unknown']))
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
            log.add('状态', event_text(event))
            if event['to'] in cfg['alerts']['notify_states'] and not cfg['alerts'].get('paused'):
                status(event_text(event))
        rendered['states'] = current

        if log.total != rendered['log']:
            entries = log.snapshot()
            log_text.configure(state='normal')
            log_text.delete('1.0', 'end')
            for moment, kind, text in entries:
                log_text.insert('end', moment + '  [' + kind + ']  ' + text + '\n')
            log_text.see('end')
            log_text.configure(state='disabled')
            rendered['log'] = log.total

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
        question = ('要隐藏到托盘继续监测，还是直接关闭？' if 'hide' in choices
                    else '关闭后监测会停止。确定关闭吗？')
        detail = ('隐藏后托盘盾牌图标继续按状态变色并提醒；直接关闭会停止监测。' if 'hide' in choices
                  else '本次未启动托盘，窗口隐藏后将无法找回；需要后台提醒请用 --tray 启动。')
        tk.Label(dialog, text=question, bg=PALETTE['card'],
                 fg=PALETTE['ink'], font=(ui, 11, 'bold'),
                 wraplength=int(400 * scale), justify='left').pack(
            padx=int(26 * scale), pady=(int(22 * scale), int(6 * scale)))
        tk.Label(dialog, text=detail,
                 bg=PALETTE['card'], fg=PALETTE['muted'], font=(ui, 9),
                 wraplength=int(400 * scale), justify='left').pack(
            padx=int(26 * scale), pady=(0, int(18 * scale)))
        row = tk.Frame(dialog, bg=PALETTE['card'])
        row.pack(pady=(0, int(20 * scale)))

        def pick(value):
            choice['value'] = value
            dialog.destroy()

        if 'hide' in choices:
            button(row, '隐藏到托盘', lambda: pick('hide'), primary=True).pack(side='left',
                                                                           padx=int(6 * scale))
        button(row, '直接关闭', lambda: pick('exit'), primary='hide' not in choices).pack(
            side='left', padx=int(6 * scale))
        button(row, '取消', lambda: pick(None)).pack(side='left', padx=int(6 * scale))
        dialog.protocol('WM_DELETE_WINDOW', lambda: pick(None))
        dialog.bind('<Escape>', lambda _event: pick(None))
        dialog.grab_set()
        dialog.update_idletasks()
        width = max(int(460 * scale), dialog.winfo_reqwidth())
        height = dialog.winfo_reqheight()
        dialog.geometry('%dx%d+%d+%d' % (width, height,
                                         root.winfo_rootx() + int(120 * scale),
                                         root.winfo_rooty() + int(90 * scale)))
        root.wait_window(dialog)
        return choice['value']

    def shutdown():
        store.stop.set()
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

    def tick():
        render(store.read())
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
    log.add('启动', '监测已启动')
    tick()
    root.mainloop()
