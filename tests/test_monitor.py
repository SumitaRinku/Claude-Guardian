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

    def test_accepts_long_fully_qualified_host_names(self):
        # Regression: a 64-character cap rejected the macOS CI runner's own host name, and would
        # reject long fully qualified names on real Macs too.
        long_name = ('runner-' + 'a' * 70 + '.local')
        with tempfile.TemporaryDirectory() as folder, patch.object(m.platform, 'node', return_value=long_name):
            tmp = Path(folder)
            self.assertEqual(m.load_config(write_config(tmp, config(tmp)))['target'], long_name)
        too_long = 'h' * 254
        with tempfile.TemporaryDirectory() as folder, patch.object(m.platform, 'node', return_value=too_long):
            tmp = Path(folder)
            with self.assertRaisesRegex(m.MonitorError, '设备'):
                m.load_config(write_config(tmp, config(tmp)))

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


class MultiClientConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def cfg(self, **proxy):
        cfg = config(self.dir)
        cfg['proxy'] = dict(cfg['proxy'], **proxy)
        return cfg

    def states(self, cfg, raw):
        return {check['id']: check['state'] for check in m.evaluate(cfg, raw, CORE_OK)}

    def test_preset_fills_process_names_tun_hints_and_format(self):
        cfg = config(self.dir)
        cfg['proxy'] = {'client': 'clash-verge-rev', 'runtime_config': str(self.dir / 'config.yaml')}
        cfg = m.validate_config(cfg)
        profile = m.proxy_profile(cfg)
        self.assertEqual(profile['client'], 'clash-verge-rev')
        self.assertIn('verge-mihomo', profile['process_names'])
        self.assertEqual(profile['config_format'], 'clash')
        self.assertIn('mihomo', profile['tun_patterns'])

    def test_explicit_values_override_preset(self):
        cfg = m.validate_config(self.cfg(client='flclash', process_names=['custom-core'],
                                         tun_adapter='Custom TUN', config_format='xray',
                                         tun_match=['my-tun']))
        profile = m.proxy_profile(cfg)
        self.assertEqual(profile['process_names'], ['custom-core'])
        self.assertEqual(profile['config_format'], 'xray')
        self.assertEqual(profile['tun_adapter'], 'Custom TUN')
        self.assertIn('my-tun', profile['tun_patterns'])

    def test_unknown_preset_format_and_bad_match_are_rejected(self):
        for change in ({'client': 'unknown'}, {'config_format': 'yaml2'}, {'tun_match': 'tun'}):
            cfg = self.cfg(**change)
            with self.assertRaises(m.MonitorError):
                m.load_config(write_config(self.dir, cfg))

    def test_empty_runtime_config_skips_core_checks(self):
        cfg = m.validate_config(self.cfg(runtime_config=''))
        state = m.state_of(cfg, FakeProviders(raw_state()))
        states = {check['id']: check['state'] for check in state['checks']}
        self.assertEqual(states['core_ipv6'], 'unknown')
        self.assertEqual(states['strict_route'], 'unknown')
        self.assertEqual(states['dns_hijack'], 'unknown')
        self.assertEqual(state['client'], 'custom')

    def test_empty_process_names_fall_back_to_known_cores(self):
        cfg = m.validate_config(self.cfg(client='custom', process_names=[]))
        self.assertEqual(self.states(cfg, raw_state(processes=['xray']))['proxy_core'], 'ok')
        self.assertEqual(self.states(cfg, raw_state(processes=['explorer']))['proxy_core'], 'fail')


class TunDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def states(self, cfg, raw):
        return {check['id']: check['state'] for check in m.evaluate(cfg, raw, CORE_OK)}

    def test_auto_detects_singbox_tun_by_description(self):
        cfg = config(self.dir)
        cfg['proxy'] = {'client': 'sing-box', 'runtime_config': str(self.dir / 'config.json')}
        cfg = m.validate_config(cfg)
        raw = raw_state(processes=['sing-box'], adapters=[
            {'Name': 'sing-box', 'InterfaceDescription': 'sing-tun', 'Status': 'Up'},
            {'Name': 'Ethernet', 'InterfaceDescription': 'Realtek', 'Status': 'Up'}],
            routes=[{'InterfaceAlias': 'sing-box', 'RouteMetric': 0, 'InterfaceMetric': 0}])
        states = self.states(cfg, raw)
        self.assertEqual(states['proxy_core'], 'ok')
        self.assertEqual(states['tun_adapter'], 'ok')
        self.assertEqual(states['default_route'], 'ok')

    def test_exact_configured_adapter_takes_precedence(self):
        cfg = config(self.dir)
        raw = raw_state(processes=['FlClashCore'], adapters=[
            {'Name': 'FlClash', 'InterfaceDescription': 'Meta Tunnel', 'Status': 'Disconnected'},
            {'Name': 'Mihomo', 'InterfaceDescription': 'Mihomo', 'Status': 'Up'},
            {'Name': 'Ethernet', 'InterfaceDescription': 'Realtek', 'Status': 'Up'}],
            routes=[{'InterfaceAlias': 'Mihomo', 'RouteMetric': 0, 'InterfaceMetric': 0}])
        states = self.states(cfg, raw)
        self.assertEqual(states['tun_adapter'], 'fail')
        self.assertEqual(states['default_route'], 'ok')

    def test_detected_tun_is_not_treated_as_physical_for_dns_and_ipv6(self):
        cfg = config(self.dir)
        cfg['proxy']['tun_adapter'] = 'auto'
        raw = raw_state(processes=['FlClashCore'], adapters=[
            {'Name': 'Mihomo', 'InterfaceDescription': 'Mihomo', 'Status': 'Up'},
            {'Name': 'Ethernet', 'InterfaceDescription': 'Realtek', 'Status': 'Up'}],
            routes=[{'InterfaceAlias': 'Mihomo', 'RouteMetric': 0, 'InterfaceMetric': 0}],
            dns=[{'InterfaceAlias': 'Ethernet', 'ServerAddresses': ['198.18.0.2']},
                 {'InterfaceAlias': 'Mihomo', 'ServerAddresses': ['1.1.1.1']}],
            ipv6=[{'Name': 'Ethernet', 'Enabled': False},
                  {'Name': 'Mihomo', 'Enabled': True}])
        states = self.states(cfg, raw)
        self.assertEqual(states['dns_servers'], 'ok')
        self.assertEqual(states['os_ipv6'], 'ok')

    def test_extra_tun_match_is_honoured(self):
        cfg = config(self.dir)
        cfg['proxy']['tun_adapter'] = 'auto'
        cfg['proxy']['tun_match'] = ['my custom tun']
        raw = raw_state(adapters=[
            {'Name': 'Adapter 7', 'InterfaceDescription': 'My Custom Tun Device', 'Status': 'Up'},
            {'Name': 'Ethernet', 'InterfaceDescription': 'Realtek', 'Status': 'Up'}],
            routes=[{'InterfaceAlias': 'Adapter 7', 'RouteMetric': 0, 'InterfaceMetric': 0}])
        states = self.states(cfg, raw)
        self.assertEqual(states['tun_adapter'], 'ok')
        self.assertEqual(states['default_route'], 'ok')


class JsonCoreConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, doc):
        path = self.dir / name
        path.write_text(json.dumps(doc), encoding='utf-8')
        return path

    def test_singbox_tun_inbound_with_hijack_dns(self):
        path = self.write('config.json', {
            'log': {'level': 'info'},
            'inbounds': [{'type': 'tun', 'tag': 'tun-in', 'inet4_address': '172.19.0.1/30',
                          'strict_route': True, 'auto_route': True}],
            'outbounds': [{'type': 'direct', 'tag': 'direct'}],
            'route': {'rules': [{'action': 'hijack-dns'}]},
            'dns': {'strategy': 'ipv4_only'},
        })
        self.assertEqual(m.detect_core_format(path, path.read_text(encoding='utf-8')), 'sing-box')
        result = m.read_core_config(path)
        self.assertIs(result['ipv6'], False)
        self.assertIs(result['strict_route'], True)
        self.assertIs(result['dns_hijack'], True)
        self.assertIsNone(result['tun_enable'])

    def test_singbox_1_11_address_list_is_understood(self):
        v4 = self.write('v4.json', {'inbounds': [{'type': 'tun', 'address': ['172.19.0.1/30']}]})
        v6 = self.write('v6.json', {'inbounds': [{'type': 'tun',
                                                  'address': ['172.19.0.1/30', 'fdfe:dcba:9876::1/126']}]})
        self.assertIs(m.read_core_config(v4)['ipv6'], False)
        self.assertIs(m.read_core_config(v6)['ipv6'], True)

    def test_singbox_top_level_tun_with_inet6_is_ipv6_on(self):
        path = self.write('config.json', {
            'tun': {'enable': True, 'inet6_address': 'fdfe:dcba:9876::1/126', 'strict-route': False},
            'route': {},
        })
        result = m.read_core_config(path)
        self.assertIs(result['tun_enable'], True)
        self.assertIs(result['strict_route'], False)
        self.assertIs(result['ipv6'], True)
        self.assertIsNone(result['dns_hijack'])

    def test_xray_strategy_and_sniffing(self):
        path = self.write('config.json', {
            'dns': {'queryStrategy': 'UseIPv4'},
            'inbounds': [{'protocol': 'socks', 'port': 10808,
                          'sniffing': {'enabled': True, 'destOverride': ['http', 'tls', 'dns']}}],
            'outbounds': [],
            'routing': {'domainStrategy': 'AsIs', 'rules': []},
        })
        self.assertEqual(m.detect_core_format(path, path.read_text(encoding='utf-8')), 'xray')
        result = m.read_core_config(path)
        self.assertIs(result['ipv6'], False)
        self.assertIs(result['dns_hijack'], True)
        self.assertIsNone(result['strict_route'])

    def test_xray_without_sniffing_reports_unknown_dns(self):
        path = self.write('config.json', {'inbounds': [{'protocol': 'socks'}], 'outbounds': [], 'routing': {}})
        self.assertIsNone(m.read_core_config(path)['dns_hijack'])

    def test_unsupported_json_is_all_unknown(self):
        path = self.write('config.json', {'hello': 'world'})
        self.assertEqual(m.read_core_config(path), m._empty_core())

    def test_forced_format_overrides_file_extension(self):
        # A .yaml suffix would auto-select Clash; the explicit format must win.
        path = self.dir / 'config.yaml'
        path.write_text(json.dumps({'tun': {'enable': True, 'strict_route': True}}), encoding='utf-8')
        result = m.read_core_config(path, 'sing-box')
        self.assertIs(result['tun_enable'], True)
        self.assertIs(result['strict_route'], True)


