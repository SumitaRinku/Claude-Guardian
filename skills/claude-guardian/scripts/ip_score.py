"""Exit IP trust score from ip.net.coffee, run only when the user asks.

Two requests over the current network, nothing else:
  1. https://1.1.1.1/cdn-cgi/trace           Cloudflare reports the exit IP it sees.
  2. https://ip.net.coffee/api/iprisk/<ip>    the trust score and IP attributes for that IP.

Neither request goes to Claude or Anthropic. The full browser check (including the exit IP that
claude.ai sees, DNS and WebRTC leaks) stays on https://ip.net.coffee/claude/, which the user opens
in their own browser. Results keep only a masked IP.
"""
import ipaddress
import json
import time
import urllib.error
import urllib.request

TRACE_URL = 'https://1.1.1.1/cdn-cgi/trace'
RISK_URL = 'https://ip.net.coffee/api/iprisk/'
DETAIL_URL = 'https://ip.net.coffee/claude/'
TIMEOUT = 10
USER_AGENT = 'CCGuard'
# Regions where the page forces the score to 0 (Claude blocks or tightly restricts them).
RESTRICTED = {
    'CN': '中国大陆', 'HK': '香港', 'MO': '澳门', 'RU': '俄罗斯', 'KP': '朝鲜', 'IR': '伊朗',
    'SY': '叙利亚', 'CU': '古巴', 'BY': '白俄罗斯', 'VE': '委内瑞拉',
}
COMPANY_TYPES = {'isp': '运营商', 'hosting': '机房', 'business': '企业', 'education': '教育', 'government': '政府'}


class ScoreError(Exception):
    pass


def label(score):
    """The page's bands: 95 极度纯净, 80 纯净, 50 良好, 25 中性, below 可疑."""
    if score >= 95:
        return '极度纯净'
    if score >= 80:
        return '纯净'
    if score >= 50:
        return '良好'
    if score >= 25:
        return '中性'
    return '可疑'


def level(score):
    """Panel colour: ok from 80, degraded from 50, otherwise fail."""
    return 'ok' if score >= 80 else 'degraded' if score >= 50 else 'fail'


def mask_ip(text):
    try:
        ip = ipaddress.ip_address(str(text).strip())
    except ValueError:
        return '无效地址'
    if ip.version == 4:
        parts = str(ip).split('.')
        return '%s.%s.*.*' % (parts[0], parts[1])
    return ':'.join(ip.exploded.split(':')[:2]) + ':*'


def http_get(url):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': '*/*'})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.status, response.read(256 * 1024)


def parse_trace(body):
    fields = {}
    for line in body.decode('utf-8', 'replace').splitlines():
        key, _, value = line.partition('=')
        if key:
            fields[key.strip()] = value.strip()
    try:
        ipaddress.ip_address(fields.get('ip', ''))
    except ValueError:
        raise ScoreError('Cloudflare 没有返回出口 IP') from None
    return fields


def facts(data):
    flags = [name for key, name in (('is_vpn', 'VPN'), ('is_proxy', '代理'), ('is_tor', 'Tor'),
                                     ('is_abuser', '滥用记录'), ('is_crawler', '爬虫'))
             if data.get(key) is True]
    if data.get('isResidential') is True:
        kind = '住宅'
    elif data.get('is_datacenter') is True:
        kind = '机房'
    elif data.get('is_mobile') is True:
        kind = '移动网络'
    else:
        kind = COMPANY_TYPES.get(str(data.get('company_type') or ''), '未知')
    place = ' '.join(str(data[key]) for key in ('country', 'region', 'city') if data.get(key))
    org = str(data.get('asOrganization') or data.get('company_name') or '')
    asn = data.get('asn')
    return {
        'location': place or '未知',
        'network': (('AS%s ' % asn) if asn else '') + org if (asn or org) else '未知',
        'kind': kind,
        'timezone': str(data.get('timezone') or '未知'),
        'flags': flags,
    }


def check(get=http_get, clock=time.time):
    """Run both requests and return the result with a step-by-step log; never raises."""
    log = []

    def note(text, ok=None):
        log.append({'time': time.strftime('%H:%M:%S', time.localtime(clock())), 'text': text, 'ok': ok})

    result = {'ok': False, 'checked_at': int(clock()), 'detail_url': DETAIL_URL, 'log': log}
    try:
        note('请求 ' + TRACE_URL + '，由 Cloudflare 返回本机当前的出口 IP')
        status, body = get(TRACE_URL)
        if status != 200:
            raise ScoreError('Cloudflare 返回 HTTP %s' % status)
        trace = parse_trace(body)
        masked = mask_ip(trace['ip'])
        ipv6 = ':' in trace['ip']
        note('出口 IP %s，Cloudflare 节点 %s，地区 %s' % (masked, trace.get('colo', '未知'), trace.get('loc', '未知')), True)
        if ipv6:
            note('出口是 IPv6：Claude 网页会走 IPv6，按整机 IPv4 指引关闭 IPv6', False)
        note('请求 ' + RISK_URL + masked + '（实际发送完整 IP），获取信任分与 IP 属性')
        status, body = get(RISK_URL + trace['ip'])
        if status != 200:
            raise ScoreError('ip.net.coffee 返回 HTTP %s' % status)
        try:
            data = json.loads(body.decode('utf-8'))
        except ValueError:
            raise ScoreError('ip.net.coffee 返回的不是 JSON') from None
        if not isinstance(data, dict):
            raise ScoreError('ip.net.coffee 返回格式不对')
        code = str(data.get('countryCode') or '').upper()
        raw = data.get('trust_score')
        if code in RESTRICTED:
            score, name = 0, '不可访问'
            note('出口位于%s，Claude 不提供服务，按页面规则记 0 分' % RESTRICTED[code], False)
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
            score = int(round(raw))
            name = label(score)
            note('信任分 %d（%s）' % (score, name), score >= 80)
        else:
            raise ScoreError('该 IP 暂无评分数据')
        result.update(ok=True, score=score, label=name, level='fail' if code in RESTRICTED else level(score),
                      ip=masked, ipv6=ipv6, facts=facts(data))
        if result['facts']['flags']:
            note('标记：' + '、'.join(result['facts']['flags']), False)
    except (ScoreError, urllib.error.URLError, OSError, ValueError) as error:
        reason = getattr(error, 'reason', None) or error
        result['error'] = str(reason)
        note('检测失败：%s' % reason, False)
    return result
