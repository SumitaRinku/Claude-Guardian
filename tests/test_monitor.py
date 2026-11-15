"""Exercise the read-only monitor at its boundaries; no real system queries, no network."""
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import HTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/claude-guardian/scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m = load('monitor')


class FakeProviders:
    def __init__(self, raw):
        self.raw = raw

    def collect(self):
        return self.raw


def raw_state(**overrides):
    base = {
        'processes': ['FlClashCore', 'explorer'],
        'adapters': [
            {'Name': 'FlClash', 'InterfaceDescription': 'Meta Tunnel', 'Status': 'Up'},
            {'Name': 'Ethernet', 'InterfaceDescription': 'Realtek Gaming GbE Family Controller', 'Status': 'Up'},
        ],
        'routes': [{'InterfaceAlias': 'FlClash', 'RouteMetric': 0, 'InterfaceMetric': 0}],
        'firewall': [
            {'Name': 'Domain', 'Enabled': True, 'DefaultOutboundAction': 'Block'},
            {'Name': 'Private', 'Enabled': True, 'DefaultOutboundAction': 'Block'},
            {'Name': 'Public', 'Enabled': True, 'DefaultOutboundAction': 'Block'},
        ],
        'rules': ['guardian-allow-tun', 'guardian-allow-lan'],
        'dns': [{'InterfaceAlias': 'Ethernet', 'ServerAddresses': ['198.18.0.2']}],
        'ipv6': [{'Name': 'Ethernet', 'Enabled': False}],
    }
    base.update(overrides)
    return base


CORE_OK = {'ipv6': False, 'tun_enable': True, 'strict_route': True, 'enhanced_mode': 'fake-ip', 'dns_hijack': True}


def config(tmp, **overrides):
    cfg = {
        'version': 1,
        'target': platform.node(),
        'proxy': {'process_names': ['FlClashCore'], 'tun_adapter': 'FlClash',
                  'runtime_config': str(tmp / 'config.yaml')},
        'firewall': {'expect_default_block': True, 'allow_rule_prefix': 'guardian-', 'min_allow_rules': 1},
        'network': {'expect_dns_servers': ['198.18.0.2'], 'expect_ipv6_disabled': True},
        'alerts': {'cooldown_seconds': 120, 'notify_states': ['fail', 'degraded'], 'interval_seconds': 5},
    }
    cfg.update(overrides)
    return cfg


def write_config(tmp, cfg):
    path = tmp / 'monitor.json'
    path.write_text(json.dumps(cfg), encoding='utf-8')
    return path