class DetectCommand(unittest.TestCase):
    def test_lists_cores_tuns_and_client_guesses(self):
        raw = raw_state(processes=['FlClashCore', 'explorer'], adapters=[
            {'Name': 'FlClash', 'InterfaceDescription': 'Meta Tunnel', 'Status': 'Up'},
            {'Name': 'Ethernet', 'InterfaceDescription': 'Realtek', 'Status': 'Up'}])
        result = m.detect(FakeProviders(raw))
        self.assertEqual(result['cores'], ['FlClashCore'])
        self.assertEqual([row['name'] for row in result['tun_adapters']], ['FlClash'])
        self.assertIn('flclash', result['client_guesses'])
        self.assertEqual(result['platform'], platform.system())

    def test_unavailable_probe_is_refused(self):
        with self.assertRaises(m.MonitorError):
            m.detect(FakeProviders(None))

    def test_cli_detect_needs_no_config(self):
        with patch.object(m, 'detect', return_value={'platform': 'Windows'}):
            self.assertEqual(m.main(['detect']), 0)


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
        # The config path is passed through in the platform's own form (backslashes only on Windows).
        config_path = Path('private') / 'monitor with space.json'
        argv = m.launcher_argv(config_path, 0)
        self.assertIn('--tray', argv)
        self.assertIn('gui', argv)
        self.assertEqual(argv[argv.index('--idle-minutes') + 1], '0')
        self.assertEqual(argv[argv.index('--config') + 1], str(config_path))
        self.assertEqual(m.launcher_argv(config_path, 30)[-1], '30')

    def test_hidden_launcher_adds_start_hidden(self):
        self.assertNotIn('--start-hidden', m.launcher_argv(Path('x'), 0))
        self.assertEqual(m.launcher_argv(Path('x'), 0, hidden=True)[-1], '--start-hidden')


