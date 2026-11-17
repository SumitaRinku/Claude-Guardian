"""WebView panel bridge: pure logic with fakes; never opens a window or imports pywebview."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/claude-guardian/scripts'
ASSETS = ROOT / 'skills/claude-guardian/assets/monitor'
sys.path.insert(0, str(SCRIPTS))

web = importlib.import_module('monitor_webview')
gui = sys.modules['monitor_gui']
engine = sys.modules['monitor']


def config(tmp):
    return {
        'version': 1,
        'target': engine.platform.node(),
        'proxy': {'process_names': ['FlClashCore'], 'tun_adapter': 'FlClash',
                  'runtime_config': str(tmp / 'config.yaml')},
        'firewall': {'expect_default_block': True, 'allow_rule_prefix': 'guardian-', 'min_allow_rules': 1},
        'network': {'expect_dns_servers': ['198.18.0.2'], 'expect_ipv6_disabled': True},
        'alerts': {'cooldown_seconds': 120, 'notify_states': ['fail', 'degraded'], 'interval_seconds': 5},
    }


class FakeStore:
    def __init__(self, state=None):
        self.state = state or {'overall': 'unknown', 'checked_at': 0, 'checks': [], 'target_ref': 'demo-pc'}
        self.refreshes = 0
        self.busy = False
        self.stop = threading.Event()

    def read(self):
        return dict(self.state)

    def refresh_async(self):
        if self.busy:
            return False
        self.refreshes += 1
        return True


def failing_state(stamp=1000):
    return {'overall': 'fail', 'checked_at': stamp, 'target_ref': 'demo-pc', 'checks': [
        {'id': 'proxy_core', 'state': 'ok', 'code': 'PROXY_CORE_RUNNING'},
        {'id': 'firewall_block', 'state': 'fail', 'code': 'FIREWALL_ALLOW_OUTBOUND'},
        {'id': 'core_ipv6', 'state': 'degraded', 'code': 'CORE_IPV6_ON'}]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = config(self.dir)
        self.path = self.dir / 'monitor.json'
        self.path.write_text(json.dumps(self.cfg), encoding='utf-8')
        self.store = FakeStore()
        self.calls = []
        self.tray = False
        autostart = {'status': lambda: {'enabled': True},
                     'enable': lambda: self.calls.append('enable'),
                     'disable': lambda: self.calls.append('disable')}
        self.api = web.PanelApi(self.cfg, self.path, self.store, tray_alive=lambda: self.tray,
                                autostart=autostart, open_file=self.calls.append,
                                clock=lambda: 1042)

    def tearDown(self):
        self.tmp.cleanup()


class Snapshot(Base):
    def test_before_first_collection(self):
        snap = self.api.snapshot(0)
        self.assertEqual(snap['overall'], 'unknown')
        self.assertEqual(snap['rows'], [])
        self.assertEqual((snap['headline'], snap['detail']), ('正在读取…', ''))

    def test_rows_banner_and_badge(self):
        self.store.state = failing_state()
        snap = self.api.snapshot(0)
        self.assertEqual(snap['headline'], '防护已失效')
        self.assertEqual(snap['detail'], '防火墙默认阻止 失效、核心 IPv6 降级')
        self.assertEqual(snap['problems'], 2)
        self.assertEqual(snap['worst'], 'fail')
        row = snap['rows'][1]
        self.assertEqual((row['label'], row['state_text']), ('防火墙默认阻止', '失效'))
        self.assertFalse({'ago', 'counts', 'target'} & set(snap))
        json.dumps(snap, ensure_ascii=False)

    def test_state_changes_become_log_rows_and_delta_is_incremental(self):
        self.store.state = failing_state()
        first = self.api.snapshot(0)
        total = first['log']['total']
        self.store.state = dict(failing_state(), checks=[
            {'id': 'proxy_core', 'state': 'ok', 'code': 'A'},
            {'id': 'firewall_block', 'state': 'ok', 'code': 'B'},
            {'id': 'core_ipv6', 'state': 'degraded', 'code': 'C'}])
        snap = self.api.snapshot(total)
        self.assertFalse(snap['log']['rebuild'])
        self.assertEqual([row['text'] for row in snap['log']['rows']], ['防火墙默认阻止 恢复正常'])
        self.assertEqual(snap['log']['rows'][0]['level'], 'ok')
        self.assertEqual(self.api.snapshot(snap['log']['total'])['log']['rows'], [])

    def test_stale_or_future_cursor_rebuilds(self):
        for _ in range(3):
            self.api._note('x', 'y')
        snap = self.api.snapshot(99)
        self.assertTrue(snap['log']['rebuild'])
        self.assertEqual(len(snap['log']['rows']), 3)

    def test_notice_is_delivered_once(self):
        self.api._notice = '托盘已退出'
        self.assertEqual(self.api.snapshot(0)['notice'], '托盘已退出')
        self.assertIsNone(self.api.snapshot(0)['notice'])


class Settings(Base):
    FORM = {'interval': '15', 'cooldown': '60', 'notify': {'fail': True, 'unknown': True}, 'paused': True}

    def test_settings_reflect_config(self):
        view = self.api.settings()
        self.assertEqual(view['interval'], 5)
        self.assertEqual(view['notify'], {'fail': True, 'degraded': True, 'unknown': False})

    def test_apply_changes_runtime_only(self):
        before = self.path.read_bytes()
        result = self.api.apply(self.FORM, False)
        self.assertTrue(result['ok'])
        self.assertEqual(self.cfg['alerts']['interval_seconds'], 15)
        self.assertTrue(self.cfg['alerts']['paused'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.store.refreshes, 1)

    def test_save_writes_a_loadable_config(self):
        self.assertTrue(self.api.apply(self.FORM, True)['ok'])
        loaded = engine.load_config(self.path)
        self.assertEqual(loaded['alerts']['notify_states'], ['fail', 'unknown'])
        self.assertIs(loaded['alerts']['paused'], True)

    def test_invalid_form_changes_nothing(self):
        before = self.path.read_bytes()
        for form in ({'interval': '1', 'cooldown': '0'}, {'interval': 'x', 'cooldown': '0'},
                     {'interval': '5', 'cooldown': '0', 'notify': {'ok': True}}, None):
            result = self.api.apply(form, True)
            self.assertFalse(result['ok'])
            self.assertIn('设置未生效', result['message'])
        self.assertEqual(self.cfg['alerts']['interval_seconds'], 5)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.store.refreshes, 0)

    def test_refresh_reports_busy_collector(self):
        self.assertTrue(self.api.refresh()['ok'])
        self.store.busy = True
        self.assertEqual(self.api.refresh()['message'], '上一次采集尚未完成')


class Actions(Base):
    def test_autostart_toggle_and_failure(self):
        self.assertEqual(self.api.autostart_status(), {'enabled': True})
        self.assertTrue(self.api.set_autostart(True)['enabled'])
        self.assertFalse(self.api.set_autostart(False)['enabled'])
        self.assertEqual(self.calls, ['enable', 'disable'])

        def boom():
            raise engine.MonitorError('no startup dir')
        self.api._autostart['enable'] = boom
        result = self.api.set_autostart(True)
        self.assertFalse(result['ok'])
        self.assertFalse(result['enabled'])
        self.assertIn('no startup dir', result['message'])

    def test_autostart_status_failure_reads_as_off(self):
        self.api._autostart['status'] = lambda: 1 / 0
        self.assertEqual(self.api.autostart_status(), {'enabled': False})

    def test_open_config(self):
        self.assertTrue(self.api.open_config()['ok'])
        self.assertEqual(self.calls, [str(self.path)])
        self.api._open_file = None
        self.assertFalse(self.api.open_config()['ok'])

    def test_clear_and_copy_log(self):
        self.api._note('启动', '监测已启动')
        self.assertIn('[启动]  监测已启动', self.api.log_text())
        result = self.api.clear_log()
        self.assertEqual(result['total'], 1)
        self.assertEqual(self.api.log_text(), '')

    def test_close_offers_hide_only_with_live_tray(self):
        picked = []
        self.api._bind(object(), picked.append)
        self.assertEqual(self.api.close_choices(), ['exit', None])
        self.assertFalse(self.api.close('hide')['ok'])
        self.assertFalse(self.api.close(None)['ok'])
        self.assertTrue(self.api.close('exit')['ok'])
        self.tray = True
        self.assertTrue(self.api.close('hide')['ok'])
        self.assertEqual(picked, ['exit', 'hide'])
        self.assertIn('已隐藏到托盘', self.api.log_text())

    def test_only_page_methods_are_public(self):
        public = {name for name in vars(self.api) if not name.startswith('_')}
        self.assertEqual(public, set(), 'pywebview would expose these attributes to the page')


class HistoryAndDetail(Base):
    def setUp(self):
        super().setUp()
        import monitor_history
        self.now = [1000.0]
        self.history = monitor_history.History(self.dir / 'history.jsonl', clock=lambda: self.now[0]).open()
        self.api._history = self.history
        self.api._clock = lambda: self.now[0]

    def test_record_only_after_first_collection(self):
        self.api._record()
        self.assertEqual([r for r in self.history.snapshot() if 'id' in r], [])
        self.store.state = failing_state()
        self.api._record()
        self.assertEqual(len([r for r in self.history.snapshot() if 'id' in r]), 3)

    def test_detail_has_guidance_and_own_timeline(self):
        self.store.state = failing_state()
        self.api._record()
        self.now[0] = 1600
        detail = self.api.detail('firewall_block')
        self.assertEqual((detail['label'], detail['state'], detail['state_text']), ('防火墙默认阻止', 'fail', '失效'))
        self.assertTrue(detail['checks'])
        self.assertEqual(detail['segments'], [{'s': 1000, 'e': 1600, 'state': 'fail'}])
        self.assertEqual(detail['window'], 86400)
        self.assertIsNone(self.api.detail('not_a_check'))
        json.dumps(detail, ensure_ascii=False)

    def test_timeline_covers_every_check_and_only_known_spans(self):
        self.store.state = failing_state()
        self.api._record()
        data = self.api.timeline(604800)
        self.assertEqual(data['window'], 604800)
        self.assertEqual([row['id'] for row in data['rows']], list(engine.CHECK_IDS))
        self.assertEqual(self.api.timeline(12345)['window'], 86400)

    def test_fit_resizes_by_the_missing_content_size(self):
        window = types.SimpleNamespace(width=1000, height=700, sizes=[])
        window.resize = lambda w, h: window.sizes.append((w, h))
        self.api._bind(window, None)
        self.api._screen = (1920, 1080)
        result = self.api.fit(900, 480, 986, 663)
        self.assertEqual(window.sizes, [(914, 517)])
        self.assertTrue(result['ok'])
        self.api._screen = (800, 500)
        self.api.fit(900, 480, 986, 663)
        self.assertEqual(window.sizes[-1], (752, 470))

    def test_fit_without_window_is_a_no_op(self):
        self.assertEqual(self.api.fit(900, 480, 986, 663), {'ok': False})

    def test_bridge_parameters_do_not_shadow_js_globals(self):
        # Regression: pywebview turns parameter names into JS parameter names; one named `window`
        # made window.pywebview undefined inside the stub and the history page stayed empty.
        import inspect
        reserved = {'window', 'document', 'self', 'globalThis', 'location', 'history', 'name', 'top'}
        for name, method in inspect.getmembers(web.PanelApi, inspect.isfunction):
            if name.startswith('_'):
                continue
            params = set(inspect.signature(method).parameters) - {'self'}
            self.assertFalse(params & reserved, name)


class Fonts(unittest.TestCase):
    def test_page_fonts_only_ship_wordmark_and_code_faces(self):
        sys.path.insert(0, str(ROOT / 'tests'))
        from test_monitor_gui import fake_font
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            files = [fake_font(tmp / 'a.ttf', 'Anthropic Serif Web Text'),
                     fake_font(tmp / 'b.ttf', 'Anthropic Sans Text'),
                     fake_font(tmp / 'c.ttf', 'Anthropic Mono Variable'),
                     fake_font(tmp / 'd.ttf', 'Anthropic Serif Web Text'),
                     tmp / 'missing.ttf']
            fonts = web.page_fonts(files)
        self.assertEqual([font['family'] for font in fonts],
                         ['Anthropic Serif Web Text', 'Anthropic Mono Variable'])
        self.assertTrue(all(font['data'] for font in fonts))


class Launch(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def web_ok(self, cfg, path, tray=False, start_hidden=False):
        self.calls.append(('web', tray, start_hidden))

    def web_missing(self, cfg, path, tray=False, start_hidden=False):
        self.calls.append(('web', tray, start_hidden))
        raise web.Unavailable('未安装 pywebview')

    def tk(self, cfg, path, tray=False, start_hidden=False):
        self.calls.append(('tk', tray, start_hidden))

    def test_auto_prefers_webview(self):
        web.launch({}, 'c', tray=True, start_hidden=True, web=self.web_ok, tk=self.tk)
        self.assertEqual(self.calls, [('web', True, True)])

    def test_auto_falls_back_to_tk_with_same_options(self):
        web.launch({}, 'c', tray=True, start_hidden=True, web=self.web_missing, tk=self.tk)
        self.assertEqual(self.calls, [('web', True, True), ('tk', True, True)])

    def test_forced_modes(self):
        web.launch({}, 'c', ui='tk', web=self.web_ok, tk=self.tk)
        self.assertEqual(self.calls, [('tk', False, False)])
        with self.assertRaises(engine.MonitorError):
            web.launch({}, 'c', ui='web', web=self.web_missing, tk=self.tk)

    def test_missing_pywebview_is_unavailable_before_any_side_effect(self):
        real = sys.modules.get('webview')
        sys.modules['webview'] = None  # makes "import webview" raise ImportError
        try:
            with self.assertRaises(web.Unavailable):
                web.run({}, 'c')
        finally:
            if real is None:
                sys.modules.pop('webview', None)
            else:
                sys.modules['webview'] = real

    def test_native_icon_tolerates_missing_handle(self):
        self.assertFalse(web.set_native_icon(types.SimpleNamespace(), 'ok'))

    def test_entry_points_use_launch(self):
        monitor_src = (SCRIPTS / 'monitor.py').read_text(encoding='utf-8')
        self.assertNotIn('from monitor_gui import run', monitor_src)
        self.assertEqual(monitor_src.count('from monitor_webview import launch'), 2)
        self.assertIn("choices=['auto', 'web', 'tk']", monitor_src)
        self.assertIn('from monitor_webview import launch', (ROOT / 'CCGuard.pyw').read_text(encoding='utf-8'))

    def test_release_single_instance_is_idempotent(self):
        gui._INSTANCE_MUTEX = None
        gui.release_single_instance()
        self.assertIsNone(gui._INSTANCE_MUTEX)


class Page(unittest.TestCase):
    def test_page_assets_exist_and_reference_each_other(self):
        html = (ASSETS / 'panel.html').read_text(encoding='utf-8')
        self.assertIn('panel.css', html)
        self.assertIn('panel.js', html)
        for state in engine.STATES:
            self.assertTrue((ASSETS / ('logo-' + state + '.png')).is_file())

    def test_page_makes_no_network_requests(self):
        for name in ('panel.html', 'panel.js', 'panel.css'):
            text = (ASSETS / name).read_text(encoding='utf-8')
            for marker in ('http://', 'https://', 'fetch(', 'XMLHttpRequest', 'WebSocket', '@import'):
                self.assertNotIn(marker, text, name)

    def test_page_text_avoids_middle_dots(self):
        for name in ('panel.html', 'panel.js'):
            self.assertNotIn('·', (ASSETS / name).read_text(encoding='utf-8'), name)

    def test_css_body_font_is_cjk_first(self):
        css = (ASSETS / 'panel.css').read_text(encoding='utf-8')
        stack = css.split('--font-ui:', 1)[1].split(';', 1)[0]
        self.assertLess(stack.index('MiSans'), stack.index('Microsoft YaHei UI'))
        self.assertNotIn('Anthropic Sans', stack)

    def test_page_calls_only_existing_api_methods(self):
        import re
        js = (ASSETS / 'panel.js').read_text(encoding='utf-8')
        called = set(re.findall(r'api\(\)\.(\w+)\(', js))
        exposed = {name for name in dir(web.PanelApi) if not name.startswith('_')}
        self.assertTrue(called)
        self.assertLessEqual(called, exposed)


if __name__ == '__main__':
    unittest.main()