class Config(unittest.TestCase):
    def test_accepts_valid_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            self.assertEqual(m.load_config(write_config(tmp, config(tmp)))['version'], 1)

    def test_rejects_unknown_member(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            cfg = config(tmp)
            cfg['extra'] = True
            with self.assertRaisesRegex(m.MonitorError, '配置格式'):
                m.load_config(write_config(tmp, cfg))

    def test_rejects_other_target(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            cfg = config(tmp)
            cfg['target'] = 'another-host'
            with self.assertRaisesRegex(m.MonitorError, '设备'):
                m.load_config(write_config(tmp, cfg))

    def test_rejects_relative_runtime_config(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            cfg = config(tmp)
            cfg['proxy']['runtime_config'] = 'config.yaml'
            with self.assertRaisesRegex(m.MonitorError, '绝对路径'):
                m.load_config(write_config(tmp, cfg))

    def test_rejects_unsafe_process_name(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            cfg = config(tmp)
            cfg['proxy']['process_names'] = ['FlClashCore; Get-Process']
            with self.assertRaisesRegex(m.MonitorError, '进程名'):
                m.load_config(write_config(tmp, cfg))

    def test_rejects_bad_prefix_and_states(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            cfg = config(tmp)
            cfg['firewall']['allow_rule_prefix'] = 'guardian-*'
            with self.assertRaisesRegex(m.MonitorError, '前缀'):
                m.load_config(write_config(tmp, cfg))
            cfg = config(tmp)
            cfg['alerts']['notify_states'] = ['ok']
            with self.assertRaisesRegex(m.MonitorError, 'notify_states'):
                m.load_config(write_config(tmp, cfg))

    def test_rejects_interval_out_of_range(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            cfg = config(tmp)
            cfg['alerts']['interval_seconds'] = 1
            with self.assertRaisesRegex(m.MonitorError, 'interval_seconds'):
                m.load_config(write_config(tmp, cfg))


class CoreConfig(unittest.TestCase):
    def test_reads_whitelisted_keys_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.yaml'
            path.write_text('\n'.join([
                'mixed-port: 7890',
                'ipv6: false',
                'tun:',
                '  enable: true',
                '  stack: "mixed"',
                '  dns-hijack:',
                '    - "any:53"',
                '  strict-route: true',
                'dns:',
                '  enhanced-mode: "fake-ip"',
                'proxies:',
                '  - {name: private-node, password: do-not-echo}',
            ]), encoding='utf-8')
            result = m.read_core_config(path)
            self.assertEqual(result, {'ipv6': False, 'tun_enable': True, 'strict_route': True,
                                      'enhanced_mode': 'fake-ip', 'dns_hijack': True})
            self.assertNotIn('private-node', json.dumps(result))

    def test_dns_level_hijack_is_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.yaml'
            path.write_text('\n'.join(['dns:', '  enhanced-mode: fake-ip',
                                       '  dns-hijack:', '    - any:53']), encoding='utf-8')
            self.assertTrue(m.read_core_config(path)['dns_hijack'])

    def test_inline_hijack_list_and_exact_port(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.yaml'
            path.write_text('\n'.join(['tun:', '  enable: true',
                                       '  dns-hijack: [any:53, "tcp://any:53"]']), encoding='utf-8')
            self.assertTrue(m.read_core_config(path)['dns_hijack'])
            path.write_text('\n'.join(['tun:', '  dns-hijack:', '    - any:5353']), encoding='utf-8')
            self.assertFalse(m.read_core_config(path)['dns_hijack'])

    def test_missing_file_reports_unknown(self):
        self.assertEqual(m.read_core_config(Path(tempfile.gettempdir()) / 'absent-monitor.yaml'),
                         {'ipv6': None, 'tun_enable': None, 'strict_route': None,
                          'enhanced_mode': None, 'dns_hijack': None})


class Evaluation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def states(self, raw, core=None):
        return {check['id']: check['state'] for check in m.evaluate(self.cfg, raw, core or CORE_OK)}

    def test_all_checks_pass(self):
        checks = m.evaluate(self.cfg, raw_state(), CORE_OK)
        self.assertEqual([check['id'] for check in checks], list(m.CHECK_IDS))
        self.assertEqual(m.overall(checks), 'ok')

    def test_core_missing_is_failure(self):
        self.assertEqual(self.states(raw_state(processes=['explorer']))['proxy_core'], 'fail')

    def test_tun_down_and_route_elsewhere_are_failures(self):
        raw = raw_state(adapters=[{'Name': 'FlClash', 'InterfaceDescription': 'Meta Tunnel', 'Status': 'Disconnected'},
                                  {'Name': 'Ethernet', 'InterfaceDescription': 'Realtek', 'Status': 'Up'}])
        states = self.states(raw)
        self.assertEqual(states['tun_adapter'], 'fail')
        raw = raw_state(routes=[{'InterfaceAlias': 'Ethernet', 'RouteMetric': 0, 'InterfaceMetric': 25}])
        self.assertEqual(self.states(raw)['default_route'], 'fail')

    def test_firewall_allow_is_failure(self):
        raw = raw_state(firewall=[{'Name': 'Domain', 'Enabled': True, 'DefaultOutboundAction': 'Allow'},
                                  {'Name': 'Private', 'Enabled': True, 'DefaultOutboundAction': 'Block'}])
        self.assertEqual(self.states(raw)['firewall_block'], 'fail')

    def test_numeric_gpo_enum_values_are_understood(self):
        raw = raw_state(firewall=[{'Name': 'Domain', 'Enabled': 1, 'DefaultOutboundAction': 4},
                                  {'Name': 'Private', 'Enabled': 1, 'DefaultOutboundAction': 4},
                                  {'Name': 'Public', 'Enabled': 1, 'DefaultOutboundAction': 4}],
                        ipv6=[{'Name': 'Ethernet', 'Enabled': False}])
        states = self.states(raw)
        self.assertEqual(states['firewall_block'], 'ok')
        self.assertEqual(states['os_ipv6'], 'ok')

    def test_missing_rules_degrade(self):
        self.assertEqual(self.states(raw_state(rules=[]))['guardian_rules'], 'degraded')

    def test_config_drift_degrades(self):
        core = dict(CORE_OK, ipv6=True, strict_route=False, dns_hijack=False)
        states = self.states(raw_state(), core)
        self.assertEqual(states['core_ipv6'], 'degraded')
        self.assertEqual(states['strict_route'], 'degraded')
        self.assertEqual(states['dns_hijack'], 'degraded')

    def test_dns_and_ipv6_drift_degrade(self):
        raw = raw_state(dns=[{'InterfaceAlias': 'Ethernet', 'ServerAddresses': ['192.168.1.1']}],
                        ipv6=[{'Name': 'Ethernet', 'Enabled': True}])
        states = self.states(raw)
        self.assertEqual(states['dns_servers'], 'degraded')
        self.assertEqual(states['os_ipv6'], 'degraded')

    def test_unavailable_probe_is_unknown(self):
        checks = m.evaluate(self.cfg, None, {'ipv6': None, 'tun_enable': None, 'strict_route': None,
                                             'enhanced_mode': None, 'dns_hijack': None})
        self.assertEqual({check['state'] for check in checks}, {'unknown'})
        self.assertEqual(m.overall(checks), 'unknown')

    def test_single_dns_server_flattened_to_string(self):
        raw = raw_state(dns=[{'InterfaceAlias': 'Ethernet', 'ServerAddresses': '198.18.0.2'}])
        self.assertEqual(self.states(raw)['dns_servers'], 'ok')

    def test_route_through_detected_tun_with_other_alias(self):
        raw = raw_state(adapters=[{'Name': 'Meta', 'InterfaceDescription': 'Meta Tunnel', 'Status': 'Up'},
                                  {'Name': 'Ethernet', 'InterfaceDescription': 'Realtek', 'Status': 'Up'}],
                        routes=[{'InterfaceAlias': 'Meta', 'RouteMetric': 0, 'InterfaceMetric': 0}])
        states = self.states(raw)
        self.assertEqual(states['tun_adapter'], 'ok')
        self.assertEqual(states['default_route'], 'ok')

    def test_refresh_async_runs_one_collection_at_a_time(self):
        gate = threading.Event()

        class Slow:
            calls = 0

            def collect(self):
                Slow.calls += 1
                gate.wait(5)
                return raw_state()
        store = m.Store(self.cfg, Path(self.tmp.name) / 'state.json', Slow())
        self.assertTrue(store.refresh_async())
        for _ in range(100):
            if store.refresh_lock.locked():
                break
            threading.Event().wait(0.01)
        self.assertFalse(store.refresh_async())
        gate.set()
        for _ in range(200):
            if not store.refresh_lock.locked():
                break
            threading.Event().wait(0.01)
        self.assertEqual(Slow.calls, 1)
        self.assertGreater(store.read()['checked_at'], 0)

    def test_virtual_adapters_are_ignored(self):
        raw = raw_state(adapters=[
            {'Name': 'FlClash', 'InterfaceDescription': 'Meta Tunnel', 'Status': 'Up'},
            {'Name': 'Ethernet', 'InterfaceDescription': 'Realtek', 'Status': 'Up'},
            {'Name': 'VMware Network Adapter VMnet8', 'InterfaceDescription': 'VMware Virtual Ethernet Adapter for VMnet8', 'Status': 'Up'},
        ], dns=[{'InterfaceAlias': 'Ethernet', 'ServerAddresses': ['198.18.0.2']},
                {'InterfaceAlias': 'VMware Network Adapter VMnet8', 'ServerAddresses': ['192.168.1.1']}])
        self.assertEqual(self.states(raw)['dns_servers'], 'ok')


class Output(unittest.TestCase):
    def test_state_carries_no_paths_or_addresses(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            cfg = config(tmp)
            state = m.state_of(cfg, FakeProviders(raw_state()))
            body = json.dumps(state, ensure_ascii=False)
            self.assertEqual(state['schema_version'], m.SCHEMA)
            self.assertNotIn('C:\\', body)
            self.assertNotIn('.yaml', body)
            self.assertIsNone(re.search(r'\b\d{1,3}(\.\d{1,3}){3}\b', body))
            self.assertEqual({check['id'] for check in state['checks']}, set(m.CHECK_IDS))


class RecordingRunner:
    """Stands in for subprocess.run; records argv and returns a fixed JSON reply."""
    def __init__(self, reply, returncode=0):
        self.reply, self.returncode, self.calls = reply, returncode, []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, self.returncode, json.dumps(self.reply), '')


POWERSHELL = shutil.which('powershell.exe')


class Notifier(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.config_path = write_config(self.dir, config(self.dir))
        self.lnk = self.dir / 'Start Menu' / 'CCGuard.lnk'
        patcher = patch.object(m.platform, 'system', return_value='Windows')
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_register_passes_identity_launcher_and_icon_to_the_helper(self):
        runner = RecordingRunner({'registered': True, 'path': str(self.lnk)})
        result = m.register_notifier(self.config_path, runner=runner, path=self.lnk)
        self.assertTrue(result['registered'])
        argv = runner.calls[0]
        self.assertEqual(argv[argv.index('-File') + 1], str(m.SHORTCUT_TOOL))
        self.assertEqual(argv[argv.index('-Action') + 1], 'Register')
        self.assertEqual(argv[argv.index('-AppId') + 1], m.APP_ID)
        self.assertEqual(argv[argv.index('-Path') + 1], str(self.lnk))
        self.assertIn('gui', argv[argv.index('-Arguments') + 1])
        self.assertIn('--tray', argv[argv.index('-Arguments') + 1])
        self.assertIn('-ExecutionPolicy', argv)

    def test_register_rejects_an_invalid_config_before_touching_anything(self):
        self.config_path.write_text('{}', encoding='utf-8')
        runner = RecordingRunner({'registered': True})
        with self.assertRaises(m.MonitorError):
            m.register_notifier(self.config_path, runner=runner, path=self.lnk)
        self.assertEqual(runner.calls, [])

    def test_helper_refusal_becomes_an_error(self):
        runner = RecordingRunner({'error': 'not ours'}, returncode=2)
        with self.assertRaisesRegex(m.MonitorError, 'not ours'):
            m.unregister_notifier(runner=runner, path=self.lnk)

    def test_other_platforms_are_refused(self):
        with patch.object(m.platform, 'system', return_value='Linux'):
            with self.assertRaises(m.MonitorError):
                m.register_notifier(self.config_path, runner=RecordingRunner({}), path=self.lnk)

    def test_names_match_between_python_tray_and_helper(self):
        tray = (ROOT / 'skills/claude-guardian/assets/monitor/tray.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("$AppName = '" + m.APP_NAME + "'", tray)
        self.assertIn("$AppId = '" + m.APP_ID + "'", tray)
        # APPDATA exists only on Windows; supply one so the path logic is checked on every platform.
        with patch.dict(os.environ, {'APPDATA': str(self.dir)}):
            shortcut = m.start_menu_shortcut()
        self.assertEqual(shortcut.name, m.APP_NAME + '.lnk')
        self.assertEqual(shortcut.parent.name, 'Programs')
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(m.MonitorError):
                m.start_menu_shortcut()
        # The tray must not trust a registry-only identity: Windows drops those toasts silently.
        self.assertNotIn('AppUserModelId', tray)
        self.assertIn('Start Menu', tray)
        self.assertIn("-notmatch '^Disabled", tray)
        self.assertIn('ShowBalloonTip', tray)
        self.assertIn('SecurityElement]::Escape', tray)
        self.assertIn('SmallIconSize', tray)

    @unittest.skipUnless(POWERSHELL and platform.system() == 'Windows', 'needs Windows PowerShell')
    def test_real_helper_creates_reads_and_removes_only_its_own_shortcut(self):
        target = sys.executable
        result = m.register_notifier(self.config_path, path=self.lnk)
        self.assertTrue(result['registered'])
        self.assertTrue(self.lnk.is_file())
        self.assertTrue(m.notifier_status(path=self.lnk)['registered'])
        # A shortcut with another identity is reported as not ours and is never deleted.
        other = self.dir / 'Other.lnk'
        m._shortcut_tool('Register', other, Target=target, Arguments='', Icon=m.ICON, WorkingDirectory=self.dir)
        with patch.object(m, 'APP_ID', 'Someone.Else'):
            self.assertFalse(m.notifier_status(path=self.lnk)['registered'])
            with self.assertRaises(m.MonitorError):
                m.unregister_notifier(path=self.lnk)
        self.assertTrue(self.lnk.is_file())
        self.assertTrue(m.unregister_notifier(path=self.lnk)['removed'])
        self.assertFalse(self.lnk.exists())
        self.assertFalse(m.unregister_notifier(path=self.lnk)['removed'])

    def test_cli_status_needs_no_config_and_others_do(self):
        with patch.object(m, 'notifier_status', return_value={'registered': False}):
            self.assertEqual(m.main(['notifier-status']), 0)
        self.assertEqual(m.main(['register-notifier']), 2)
        self.assertEqual(m.main(['check']), 2)


class Launcher(unittest.TestCase):
    def test_desktop_launcher_keeps_monitor_alive(self):
        argv = m.launcher_argv(Path('C:/private/monitor.json'), 0)
        self.assertIn('--tray', argv)
        self.assertIn('gui', argv)
        self.assertEqual(argv[argv.index('--idle-minutes') + 1], '0')
        self.assertEqual(argv[argv.index('--config') + 1], 'C:\\private\\monitor.json')
        self.assertEqual(m.launcher_argv(Path('C:/private/monitor.json'), 30)[-1], '30')


class ProbeProcess(unittest.TestCase):
    def test_probe_never_opens_a_console_window(self):
        seen = {}

        def fake_run(argv, **kwargs):
            seen.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, '{"processes": []}', '')

        with patch.object(m.platform, 'system', return_value='Windows'), \
                patch.object(m.subprocess, 'run', side_effect=fake_run):
            self.assertEqual(m.WindowsProbes().collect(), {'processes': []})
        if hasattr(subprocess, 'CREATE_NO_WINDOW'):
            self.assertEqual(seen.get('creationflags'), subprocess.CREATE_NO_WINDOW)


class Http(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(Path(self.tmp.name))
        (Path(self.tmp.name) / 'config.yaml').write_text('\n'.join([
            'ipv6: false', 'tun:', '  enable: true', '  strict-route: true',
            'dns:', '  enhanced-mode: "fake-ip"', '  dns-hijack:', '    - "any:53"']), encoding='utf-8')
        self.store = m.Store(self.cfg, Path(self.tmp.name) / 'state.json', FakeProviders(raw_state()))
        self.store.refresh()
        self.token = 'test-token'
        self.server = HTTPServer(('127.0.0.1', 0), m.handler_for(self.store, self.token, {'seen': 0}))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def url(self, route=''):
        return 'http://127.0.0.1:%d/%s/%s' % (self.server.server_port, self.token, route)

    def test_state_requires_token(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen('http://127.0.0.1:%d/wrong/state' % self.server.server_port, timeout=5)
        self.assertEqual(caught.exception.code, 403)

    def test_state_requires_same_origin(self):
        request = Request(self.url('state'), headers={'Origin': 'http://evil.example'})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 403)

    def test_state_and_assets_served_with_csp(self):
        with urlopen(self.url('state'), timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("default-src 'self'", response.headers['Content-Security-Policy'])
            data = json.loads(response.read())
            self.assertEqual(data['overall'], 'ok')
        with urlopen(self.url('monitor.js'), timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn('javascript', response.headers['Content-Type'])
            body = response.read().decode()
            self.assertNotIn('http://', body)
            self.assertNotIn('https://', body)
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.url('config.example.json'), timeout=5)
        self.assertEqual(caught.exception.code, 404)

    def test_state_file_is_written(self):
        payload = json.loads((Path(self.tmp.name) / 'state.json').read_text(encoding='utf-8'))
        self.assertEqual(payload['schema_version'], m.SCHEMA)


if __name__ == '__main__':
    unittest.main()
