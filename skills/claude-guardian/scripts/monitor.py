"""Read-only local monitor for a deployed Guardian setup: no network, no writes, no elevation."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / 'assets/monitor'
ICON = ROOT / 'assets/monitor/icon-ok.ico'
ICON_DIR = ROOT / 'assets/monitor'
SCHEMA = 'guardian-monitor-state/0.1'
STATES = ('ok', 'degraded', 'fail', 'unknown')
ALERT_STATES = {'fail', 'degraded', 'unknown'}
CHECK_IDS = ('proxy_core', 'tun_adapter', 'default_route', 'firewall_block', 'guardian_rules',
             'core_ipv6', 'strict_route', 'dns_hijack', 'dns_servers', 'os_ipv6')
VIRTUAL = re.compile(r'virtual|meta tunnel|zerotier|hyper-v|vmware|bluetooth|loopback|tap-|wintun|wireguard|'
                     r'sing-tun|sing-box|mihomo|clash|flclash|hiddify|nekoray|nekobox|v2rayn|tun2socks', re.I)
# Process and adapter names may contain spaces and punctuation (for example "Clash for Windows").
# They are only compared in Python and never interpolated into PowerShell.
NAME = re.compile(r'[A-Za-z0-9_. +()-]{1,64}\Z')
PREFIX = re.compile(r'[A-Za-z0-9_.-]{1,32}\Z')

# Adapter name/description fragments that identify a TUN interface across clients and versions.
TUN_HINTS = ('meta tunnel', 'mihomo', 'clash', 'flclash', 'sing-tun', 'sing-box', 'hiddify',
             'nekoray', 'nekobox', 'v2rayn', 'tun2socks', 'wintun', 'wireguard')

# Known Windows proxy clients. A preset fills process names, TUN hints and the config format;
# every field can still be overridden from the private monitor.json.
CLIENT_PRESETS = {
    'flclash': {
        'label': 'FlClash',
        'process_names': ('FlClashCore', 'FlClash'),
        'tun_patterns': ('flclash', 'meta tunnel'),
        'config_format': 'clash',
    },
    'clash-verge-rev': {
        'label': 'Clash Verge Rev',
        'process_names': ('verge-mihomo', 'verge-mihomo-alpha', 'clash-verge', 'clash-verge-service'),
        'tun_patterns': ('clash', 'mihomo', 'meta'),
        'config_format': 'clash',
    },
    'clash-nyanpasu': {
        'label': 'Clash Nyanpasu',
        'process_names': ('clash-nyanpasu', 'mihomo', 'clash-meta'),
        'tun_patterns': ('nyanpasu', 'mihomo', 'meta'),
        'config_format': 'clash',
    },
    'clash-for-windows': {
        'label': 'Clash for Windows',
        'process_names': ('Clash for Windows', 'clash-win64'),
        'tun_patterns': ('clash',),
        'config_format': 'clash',
    },
    'mihomo': {
        'label': 'Mihomo / Clash.Meta',
        'process_names': ('mihomo', 'clash-meta'),
        'tun_patterns': ('mihomo', 'meta tunnel', 'clash'),
        'config_format': 'clash',
    },
    'sing-box': {
        'label': 'sing-box',
        'process_names': ('sing-box',),
        'tun_patterns': ('sing-box', 'sing-tun'),
        'config_format': 'sing-box',
    },
    'hiddify': {
        'label': 'Hiddify',
        'process_names': ('Hiddify', 'HiddifyCli', 'hiddify-core', 'sing-box'),
        'tun_patterns': ('hiddify', 'sing-tun'),
        'config_format': 'sing-box',
    },
    'v2rayn': {
        'label': 'v2rayN',
        'process_names': ('v2rayN', 'xray', 'v2ray'),
        'tun_patterns': ('v2rayn', 'tun2socks'),
        'config_format': 'xray',
    },
    'nekoray': {
        'label': 'NekoRay / NekoBox',
        'process_names': ('nekoray', 'nekobox', 'sing-box', 'xray'),
        'tun_patterns': ('nekoray', 'nekobox', 'sing-tun'),
        'config_format': 'auto',
    },
}

KNOWN_CORES = tuple(sorted({name for preset in CLIENT_PRESETS.values() for name in preset['process_names']}))

PROBE_SCRIPT = r'''
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$result = [ordered]@{}
$result.processes = @(Get-Process | Select-Object -ExpandProperty Name -Unique)
$result.adapters = @(Get-NetAdapter | Select-Object Name, InterfaceDescription, Status)
$result.routes = @(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Select-Object InterfaceAlias, RouteMetric, InterfaceMetric)
$result.firewall = @(Get-NetFirewallProfile | ForEach-Object { [pscustomobject]@{ Name = $_.Name; Enabled = [bool]$_.Enabled; DefaultOutboundAction = [string]$_.DefaultOutboundAction } })
$result.rules = @(Get-NetFirewallRule -Direction Outbound -Action Allow -Enabled True | Select-Object -ExpandProperty DisplayName)
$result.dns = @(Get-DnsClientServerAddress -AddressFamily IPv4 | Select-Object InterfaceAlias, ServerAddresses)
$result.ipv6 = @(Get-NetAdapterBinding -ComponentID ms_tcpip6 | Select-Object Name, Enabled)
[pscustomobject]$result | ConvertTo-Json -Depth 4 -Compress
'''


class MonitorError(Exception):
    pass


def _text(value, limit=64):
    return isinstance(value, str) and 0 < len(value) <= limit and '\n' not in value and '\x00' not in value


def load_config(path):
    try:
        cfg = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        raise MonitorError('配置无法读取，请从随包模板重新填写。') from None
    return validate_config(cfg)


def validate_config(cfg):
    """Validate an already-parsed configuration; shared by load and by the panel before saving."""
    required = {'version', 'target', 'proxy', 'firewall', 'network', 'alerts'}
    if not isinstance(cfg, dict) or set(cfg) != required or cfg.get('version') != 1:
        raise MonitorError('配置格式不正确，请从随包模板重新填写。')
    # Host names may be fully qualified (macOS often is), so allow the DNS maximum of 253.
    if not _text(cfg.get('target'), 253) or cfg['target'] != platform.node():
        raise MonitorError('配置与当前设备不匹配，请让 Agent 核对目标设备。')
    proxy, firewall = cfg.get('proxy'), cfg.get('firewall')
    network, alerts = cfg.get('network'), cfg.get('alerts')
    allowed_proxy = {'process_names', 'tun_adapter', 'runtime_config', 'client', 'config_format', 'tun_match'}
    if not isinstance(proxy, dict) or not set(proxy) <= allowed_proxy:
        raise MonitorError('proxy 段格式不正确。')
    client = proxy.get('client', '')
    if not isinstance(client, str) or (client not in ('', 'custom') and client not in CLIENT_PRESETS):
        raise MonitorError('proxy.client 不是已知的客户端预设。')
    names = proxy.get('process_names')
    if names is not None and (not isinstance(names, list) or len(names) > 16
                              or any(not isinstance(n, str) or not NAME.fullmatch(n) for n in names)):
        raise MonitorError('请填写需要监测的代理核心进程名。')
    adapter = proxy.get('tun_adapter', '')
    if (not isinstance(adapter, str)
            or (adapter != '' and adapter.lower() != 'auto' and not NAME.fullmatch(adapter))):
        raise MonitorError('TUN 网卡名称格式不正确；可填 auto 交由自动识别。')
    runtime = proxy.get('runtime_config', '')
    if not isinstance(runtime, str) or (runtime and (not Path(runtime).is_absolute() or not _text(runtime, 260))):
        raise MonitorError('代理运行配置必须是绝对路径，或留空关闭配置项检查。')
    if proxy.get('config_format', 'auto') not in ('auto', 'clash', 'sing-box', 'xray'):
        raise MonitorError('config_format 只能是 auto、clash、sing-box 或 xray。')
    matches = proxy.get('tun_match', [])
    if (not isinstance(matches, list) or len(matches) > 8
            or any(not isinstance(m, str) or not NAME.fullmatch(m) for m in matches)):
        raise MonitorError('tun_match 必须是最多 8 个网卡名称片段。')
    if not isinstance(firewall, dict) or set(firewall) != {'expect_default_block', 'allow_rule_prefix', 'min_allow_rules'}:
        raise MonitorError('firewall 段格式不正确。')
    if type(firewall['expect_default_block']) is not bool:
        raise MonitorError('expect_default_block 必须是布尔值。')
    if not isinstance(firewall['allow_rule_prefix'], str) or not PREFIX.fullmatch(firewall['allow_rule_prefix']):
        raise MonitorError('允许规则前缀格式不正确。')
    if type(firewall['min_allow_rules']) is not int or not 0 <= firewall['min_allow_rules'] <= 1000:
        raise MonitorError('min_allow_rules 必须是 0 到 1000 的整数。')
    if not isinstance(network, dict) or set(network) != {'expect_dns_servers', 'expect_ipv6_disabled'}:
        raise MonitorError('network 段格式不正确。')
    servers = network['expect_dns_servers']
    if not isinstance(servers, list) or len(servers) > 8:
        raise MonitorError('expect_dns_servers 必须是地址列表。')
    for server in servers:
        try:
            ipaddress.IPv4Address(server)
        except (ValueError, TypeError):
            raise MonitorError('expect_dns_servers 只能包含 IPv4 地址。') from None
    if type(network['expect_ipv6_disabled']) is not bool:
        raise MonitorError('expect_ipv6_disabled 必须是布尔值。')
    alert_keys = {'cooldown_seconds', 'notify_states', 'interval_seconds'}
    if not isinstance(alerts, dict) or not alert_keys <= set(alerts) <= alert_keys | {'paused'}:
        raise MonitorError('alerts 段格式不正确。')
    if type(alerts.get('paused', False)) is not bool:
        raise MonitorError('paused 必须是布尔值。')
    if type(alerts['cooldown_seconds']) is not int or not 0 <= alerts['cooldown_seconds'] <= 86400:
        raise MonitorError('cooldown_seconds 必须是 0 到 86400 的整数。')
    if type(alerts['interval_seconds']) is not int or not 2 <= alerts['interval_seconds'] <= 3600:
        raise MonitorError('interval_seconds 必须是 2 到 3600 的整数。')
    states = alerts['notify_states']
    if not isinstance(states, list) or any(s not in ALERT_STATES for s in states):
        raise MonitorError('notify_states 只能包含 fail、degraded、unknown。')
    return cfg


def _empty_core():
    return {'ipv6': None, 'tun_enable': None, 'strict_route': None, 'enhanced_mode': None, 'dns_hijack': None}


def detect_core_format(path, text):
    """Best-effort format detection: YAML stays Clash/Mihomo, JSON is sniffed by its keys."""
    suffix = Path(path).suffix.lower()
    if suffix in ('.yaml', '.yml'):
        return 'clash'
    stripped = text.lstrip('\ufeff \t\r\n')
    if suffix == '.json' or stripped.startswith('{'):
        try:
            doc = json.loads(text)
        except ValueError:
            return 'unknown'
        if isinstance(doc, dict):
            if 'routing' in doc:
                return 'xray'
            if 'route' in doc or 'tun' in doc:
                return 'sing-box'
            inbounds = doc.get('inbounds')
            if isinstance(inbounds, list) and any(isinstance(item, dict) and 'type' in item for item in inbounds):
                return 'sing-box'
            if 'inbounds' in doc and 'outbounds' in doc:
                return 'xray'
    return 'unknown' if stripped.startswith('{') else 'clash'


def write_config(path, cfg):
    """Validate first, then replace the file atomically; a failed write never leaves a broken config."""
    validate_config(cfg)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    try:
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def read_core_config(path, config_format='auto'):
    """Whitelisted scalar keys only; never returns proxies, groups or credentials.

    Clash/Mihomo YAML is parsed directly. sing-box and Xray JSON are mapped best-effort to the
    same five scalars; anything the format does not express stays None so the panel reports
    unknown instead of guessing.
    """
    result = _empty_core()
    if not path:
        return result
    try:
        text = Path(path).read_text(encoding='utf-8-sig', errors='replace')
    except OSError:
        return result
    fmt = config_format
    if fmt == 'auto':
        fmt = detect_core_format(path, text)
    if fmt == 'clash':
        return _read_clash_config(text)
    if fmt in ('sing-box', 'xray'):
        try:
            doc = json.loads(text)
        except ValueError:
            return result
        if not isinstance(doc, dict):
            return result
        return _read_singbox_config(doc) if fmt == 'sing-box' else _read_xray_config(doc)
    return result


def _read_clash_config(text):
    result = _empty_core()
    section = None
    hijack = []
    in_hijack = False

    def start_hijack(line):
        # Block list follows on later lines; an inline flow list ([any:53]) is complete here.
        inline = line.split(':', 1)[1].strip()
        if inline.startswith('[') and inline.endswith(']'):
            hijack.extend(item.strip().strip('"').strip("'") for item in inline[1:-1].split(',') if item.strip())
            return False
        return True

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith('#'):
            continue
        indent = len(raw) - len(raw.lstrip(' '))
        line = raw.strip()
        if indent == 0:
            section = line[:-1] if line.endswith(':') else None
            in_hijack = False
            if section is None and line.startswith('ipv6:'):
                value = line.split(':', 1)[1].strip().lower()
                result['ipv6'] = True if value in ('true', 'yes') else False if value in ('false', 'no') else None
            continue
        if in_hijack:
            if line.startswith('- '):
                hijack.append(line[2:].strip().strip('"').strip("'"))
                continue
            in_hijack = False
        if section in ('tun', 'dns') and line.startswith('dns-hijack:'):
            in_hijack = start_hijack(line)
            continue
        if section == 'tun':
            key, _, value = line.partition(':')
            value = value.strip().strip('"').strip("'").lower()
            if key == 'enable' and value in ('true', 'false'):
                result['tun_enable'] = value == 'true'
            elif key == 'strict-route' and value in ('true', 'false'):
                result['strict_route'] = value == 'true'
        elif section == 'dns':
            key, _, value = line.partition(':')
            if key == 'enhanced-mode':
                result['enhanced_mode'] = value.strip().strip('"').strip("'") or None
    if hijack:
        result['dns_hijack'] = any(re.search(r'(?:^|:)53\Z', item) for item in hijack)
    return result


def _singbox_tun(doc):
    tun = doc.get('tun') if isinstance(doc.get('tun'), dict) else None
    if tun is not None:
        return tun
    # sing-box 1.11+ configures TUN as an inbound with type "tun".
    for inbound in doc.get('inbounds') or []:
        if isinstance(inbound, dict) and str(inbound.get('type', '')).lower() == 'tun':
            return inbound
    return None


def _read_singbox_config(doc):
    result = _empty_core()
    tun = _singbox_tun(doc)
    if isinstance(tun, dict):
        if 'enable' in tun:
            result['tun_enable'] = _flag(tun['enable'])
        strict = tun.get('strict-route', tun.get('strict_route'))
        if strict is not None:
            result['strict_route'] = _flag(strict)
        inet6 = tun.get('inet6_address', tun.get('inet6-address'))
        inet4 = tun.get('inet4_address', tun.get('inet4-address'))
        addresses = tun.get('address')
        if inet6:
            result['ipv6'] = True
        elif inet4:
            result['ipv6'] = False
        elif isinstance(addresses, (list, tuple)) and addresses:
            result['ipv6'] = any(':' in str(item) for item in addresses)
        elif isinstance(addresses, str) and addresses:
            result['ipv6'] = ':' in addresses
    if result['ipv6'] is None and isinstance(doc.get('ipv6'), bool):
        result['ipv6'] = doc['ipv6']
    route = doc.get('route')
    if result['ipv6'] is None and isinstance(doc.get('dns'), dict):
        strategy = str(doc['dns'].get('strategy', '')).strip().lower()
        if strategy == 'ipv4_only':
            result['ipv6'] = False
        elif strategy in ('ipv6_only', 'prefer_ipv6'):
            result['ipv6'] = True
    if isinstance(route, dict) and isinstance(route.get('rules'), list):
        hijack = False
        for rule in route['rules']:
            if not isinstance(rule, dict):
                continue
            action = str(rule.get('action', '')).strip().lower()
            protocol = rule.get('protocol')
            protocols = [protocol] if isinstance(protocol, str) else protocol
            if action in ('hijack-dns', 'hijack_dns') or (
                    isinstance(protocols, list) and 'dns' in [str(item).lower() for item in protocols]):
                hijack = True
                break
        result['dns_hijack'] = hijack
    return result


def _read_xray_config(doc):
    result = _empty_core()
    dns = doc.get('dns') if isinstance(doc.get('dns'), dict) else {}
    routing = doc.get('routing') if isinstance(doc.get('routing'), dict) else {}
    strategy = dns.get('queryStrategy', dns.get('query_strategy'))
    if strategy is None:
        strategy = routing.get('domainStrategy', routing.get('domain_strategy'))
    if isinstance(strategy, str):
        value = strategy.strip().lower()
        if value == 'useipv4':
            result['ipv6'] = False
        elif value in ('useipv6', 'useip', 'asis'):
            result['ipv6'] = True
    found = False
    hijack = False
    for inbound in doc.get('inbounds') or []:
        if not isinstance(inbound, dict):
            continue
        sniffing = inbound.get('sniffing')
        if not isinstance(sniffing, dict) or not sniffing.get('enabled'):
            continue
        found = True
        override = sniffing.get('destOverride', sniffing.get('dest_override')) or []
        if isinstance(override, str):
            override = [override]
        if 'dns' in [str(item).lower() for item in override]:
            hijack = True
    for rule in routing.get('rules') or []:
        if not isinstance(rule, dict):
            continue
        protocol = rule.get('protocol')
        protocols = [protocol] if isinstance(protocol, str) else protocol or []
        if 'dns' in [str(item).lower() for item in protocols]:
            found = True
            hijack = True
            break
    if found:
        result['dns_hijack'] = hijack
    return result


def _flag(value):
    if value is True:
        return True
    if isinstance(value, (int, float)):
        return value == 1
    return str(value).strip().lower() in ('true', '1')


def _blocked(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 4
    return str(value).strip().lower() in ('block', '4')


def proxy_profile(cfg):
    """Resolve optional client presets and overrides into the values the checks use."""
    proxy = cfg.get('proxy') if isinstance(cfg.get('proxy'), dict) else {}
    client = proxy.get('client', '') if isinstance(proxy.get('client', ''), str) else ''
    preset = CLIENT_PRESETS.get(client, {})
    names = proxy.get('process_names')
    if names is None:
        names = list(preset.get('process_names', ()))
    patterns = [item.casefold() for item in preset.get('tun_patterns', ())]
    for item in proxy.get('tun_match', []) or []:
        if isinstance(item, str) and item.casefold() not in patterns:
            patterns.append(item.casefold())
    fmt = proxy.get('config_format', 'auto')
    if fmt == 'auto':
        fmt = preset.get('config_format', 'auto')
    return {
        'client': client or 'custom',
        'process_names': list(names),
        'tun_patterns': patterns,
        'config_format': fmt,
        'tun_adapter': proxy.get('tun_adapter', '') or '',
        'runtime_config': proxy.get('runtime_config', '') or '',
    }


def find_tun_adapters(profile, adapters):
    """Configured adapter name wins; otherwise match TUN-ish name/description hints.

    Matching is case-insensitive and substring-based so adapter renames between client
    versions do not break detection.
    """
    configured = str(profile.get('tun_adapter') or '').strip().casefold()
    hints = list(TUN_HINTS) + list(profile.get('tun_patterns') or [])
    exact, hinted = [], []
    for adapter in adapters or []:
        if not isinstance(adapter, dict):
            continue
        name = _name(adapter)
        description = str(adapter.get('InterfaceDescription') or adapter.get('description') or '')
        haystack = (name + ' ' + description).casefold()
        if configured and configured != 'auto' and (
                name.casefold() == configured or description.casefold() == configured):
            exact.append(adapter)
        elif any(hint in haystack for hint in hints):
            hinted.append(adapter)
    return exact + hinted


def _physical(adapters, tuns=()):
    tun_names = {_name(adapter).casefold() for adapter in tuns or []}
    return [a for a in adapters
            if isinstance(a, dict) and _name(a).casefold() not in tun_names
            and not VIRTUAL.search(str(a.get('InterfaceDescription') or a.get('description') or ''))
            and str(a.get('Status') or a.get('status') or '').lower() == 'up']


def _addresses(value):
    # ConvertTo-Json flattens a one-element array to a scalar on Windows PowerShell 5.1.
    if isinstance(value, str):
        value = [value]
    return {str(item) for item in (value or [])}


def _name(adapter):
    return str(adapter.get('Name') or adapter.get('name') or '')


def _norm(raw):
    def rows(key):
        value = raw.get(key) if isinstance(raw, dict) else None
        return value if isinstance(value, list) else None
    return {
        'processes': raw.get('processes') if isinstance(raw, dict) and isinstance(raw.get('processes'), list) else None,
        'adapters': rows('adapters'),
        'routes': rows('routes'),
        'firewall': rows('firewall'),
        'rules': rows('rules'),
        'dns': rows('dns'),
        'ipv6': rows('ipv6'),
    }


def evaluate(cfg, raw, core):
    data = _norm(raw)
    profile = proxy_profile(cfg)
    checks = []

    def add(check_id, state, code):
        checks.append({'id': check_id, 'state': state, 'code': code})

    running = {str(n).casefold().removesuffix('.exe') for n in (data['processes'] or [])}
    wanted = {str(n).casefold().removesuffix('.exe')
              for n in (profile['process_names'] or KNOWN_CORES)}
    if data['processes'] is None:
        add('proxy_core', 'unknown', 'PROCESS_QUERY_UNAVAILABLE')
    elif wanted & running:
        add('proxy_core', 'ok', 'PROXY_CORE_RUNNING')
    else:
        add('proxy_core', 'fail', 'PROXY_CORE_MISSING')

    adapters = data['adapters'] or []
    tuns = find_tun_adapters(profile, adapters)
    tun = tuns[0] if tuns else None
    if data['adapters'] is None:
        add('tun_adapter', 'unknown', 'ADAPTER_QUERY_UNAVAILABLE')
    elif tun is None:
        add('tun_adapter', 'fail', 'TUN_ADAPTER_MISSING')
    elif str(tun.get('Status') or '').lower() != 'up':
        add('tun_adapter', 'fail', 'TUN_ADAPTER_DOWN')
    else:
        add('tun_adapter', 'ok', 'TUN_ADAPTER_UP')

    routes = data['routes']
    if routes is None:
        add('default_route', 'unknown', 'ROUTE_QUERY_UNAVAILABLE')
    elif not routes:
        add('default_route', 'fail', 'DEFAULT_ROUTE_MISSING')
    else:
        def weight(route):
            try:
                return int(route.get('RouteMetric') or 0) + int(route.get('InterfaceMetric') or 0)
            except (TypeError, ValueError):
                return 999999
        best = min(routes, key=weight)
        tun_aliases = {_name(adapter).casefold() for adapter in tuns}
        configured = str(profile.get('tun_adapter') or '').strip().casefold()
        if configured and configured != 'auto':
            tun_aliases.add(configured)
        if str(best.get('InterfaceAlias') or '').casefold() in tun_aliases:
            add('default_route', 'ok', 'DEFAULT_ROUTE_VIA_TUN')
        else:
            add('default_route', 'fail', 'DEFAULT_ROUTE_NOT_TUN')

    firewall = data['firewall']
    if firewall is None:
        add('firewall_block', 'unknown', 'FIREWALL_QUERY_UNAVAILABLE')
    elif any(not _flag(p.get('Enabled')) for p in firewall):
        add('firewall_block', 'fail', 'FIREWALL_PROFILE_DISABLED')
    elif cfg['firewall']['expect_default_block'] and any(
            not _blocked(p.get('DefaultOutboundAction')) for p in firewall):
        add('firewall_block', 'fail', 'DEFAULT_OUTBOUND_ALLOW')
    else:
        add('firewall_block', 'ok', 'DEFAULT_OUTBOUND_BLOCKED' if cfg['firewall']['expect_default_block'] else 'DEFAULT_OUTBOUND_NOT_REQUIRED')

    rules = data['rules']
    prefix = cfg['firewall']['allow_rule_prefix']
    if rules is None:
        add('guardian_rules', 'unknown', 'RULE_QUERY_UNAVAILABLE')
    else:
        count = sum(1 for item in rules if isinstance(item, str) and item.startswith(prefix))
        if count < cfg['firewall']['min_allow_rules']:
            add('guardian_rules', 'degraded', 'GUARDIAN_RULES_MISSING')
        else:
            add('guardian_rules', 'ok', 'GUARDIAN_RULES_PRESENT')

    if core['ipv6'] is None:
        add('core_ipv6', 'unknown', 'CORE_CONFIG_UNAVAILABLE')
    elif core['ipv6']:
        add('core_ipv6', 'degraded', 'CORE_IPV6_ON')
    else:
        add('core_ipv6', 'ok', 'CORE_IPV6_OFF')

    if core['strict_route'] is None:
        add('strict_route', 'unknown', 'STRICT_ROUTE_UNKNOWN')
    elif core['strict_route']:
        add('strict_route', 'ok', 'STRICT_ROUTE_ON')
    else:
        add('strict_route', 'degraded', 'STRICT_ROUTE_OFF')

    if core['dns_hijack'] is None:
        add('dns_hijack', 'unknown', 'DNS_HIJACK_UNKNOWN')
    elif core['dns_hijack']:
        add('dns_hijack', 'ok', 'DNS_HIJACK_ON')
    else:
        add('dns_hijack', 'degraded', 'DNS_HIJACK_MISSING')

    physical = _physical(adapters, tuns)
    expected = {str(item) for item in cfg['network']['expect_dns_servers']}
    if not expected:
        add('dns_servers', 'ok', 'DNS_SERVERS_NOT_CHECKED')
    elif data['dns'] is None:
        add('dns_servers', 'unknown', 'DNS_QUERY_UNAVAILABLE')
    elif not physical:
        add('dns_servers', 'unknown', 'NO_PHYSICAL_ADAPTER')
    else:
        aliases = {_name(a) for a in physical}
        actual = [row for row in data['dns'] if str(row.get('InterfaceAlias') or '') in aliases]
        if not actual:
            add('dns_servers', 'unknown', 'DNS_QUERY_UNAVAILABLE')
        elif all(_addresses(row.get('ServerAddresses')) == expected for row in actual):
            add('dns_servers', 'ok', 'DNS_SERVERS_MATCH')
        else:
            add('dns_servers', 'degraded', 'DNS_SERVERS_DIFFER')

    if not cfg['network']['expect_ipv6_disabled']:
        add('os_ipv6', 'ok', 'OS_IPV6_NOT_REQUIRED')
    elif data['ipv6'] is None:
        add('os_ipv6', 'unknown', 'IPV6_QUERY_UNAVAILABLE')
    elif not physical:
        add('os_ipv6', 'unknown', 'NO_PHYSICAL_ADAPTER')
    else:
        aliases = {_name(a) for a in physical}
        rows = [row for row in data['ipv6'] if str(row.get('Name') or '') in aliases]
        if not rows:
            add('os_ipv6', 'unknown', 'IPV6_QUERY_UNAVAILABLE')
        elif any(_flag(row.get('Enabled')) for row in rows):
            add('os_ipv6', 'degraded', 'OS_IPV6_ENABLED')
        else:
            add('os_ipv6', 'ok', 'OS_IPV6_DISABLED')

    order = {check_id: index for index, check_id in enumerate(CHECK_IDS)}
    checks.sort(key=lambda item: order.get(item['id'], 99))
    return checks


def overall(checks):
    states = {check['state'] for check in checks}
    if 'fail' in states:
        return 'fail'
    if 'degraded' in states:
        return 'degraded'
    if 'unknown' in states:
        return 'unknown'
    return 'ok'


class WindowsProbes:
    def __init__(self, timeout=20):
        self.timeout = timeout

    def collect(self):
        if platform.system() != 'Windows':
            return None
        try:
            proc = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                   '-Command', PROBE_SCRIPT], capture_output=True, text=True, encoding='utf-8',
                                  errors='replace', timeout=self.timeout,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        try:
            data = json.loads(proc.stdout.strip().lstrip('\ufeff'))
        except ValueError:
            return None
        return data if isinstance(data, dict) else None


def transitions(previous, current):
    """Return [{'id','from','to'}] for check ids whose state changed since the last snapshot."""
    events = []
    for check_id, state in current.items():
        before = previous.get(check_id)
        if before and before != state:
            events.append({'id': check_id, 'from': before, 'to': state})
    return events


def states_of(state):
    return {check['id']: check['state'] for check in (state or {}).get('checks', [])}


def state_of(cfg, providers=None):
    providers = providers or WindowsProbes()
    profile = proxy_profile(cfg)
    raw = providers.collect()
    core = read_core_config(profile['runtime_config'], profile['config_format'])
    checks = evaluate(cfg, raw, core)
    return {'schema_version': SCHEMA, 'target_ref': cfg['target'], 'checked_at': int(time.time()),
            'interval_seconds': cfg['alerts']['interval_seconds'],
            'cooldown_seconds': cfg['alerts']['cooldown_seconds'],
            'notify_states': list(cfg['alerts']['notify_states']),
            'paused': bool(cfg['alerts'].get('paused', False)),
            'client': profile['client'],
            'overall': overall(checks), 'checks': checks}


def detect(providers=None):
    """Candidate proxy cores and TUN adapters for the current host; no configuration needed."""
    providers = providers or WindowsProbes()
    raw = providers.collect()
    if not isinstance(raw, dict):
        raise MonitorError('无法读取本机状态：监测仅支持 Windows，或需要以普通用户运行。')
    processes = [str(item) for item in raw.get('processes') or []]
    known = {name.casefold().removesuffix('.exe') for name in KNOWN_CORES}
    cores = sorted({item for item in processes
                    if item.casefold().removesuffix('.exe') in known}, key=str.casefold)
    adapters = raw.get('adapters') or []
    tuns = find_tun_adapters({'tun_adapter': '', 'tun_patterns': []}, adapters)
    running = {item.casefold().removesuffix('.exe') for item in cores}
    guesses = [key for key, preset in CLIENT_PRESETS.items()
               if {name.casefold().removesuffix('.exe') for name in preset['process_names']} & running]
    return {
        'platform': platform.system(),
        'cores': cores,
        'tun_adapters': [{'name': _name(adapter),
                          'description': str(adapter.get('InterfaceDescription') or ''),
                          'status': str(adapter.get('Status') or '')} for adapter in tuns],
        'client_guesses': guesses,
    }


def collect_state(cfg, providers=None):
    return state_of(cfg, providers)


class Store:
    def __init__(self, cfg, path, providers=None):
        self.cfg, self.path, self.providers = cfg, path, providers or WindowsProbes()
        self.lock = threading.Lock()
        self.refresh_lock = threading.Lock()
        self.current = {'schema_version': SCHEMA, 'target_ref': cfg['target'], 'checked_at': 0,
                        'interval_seconds': cfg['alerts']['interval_seconds'],
                        'cooldown_seconds': cfg['alerts']['cooldown_seconds'],
                        'overall': 'unknown', 'checks': []}
        self.stop = threading.Event()

    def refresh(self):
        with self.refresh_lock:
            return self._refresh()

    def refresh_async(self):
        """Start one background collection unless one is already running; never blocks the caller."""
        if self.refresh_lock.locked():
            return False
        threading.Thread(target=self.refresh, daemon=True).start()
        return True

    def _refresh(self):
        try:
            state = state_of(self.cfg, self.providers)
        except Exception:
            state = dict(self.current, checked_at=int(time.time()), overall='unknown',
                         checks=[{'id': check_id, 'state': 'unknown', 'code': 'COLLECTOR_FAILED'} for check_id in CHECK_IDS])
        with self.lock:
            self.current = state
        self.write(state)
        return state

    def write(self, state):
        try:
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
            os.replace(tmp, self.path)
        except OSError:
            pass

    def read(self):
        with self.lock:
            return dict(self.current)

    def loop(self):
        while not self.stop.is_set():
            started = time.monotonic()
            self.refresh()
            self.stop.wait(max(1.0, self.cfg['alerts']['interval_seconds'] - (time.monotonic() - started)))


def asset(name):
    mapping = {'': ('monitor.html', 'text/html; charset=utf-8'),
               'monitor.css': ('monitor.css', 'text/css; charset=utf-8'),
               'monitor.js': ('monitor.js', 'text/javascript; charset=utf-8'),
               'icon.png': ('icon.png', 'image/png')}
    return mapping.get(name)


def handler_for(store, token, clock):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def trusted(self):
            host = '127.0.0.1:%s' % self.server.server_port
            return (self.headers.get('Host') == host and self.headers.get('Origin', 'http://' + host) == 'http://' + host
                    and self.headers.get('Sec-Fetch-Site', 'same-origin') in {'same-origin', 'none'})

        def send(self, status, body, content_type='application/json; charset=utf-8'):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy',
                             "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'")
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.trusted() or not self.path.startswith('/' + token + '/'):
                return self.send(403, b'{}')
            clock['seen'] = time.monotonic()
            route = self.path[len(token) + 2:]
            if route == 'state':
                return self.send(200, json.dumps(store.read(), ensure_ascii=False).encode())
            entry = asset(route)
            if entry is None:
                return self.send(404, b'{}')
            name, mime = entry
            self.send(200, (ASSETS / name).read_bytes(), mime)
    return Handler


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def spawn_tray(state_path, url, cfg, show_file=''):
    argv = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
            '-File', str(ASSETS / 'tray.ps1'), '-StatePath', str(state_path), '-Url', url,
            '-IconDir', str(ICON_DIR), '-IntervalSeconds', str(cfg['alerts']['interval_seconds']),
            '-CooldownSeconds', str(cfg['alerts']['cooldown_seconds'])]
    if show_file:
        argv += ['-ShowFile', str(show_file)]
    try:
        return subprocess.Popen(argv, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError:
        return None


APP_ID = 'CCGuard.Monitor'
APP_NAME = 'CCGuard'
SHORTCUT_TOOL = ASSETS / 'notifier-shortcut.ps1'


def start_menu_shortcut():
    """The per-user Start menu entry that carries the notification identity (no admin rights)."""
    appdata = os.environ.get('APPDATA')
    if not appdata:
        raise MonitorError('找不到当前用户的 APPDATA 目录。')
    return Path(appdata) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / (APP_NAME + '.lnk')


def _shortcut_tool(action, path, runner=subprocess.run, **values):
    """Run the bundled helper; it only touches the one .lnk named by path."""
    argv = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(SHORTCUT_TOOL), '-Action', action, '-Path', str(path), '-AppId', APP_ID]
    for name, value in values.items():
        argv += ['-' + name, str(value)]
    try:
        proc = runner(argv, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired):
        raise MonitorError('无法运行 PowerShell 处理快捷方式。') from None
    try:
        result = json.loads((proc.stdout or '').strip().lstrip('﻿') or 'null')
    except ValueError:
        result = None
    if proc.returncode != 0 or not isinstance(result, dict):
        raise MonitorError('快捷方式操作失败：' + ((result or {}).get('error') if isinstance(result, dict)
                                                  else (proc.stderr or '').strip()[:200] or '未知错误'))
    return result


def _require_windows():
    if platform.system() != 'Windows':
        raise MonitorError('快捷方式操作只适用于 Windows。')


def _install_shortcut(config_path, path, hidden, runner):
    _require_windows()
    config_path = Path(config_path).resolve()
    load_config(config_path)
    argv = launcher_argv(config_path, 0, hidden=hidden)
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    target = pythonw if pythonw.is_file() else Path(sys.executable)
    return _shortcut_tool('Register', path, runner,
                          Target=target, Arguments=subprocess.list2cmdline(argv[1:]),
                          Icon=ICON.resolve(), WorkingDirectory=Path(__file__).resolve().parent)


def notifier_status(runner=subprocess.run, path=None):
    """{'registered': bool, ...}: registered only when our .lnk exists and carries our app id."""
    _require_windows()
    return _shortcut_tool('Status', path or start_menu_shortcut(), runner)


def register_notifier(config_path, runner=subprocess.run, path=None):
    """Create the per-user Start menu entry "CCGuard" with our app id, so toasts are named CCGuard.

    Windows ignores a toast identity that is only written to the registry (verified on Windows 11
    build 26300: the toast was dropped silently); the documented path for unpackaged apps is a
    Start menu shortcut carrying System.AppUserModel.ID. The shortcut also launches the panel.
    """
    return _install_shortcut(config_path, path or start_menu_shortcut(), False, runner)


def unregister_notifier(runner=subprocess.run, path=None):
    """Delete the shortcut only when it carries our app id; never touches anything else."""
    _require_windows()
    return _shortcut_tool('Unregister', path or start_menu_shortcut(), runner)


def startup_shortcut():
    """The per-user Startup entry used by the optional login autostart (no admin rights)."""
    appdata = os.environ.get('APPDATA')
    if not appdata:
        raise MonitorError('找不到当前用户的 APPDATA 目录。')
    return Path(appdata) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup' / (APP_NAME + '.lnk')


def autostart_status(runner=subprocess.run, path=None):
    """{'enabled': bool, ...}: the Startup shortcut exists and carries our app id."""
    _require_windows()
    result = _shortcut_tool('Status', path or startup_shortcut(), runner)
    return {'enabled': bool(result.get('registered')), 'path': result.get('path')}


def enable_autostart(config_path, runner=subprocess.run, path=None):
    """Opt-in: create a per-user Startup shortcut that opens the panel hidden in the tray."""
    return _install_shortcut(config_path, path or startup_shortcut(), True, runner)


def disable_autostart(runner=subprocess.run, path=None):
    """Remove only our Startup shortcut; never touches anything else."""
    _require_windows()
    return _shortcut_tool('Unregister', path or startup_shortcut(), runner)


def launcher_argv(config_path, idle_minutes, hidden=False):
    argv = [sys.executable, str(Path(__file__).resolve()), 'gui', '--config', str(config_path),
            '--tray', '--idle-minutes', str(idle_minutes)]
    if hidden:
        argv.append('--start-hidden')
    return argv


def default_config_path():
    base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
    if not base:
        raise MonitorError('找不到当前用户的 LOCALAPPDATA 目录。')
    return Path(base) / APP_NAME / 'monitor.json'


def quickstart_config(path=None, client='auto', runtime_config='', providers=None):
    """Create a usable config from detected values; never overwrite an existing file."""
    if client not in ('', 'auto', 'custom') and client not in CLIENT_PRESETS:
        raise MonitorError('client 必须是 auto、custom 或已知预设。')
    runtime = '' if not runtime_config else str(Path(runtime_config).expanduser())
    if runtime and not Path(runtime).is_absolute():
        raise MonitorError('运行配置必须是绝对路径。')
    path = Path(path).expanduser() if path else default_config_path()
    if path.exists():
        return load_config(path), path, False
    try:
        found = detect(providers)
    except MonitorError:
        found = {'client_guesses': []}
    if client in ('', 'auto'):
        guesses = found.get('client_guesses') or []
        chosen = guesses[0] if guesses else 'custom'
    else:
        chosen = client
    cfg = {
        'version': 1,
        'target': platform.node(),
        'proxy': {'client': chosen, 'tun_adapter': 'auto', 'config_format': 'auto',
                  'runtime_config': runtime},
        'firewall': {'expect_default_block': True, 'allow_rule_prefix': 'guardian-', 'min_allow_rules': 0},
        'network': {'expect_dns_servers': [], 'expect_ipv6_disabled': True},
        'alerts': {'cooldown_seconds': 120, 'notify_states': ['fail', 'degraded'], 'interval_seconds': 5},
    }
    write_config(path, cfg)
    return cfg, path, True


def desktop(config_path, output, idle_minutes=0):
    output = Path(output)
    if output.exists():
        raise MonitorError('输出目录已存在，请换一个新目录。')
    output.mkdir(parents=True)
    argv = launcher_argv(config_path, idle_minutes)
    system = platform.system()
    if system == 'Windows':
        icon = output / 'guardian.ico'
        shutil.copyfile(ICON, icon)
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        target = pythonw if pythonw.is_file() else Path(sys.executable)
        command = ('$s=(New-Object -ComObject WScript.Shell).CreateShortcut(' + _ps_quote(output / (APP_NAME + '.lnk')) + ');'
                   '$s.TargetPath=' + _ps_quote(target) + ';$s.Arguments=' + _ps_quote(subprocess.list2cmdline(argv[1:])) +
                   ';$s.IconLocation=' + _ps_quote(icon) + ';$s.Save()')
        subprocess.run(['powershell.exe', '-NoProfile', '-Command', command], check=True, timeout=30)
    elif system == 'Darwin':
        import plistlib
        contents = output / (APP_NAME + '.app/Contents')
        (contents / 'MacOS').mkdir(parents=True)
        (contents / 'Resources').mkdir()
        launcher = contents / 'MacOS/guardian-monitor'
        launcher.write_text('#!/bin/sh\nexec ' + shlex.join(argv) + '\n', encoding='utf-8')
        launcher.chmod(0o755)
        shutil.copyfile(ROOT / 'assets/killswitch/icon.icns', contents / 'Resources/guardian.icns')
        with (contents / 'Info.plist').open('wb') as out:
            plistlib.dump({'CFBundleName': APP_NAME, 'CFBundleDisplayName': APP_NAME,
                           'CFBundleIdentifier': 'org.claude-guardian.ccguard', 'CFBundlePackageType': 'APPL',
                           'CFBundleExecutable': 'guardian-monitor', 'CFBundleIconFile': 'guardian.icns'}, out)
    else:
        icon = output / 'guardian.png'
        shutil.copyfile(ROOT / 'assets/killswitch/icon.png', icon)
        def quote(value):
            return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('%', '%%') + '"'
        launcher = output / 'guardian-monitor.desktop'
        launcher.write_text('[Desktop Entry]\nType=Application\nName=' + APP_NAME + '\nComment=本机防护实时监测\nExec=' +
                            ' '.join(quote(a) for a in argv) + '\nIcon=' + str(icon) + '\nTerminal=false\nCategories=Network;\n',
                            encoding='utf-8')
        launcher.chmod(0o755)


def serve(cfg, state_dir, tray=False, open_browser=True, idle_minutes=15):
    if platform.system() != 'Windows':
        raise MonitorError('本版本的支持范围是 Windows。')
    if os.name == 'nt':
        import ctypes
        if ctypes.windll.shell32.IsUserAnAdmin():
            raise MonitorError('请以普通用户启动监测，不需要管理员权限。')
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / 'state.json'
    store = Store(cfg, state_path)
    store.refresh()
    threading.Thread(target=store.loop, daemon=True).start()
    token = secrets.token_urlsafe(24)
    clock = {'seen': time.monotonic()}
    server = HTTPServer(('127.0.0.1', 0), handler_for(store, token, clock))
    server.timeout = 5
    url = 'http://127.0.0.1:%s/%s/' % (server.server_port, token)
    child = spawn_tray(state_path, url, cfg) if tray else None
    print(url, flush=True)
    if open_browser:
        webbrowser.open(url)
    idle = idle_minutes * 60 if idle_minutes else 0
    try:
        while True:
            server.handle_request()
            if idle and time.monotonic() - clock['seen'] > idle:
                break
    finally:
        store.stop.set()
        server.server_close()
        if child is not None:
            child.terminate()


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='CCGuard 本机实时监测（只读、不联网）')
    parser.add_argument('action', choices=['quickstart', 'check', 'detect', 'serve', 'gui', 'desktop',
                                           'register-notifier', 'unregister-notifier', 'notifier-status',
                                           'autostart-enable', 'autostart-disable', 'autostart-status'])
    parser.add_argument('--config', type=Path)
    parser.add_argument('--tray', action='store_true')
    parser.add_argument('--start-hidden', action='store_true')
    parser.add_argument('--ui', choices=['auto', 'web', 'tk'], default='auto',
                        help='面板实现：auto 优先 WebView（pywebview），不可用时回退 tkinter')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--no-launch', action='store_true')
    parser.add_argument('--autostart', action='store_true')
    parser.add_argument('--client', default='auto')
    parser.add_argument('--runtime-config', type=Path)
    parser.add_argument('--idle-minutes', type=int, default=None)
    parser.add_argument('--state-dir', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == 'quickstart':
            cfg, config_path, created = quickstart_config(
                args.output, args.client, str(args.runtime_config) if args.runtime_config else '')
            print(('已创建配置：' if created else '沿用现有配置：') + str(config_path))
            if args.autostart:
                result = enable_autostart(config_path)
                print('已开启开机自启（仅当前用户）：' + result['path'] +
                      '\n登录 Windows 后会自动打开面板并隐藏到托盘。关闭：autostart-disable')
            if args.no_launch:
                return 0
            from monitor_webview import launch
            launch(cfg, config_path, tray=True, ui=args.ui)
            return 0
        if args.action == 'autostart-enable':
            if args.config is None:
                raise MonitorError('请用 --config 指定监测配置；开机自启会用它启动面板。')
            result = enable_autostart(args.config)
            print('已开启开机自启（仅当前用户）：' + result['path'] +
                  '\n登录 Windows 后会自动打开面板并隐藏到托盘。关闭：autostart-disable')
            return 0
        if args.action == 'autostart-disable':
            result = disable_autostart()
            print('已关闭开机自启。' if result.get('removed') else '未开启，无需关闭。')
            return 0
        if args.action == 'autostart-status':
            if platform.system() != 'Windows':
                print(json.dumps({'enabled': False}))
            else:
                print(json.dumps(autostart_status(), ensure_ascii=False))
            return 0
        if args.action == 'register-notifier':
            if args.config is None:
                raise MonitorError('请用 --config 指定监测配置；开始菜单入口会用它启动面板。')
            result = register_notifier(args.config)
            print('已在开始菜单创建「' + APP_NAME + '」（仅当前用户）：' + result['path'] +
                  '\n重新启动托盘后，通知会以 ' + APP_NAME + ' 署名。移动程序目录或配置后请重新注册。'
                  '撤销：unregister-notifier')
            return 0
        if args.action == 'unregister-notifier':
            result = unregister_notifier()
            print('已删除开始菜单入口。' if result.get('removed') else '未注册，无需移除。')
            return 0
        if args.action == 'notifier-status':
            if platform.system() != 'Windows':
                print(json.dumps({'registered': False}))
            else:
                print(json.dumps(notifier_status(), ensure_ascii=False))
            return 0
        if args.action == 'detect':
            print(json.dumps(detect(), ensure_ascii=False))
            return 0
        if args.config is None:
            raise MonitorError('请用 --config 指定监测配置。')
        cfg = load_config(args.config)
        if args.action == 'check':
            print(json.dumps(collect_state(cfg), ensure_ascii=False))
            return 0
        if args.action == 'serve':
            idle = 15 if args.idle_minutes is None else args.idle_minutes
            if idle < 0:
                raise MonitorError('idle-minutes 必须是 0 或正整数。')
            with tempfile.TemporaryDirectory(prefix='guardian-monitor-') as tmp:
                serve(cfg, args.state_dir or tmp, tray=args.tray, open_browser=not args.no_browser,
                      idle_minutes=idle)
            return 0
        if args.action == 'gui':
            if args.start_hidden and not args.tray:
                raise MonitorError('隐藏启动需要同时加 --tray，否则窗口无法找回。')
            from monitor_webview import launch
            launch(cfg, args.config, tray=args.tray, start_hidden=args.start_hidden, ui=args.ui)
            return 0
        if args.output is None:
            raise MonitorError('请用 --output 指定新的入口目录。')
        idle = 0 if args.idle_minutes is None else args.idle_minutes
        if idle < 0:
            raise MonitorError('idle-minutes 必须是 0 或正整数。')
        desktop(args.config.resolve(), args.output.resolve(), idle)
        print('监测入口已生成。请保持程序目录与配置文件位置不变。')
        return 0
    except MonitorError as error:
        sys.stderr.write(str(error) + '\n')
        return 2
    except KeyboardInterrupt:
        return 3


if __name__ == '__main__':
    raise SystemExit(main())