class Autostart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.config_path = write_config(self.dir, config(self.dir))
        self.lnk = self.dir / 'Startup' / 'CCGuard.lnk'
        patcher = patch.object(m.platform, 'system', return_value='Windows')
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_startup_shortcut_is_in_the_per_user_startup_folder(self):
        with patch.dict(os.environ, {'APPDATA': str(self.dir)}):
            path = m.startup_shortcut()
        self.assertEqual(path.name, 'CCGuard.lnk')
        self.assertEqual(path.parent.name, 'Startup')
        self.assertIn('Start Menu', str(path))

    def test_enable_autostart_uses_startup_path_and_hidden_launch(self):
        runner = RecordingRunner({'registered': True, 'path': str(self.lnk)})
        result = m.enable_autostart(self.config_path, runner=runner, path=self.lnk)
        self.assertTrue(result['registered'])
        argv = runner.calls[0]
        self.assertEqual(argv[argv.index('-Action') + 1], 'Register')
        self.assertEqual(argv[argv.index('-Path') + 1], str(self.lnk))
        launch = argv[argv.index('-Arguments') + 1]
        self.assertIn('gui', launch)
        self.assertIn('--tray', launch)
        self.assertIn('--start-hidden', launch)

    def test_notifier_shortcut_does_not_start_hidden(self):
        runner = RecordingRunner({'registered': True, 'path': str(self.lnk)})
        m.register_notifier(self.config_path, runner=runner, path=self.lnk)
        argv = runner.calls[0]
        self.assertNotIn('--start-hidden', argv[argv.index('-Arguments') + 1])

    def test_disable_autostart_only_unregisters_our_startup_entry(self):
        runner = RecordingRunner({'removed': True, 'path': str(self.lnk)})
        result = m.disable_autostart(runner=runner, path=self.lnk)
        self.assertTrue(result['removed'])
        argv = runner.calls[0]
        self.assertEqual(argv[argv.index('-Action') + 1], 'Unregister')
        self.assertEqual(argv[argv.index('-Path') + 1], str(self.lnk))

    def test_status_maps_registered_to_enabled(self):
        runner = RecordingRunner({'registered': True, 'path': str(self.lnk)})
        self.assertEqual(m.autostart_status(runner=runner, path=self.lnk),
                         {'enabled': True, 'path': str(self.lnk)})

    def test_other_platforms_are_refused(self):
        with patch.object(m.platform, 'system', return_value='Linux'):
            with self.assertRaises(m.MonitorError):
                m.enable_autostart(self.config_path, runner=RecordingRunner({}), path=self.lnk)
            with self.assertRaises(m.MonitorError):
                m.autostart_status(runner=RecordingRunner({}), path=self.lnk)

    def test_cli_autostart_status_needs_no_config(self):
        with patch.object(m, 'autostart_status', return_value={'enabled': False}):
            self.assertEqual(m.main(['autostart-status']), 0)

    def test_cli_autostart_enable_requires_config(self):
        self.assertEqual(m.main(['autostart-enable']), 2)


class Quickstart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_detects_client_and_writes_a_valid_config(self):
        path = self.dir / 'monitor.json'
        cfg, out, created = m.quickstart_config(
            path, providers=FakeProviders(raw_state(processes=['FlClashCore'])))
        self.assertTrue(created)
        self.assertEqual(out, path)
        self.assertEqual(cfg['proxy']['client'], 'flclash')
        self.assertEqual(cfg['proxy']['tun_adapter'], 'auto')
        self.assertEqual(cfg['proxy']['runtime_config'], '')
        self.assertEqual(m.load_config(path), cfg)

    def test_explicit_client_and_runtime_config(self):
        runtime = self.dir / 'config.yaml'
        runtime.write_text('ipv6: false\n', encoding='utf-8')
        path = self.dir / 'monitor.json'
        cfg, _, _ = m.quickstart_config(path, client='sing-box', runtime_config=str(runtime),
                                        providers=FakeProviders(raw_state()))
        self.assertEqual(cfg['proxy']['client'], 'sing-box')
        self.assertEqual(cfg['proxy']['runtime_config'], str(runtime))

    def test_existing_config_is_never_overwritten(self):
        path = write_config(self.dir, config(self.dir))
        before = path.read_bytes()
        cfg, out, created = m.quickstart_config(path, providers=FakeProviders(raw_state()))
        self.assertFalse(created)
        self.assertEqual(out, path)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(cfg['proxy']['process_names'], ['FlClashCore'])

    def test_relative_runtime_config_is_rejected(self):
        with self.assertRaises(m.MonitorError):
            m.quickstart_config(self.dir / 'monitor.json', runtime_config='config.yaml',
                                providers=FakeProviders(raw_state()))

    def test_unknown_client_is_rejected(self):
        with self.assertRaises(m.MonitorError):
            m.quickstart_config(self.dir / 'monitor.json', client='unknown',
                                providers=FakeProviders(raw_state()))

    def test_default_path_uses_localappdata(self):
        with patch.dict(os.environ, {'LOCALAPPDATA': str(self.dir)}, clear=True):
            path = m.default_config_path()
        self.assertEqual(path, self.dir / 'CCGuard' / 'monitor.json')

    def test_cli_quickstart_no_launch_writes_config(self):
        path = self.dir / 'monitor.json'
        with patch.object(m, 'detect', return_value={'client_guesses': ['flclash']}):
            self.assertEqual(m.main(['quickstart', '--no-launch', '--output', str(path)]), 0)
        self.assertEqual(m.load_config(path)['proxy']['client'], 'flclash')

    def test_cli_start_hidden_requires_tray(self):
        path = write_config(self.dir, config(self.dir))
        self.assertEqual(m.main(['gui', '--config', str(path), '--start-hidden']), 2)


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
