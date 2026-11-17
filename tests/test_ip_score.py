"""Exit IP trust score: offline with fake HTTP; never touches the network."""
import importlib
import json
from pathlib import Path
import sys
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/claude-guardian/scripts'
sys.path.insert(0, str(SCRIPTS))

score = importlib.import_module('ip_score')
monitor = importlib.import_module('monitor')

IP = '203.0.113.45'
TRACE = ('fl=1\nh=1.1.1.1\nip=%s\nts=1\nvisit_scheme=https\nuag=CCGuard\ncolo=NRT\nloc=JP\n' % IP).encode()
RISK = {'trust_score': 96, 'countryCode': 'jp', 'country': 'Japan', 'region': 'Tokyo', 'city': 'Tokyo',
        'asn': 64500, 'asOrganization': 'Example ISP', 'isResidential': True, 'is_datacenter': False,
        'is_vpn': False, 'is_proxy': False, 'is_tor': False, 'is_abuser': False, 'is_crawler': False,
        'timezone': 'Asia/Tokyo', 'ip': IP}


class FakeHttp:
    def __init__(self, trace=(200, TRACE), risk=None):
        self.trace = trace
        self.risk = risk if risk is not None else (200, json.dumps(RISK).encode())
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if url == score.TRACE_URL:
            if isinstance(self.trace, Exception):
                raise self.trace
            return self.trace
        if isinstance(self.risk, Exception):
            raise self.risk
        return self.risk


class Check(unittest.TestCase):
    def run_check(self, http):
        return score.check(get=http, clock=lambda: 1_700_000_000)

    def test_success_reports_score_facts_and_every_step(self):
        http = FakeHttp()
        result = self.run_check(http)
        self.assertTrue(result['ok'])
        self.assertEqual((result['score'], result['label'], result['level']), (96, '极度纯净', 'ok'))
        self.assertEqual(result['ip'], '203.0.*.*')
        self.assertEqual(result['facts']['kind'], '住宅')
        self.assertEqual(result['facts']['location'], 'Japan Tokyo Tokyo')
        self.assertEqual(result['facts']['network'], 'AS64500 Example ISP')
        self.assertEqual(result['facts']['flags'], [])
        self.assertEqual(http.urls, [score.TRACE_URL, score.RISK_URL + IP])
        texts = [line['text'] for line in result['log']]
        self.assertTrue(texts[0].startswith('请求 ' + score.TRACE_URL))
        self.assertIn('信任分 96（极度纯净）', texts[-1])

    def test_full_ip_never_appears_in_the_result(self):
        body = json.dumps(self.run_check(FakeHttp()), ensure_ascii=False)
        self.assertNotIn(IP, body)

    def test_only_cloudflare_and_ip_net_coffee_are_contacted(self):
        for url in (score.TRACE_URL, score.RISK_URL, score.DETAIL_URL):
            self.assertNotIn('claude.ai', url)
            self.assertNotIn('anthropic', url)
        source = (SCRIPTS / 'ip_score.py').read_text(encoding='utf-8')
        self.assertNotIn('claude.ai/', source)
        self.assertNotIn('anthropic.com', source)

    def test_restricted_region_scores_zero(self):
        risk = dict(RISK, countryCode='hk', trust_score=99)
        result = self.run_check(FakeHttp(risk=(200, json.dumps(risk).encode())))
        self.assertEqual((result['score'], result['label'], result['level']), (0, '不可访问', 'fail'))
        self.assertTrue(any('香港' in line['text'] for line in result['log']))

    def test_flags_and_datacenter(self):
        risk = dict(RISK, isResidential=False, is_datacenter=True, is_vpn=True, is_abuser=True, trust_score=40)
        result = self.run_check(FakeHttp(risk=(200, json.dumps(risk).encode())))
        self.assertEqual(result['facts']['kind'], '机房')
        self.assertEqual(result['facts']['flags'], ['VPN', '滥用记录'])
        self.assertEqual((result['label'], result['level']), ('中性', 'fail'))

    def test_ipv6_exit_is_noted(self):
        trace = TRACE.replace(IP.encode(), b'2001:db8:1:2::5')
        result = self.run_check(FakeHttp(trace=(200, trace)))
        self.assertTrue(result['ipv6'])
        self.assertEqual(result['ip'], '2001:0db8:*')
        self.assertTrue(any('IPv6' in line['text'] and line['ok'] is False for line in result['log']))

    def test_failures_are_reported_not_raised(self):
        cases = [
            FakeHttp(trace=urllib.error.URLError('offline')),
            FakeHttp(trace=TimeoutError('timed out')),
            FakeHttp(trace=(200, b'no ip here')),
            FakeHttp(trace=(503, b'')),
            FakeHttp(risk=(500, b'')),
            FakeHttp(risk=(200, b'<html>')),
            FakeHttp(risk=(200, b'[1]')),
            FakeHttp(risk=(200, json.dumps(dict(RISK, trust_score=None)).encode())),
            FakeHttp(risk=(200, json.dumps(dict(RISK, trust_score=True)).encode())),
        ]
        for http in cases:
            result = self.run_check(http)
            self.assertFalse(result['ok'], http.trace)
            self.assertTrue(result['error'])
            self.assertTrue(result['log'][-1]['text'].startswith('检测失败'))
            self.assertNotIn('score', result)


class Helpers(unittest.TestCase):
    def test_label_bands_match_the_page(self):
        self.assertEqual([score.label(v) for v in (100, 95, 94, 80, 79, 50, 49, 25, 24, 0)],
                         ['极度纯净', '极度纯净', '纯净', '纯净', '良好', '良好', '中性', '中性', '可疑', '可疑'])

    def test_mask_ip(self):
        self.assertEqual(score.mask_ip('198.51.100.7'), '198.51.*.*')
        self.assertEqual(score.mask_ip('2001:db8::1'), '2001:0db8:*')
        self.assertEqual(score.mask_ip('nope'), '无效地址')


class Cli(unittest.TestCase):
    def test_ip_score_needs_no_config_and_exit_code_follows_result(self):
        with patch.object(score, 'check', return_value={'ok': True, 'score': 90}):
            self.assertEqual(monitor.main(['ip-score']), 0)
        with patch.object(score, 'check', return_value={'ok': False, 'error': 'x'}):
            self.assertEqual(monitor.main(['ip-score']), 1)


if __name__ == '__main__':
    unittest.main()
