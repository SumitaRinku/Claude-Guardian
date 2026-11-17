"""What each check looks at and how to fix it, keyed by check id and result code."""

DETECT = '运行 `monitor.py detect`，核对实际的进程名和网卡名'
CONFIG = '确认配置里的 `proxy.runtime_config` 指向客户端实际加载的配置文件，`proxy.config_format` 与它的格式一致'

CHECKS = {
    'proxy_core': '代理客户端的核心进程是否在运行。',
    'tun_adapter': 'TUN 虚拟网卡是否存在并处于启用状态。',
    'default_route': '系统默认路由是否经由 TUN 网卡。',
    'firewall_block': '三个防火墙配置文件是否都已启用，且默认出站为阻止。',
    'guardian_rules': '防火墙里 Guardian 放行规则的数量是否达到配置下限。',
    'core_ipv6': '代理核心的运行配置是否关闭了 IPv6。',
    'strict_route': '代理核心的运行配置是否开启了严格路由。',
    'dns_hijack': '代理核心是否接管系统的 DNS 查询。',
    'dns_servers': '物理网卡的 DNS 是否等于配置里的期望值。',
    'os_ipv6': '物理网卡的 IPv6 绑定是否已禁用。',
}

STEPS = {
    'PROXY_CORE_MISSING': [
        '打开代理客户端并连接。',
        '仍显示失效时运行 `monitor.py detect`，把实际进程名填进 `proxy.process_names`，或改选 `proxy.client` 预设。',
    ],
    'TUN_ADAPTER_MISSING': [
        '在代理客户端里开启 TUN（虚拟网卡）模式。',
        '仍找不到时运行 `monitor.py detect`，把实际网卡名填进 `proxy.tun_adapter`。',
    ],
    'TUN_ADAPTER_DOWN': [
        '在代理客户端里关闭再重新开启 TUN 模式。',
        '仍未启用时重启代理客户端。',
    ],
    'DEFAULT_ROUTE_MISSING': [
        '检查网络是否已连接。',
        '刚切换网络或重连代理时，等代理客户端重建 TUN。',
    ],
    'DEFAULT_ROUTE_NOT_TUN': [
        '在代理客户端里重新开启 TUN，并确认自动路由已开启。',
        '开启严格路由，避免其他网卡抢走默认路由。',
    ],
    'FIREWALL_PROFILE_DISABLED': [
        '在“Windows 安全中心 → 防火墙和网络保护”里，把域、专用、公用网络的防火墙全部打开。',
    ],
    'DEFAULT_OUTBOUND_ALLOW': [
        '用断网保护开关重新开启防护：`killswitch.py on --config <开关配置>`，需要管理员权限。',
    ],
    'GUARDIAN_RULES_MISSING': [
        '重新开启断网保护会恢复放行规则。',
        '规则名前缀不是 `guardian-` 时，改配置里的 `firewall.allow_rule_prefix`。',
    ],
    'CORE_IPV6_ON': [
        '在代理客户端里关闭 IPv6（Clash：`ipv6: false`）。',
    ],
    'STRICT_ROUTE_OFF': [
        '开启严格路由：Clash 为 `tun.strict-route: true`，sing-box 为 `strict_route: true`。',
    ],
    'DNS_HIJACK_MISSING': [
        '开启 DNS 接管：Clash 为 `tun.dns-hijack`，sing-box 为路由规则 `hijack-dns`。',
    ],
    'DNS_SERVERS_DIFFER': [
        '把物理网卡的 DNS 改回部署时设定的地址。',
        '期望值本身变了时，更新配置里的 `network.expect_dns_servers`。',
    ],
    'OS_IPV6_ENABLED': [
        '在网卡属性里取消勾选“Internet 协议版本 6 (TCP/IPv6)”。',
    ],
    'NO_PHYSICAL_ADAPTER': [
        '当前没有已连接的物理网卡，联网后自动恢复。',
    ],
    'CORE_CONFIG_UNAVAILABLE': [CONFIG + '。'],
    'STRICT_ROUTE_UNKNOWN': [CONFIG + '。'],
    'DNS_HIJACK_UNKNOWN': [CONFIG + '。'],
    'COLLECTOR_FAILED': ['本次采集出错，等下一次采集。持续出现时重启 CCGuard。'],
}
# Steps for a fail/degraded result whose code is not listed above (e.g. a newer engine code).
PRIMARY = {
    'proxy_core': 'PROXY_CORE_MISSING', 'tun_adapter': 'TUN_ADAPTER_MISSING',
    'default_route': 'DEFAULT_ROUTE_NOT_TUN', 'firewall_block': 'DEFAULT_OUTBOUND_ALLOW',
    'guardian_rules': 'GUARDIAN_RULES_MISSING', 'core_ipv6': 'CORE_IPV6_ON',
    'strict_route': 'STRICT_ROUTE_OFF', 'dns_hijack': 'DNS_HIJACK_MISSING',
    'dns_servers': 'DNS_SERVERS_DIFFER', 'os_ipv6': 'OS_IPV6_ENABLED',
}
UNKNOWN_STEPS = ['读不到这一项。等下一次采集；持续出现时，' + DETECT + '。']


def guide(check_id, state, code):
    """{'checks': what is checked, 'steps': what to do now} for the card detail view."""
    if state == 'ok':
        steps = []
    else:
        steps = STEPS.get(code)
        if steps is None:
            steps = UNKNOWN_STEPS if state == 'unknown' else STEPS.get(PRIMARY.get(check_id), [])
    return {'checks': CHECKS.get(check_id, ''), 'steps': list(steps)}
