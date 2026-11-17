"""Version number, bundled update log and the manual update check; offline with fake HTTP."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/claude-guardian/scripts'
sys.path.insert(0, str(SCRIPTS))

update = importlib.import_module('app_update')
version = importlib.import_module('version')
monitor = importlib.import_module('monitor')

PAGE = 'https://github.com/SumitaRinku/CCguard/releases'


def release(tag, **extra):
    item = {'tag_name': tag, 'name': 'CCGuard ' + tag, 'published_at': '2026-12-01T00:00:00Z',
            'html_url': PAGE + '/tag/' + tag, 'body': '## 本次更新\n\n- **新功能** `x`\n- 修复 [问题](http://example)\n',
            'assets': [{'name': 'CCGuard-Setup-%s.exe' % tag.lstrip('v'),
                        'browser_download_url': PAGE + '/download/%s/CCGuard-Setup-%s.exe' % (tag, tag.lstrip('v'))},
                       {'name': 'claude-guardian.zip', 'browser_download_url': PAGE + '/download/x.zip'}]}
    item.update(extra)
    return item


def fake(items, status=200):
    calls = []

    def get(url):
        calls.append(url)
        if isinstance(items, Exception):
            raise items
        return status, json.dumps(items).encode() if not isinstance(items, bytes) else items
    get.calls = calls
    return get


class Version(unittest.TestCase):
    def test_single_source(self):
        self.assertIsNotNone(update.parse_version(version.__version__))
        self.assertEqual(update.__version__, version.__version__)

    def test_cli_prints_it(self):
        with self.assertRaises(SystemExit) as raised, patch('sys.stdout') as out:
            monitor.main(['--version'])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn(version.__version__, ''.join(call.args[0] for call in out.write.call_args_list))

    def test_bundled_update_log_starts_with_this_version(self):
        notes = update.release_notes()
        self.assertEqual(notes[0]['version'], version.__version__)
        self.assertTrue(all(entry['items'] and all(isinstance(i, str) and i for i in entry['items']) for entry in notes))
        numbers = [update.parse_version(entry['version']) for entry in notes]
        self.assertEqual(numbers, sorted(numbers, reverse=True))
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_update_log_is_shipped(self):
        package = (ROOT / 'tools/package_skill.py').read_text(encoding='utf-8')
        for path in ('scripts/app_update.py', 'scripts/version.py', 'assets/monitor/release-notes.json'):
            self.assertIn('"%s"' % path, package)

    def test_unreadable_log_is_empty_not_an_error(self):
        with tempfile.TemporaryDirectory() as folder:
            broken = Path(folder) / 'notes.json'
            broken.write_text('not json', encoding='utf-8')
            self.assertEqual(update.release_notes(broken), [])
            self.assertEqual(update.release_notes(Path(folder) / 'missing.json'), [])


class Check(unittest.TestCase):
    def test_newer_releases_newest_first_with_notes_and_installer(self):
        items = [release('v0.6.0'), release('v0.7.0'), release('v0.8.0', draft=True),
                 release('v0.9.0', prerelease=True), release('v0.6.1'), release('nightly'), 'junk']
        get = fake(items)
        result = update.check(get=get, current='0.6.0', clock=lambda: 0)
        self.assertEqual(get.calls, [update.RELEASES_API])
        self.assertTrue(result['ok'] and result['update'])
        self.assertEqual([r['version'] for r in result['releases']], ['0.7.0', '0.6.1'])
        self.assertEqual(result['latest'], '0.7.0')
        top = result['releases'][0]
        self.assertEqual(top['installer_url'], PAGE + '/download/v0.7.0/CCGuard-Setup-0.7.0.exe')
        self.assertEqual(top['notes'], ['本次更新', '新功能 x', '修复 问题'])
        json.dumps(result, ensure_ascii=False)

    def test_up_to_date(self):
        result = update.check(get=fake([release('v0.5.1'), release('v0.6.0')]), current='0.6.0')
        self.assertTrue(result['ok'])
        self.assertFalse(result['update'])
        self.assertEqual(result['releases'], [])
        self.assertEqual(result['log'][-1]['text'], '已是最新版本 0.6.0')

    def test_links_outside_this_repository_are_dropped(self):
        evil = release('v0.7.0', html_url='https://evil.example/x')
        evil['assets'][0]['browser_download_url'] = 'https://evil.example/CCGuard-Setup-0.7.0.exe'
        top = update.check(get=fake([evil]), current='0.6.0')['releases'][0]
        self.assertEqual(top['page_url'], PAGE)
        self.assertIsNone(top['installer_url'])

    def test_failures_are_reported_not_raised(self):
        for get in (fake(urllib.error.URLError('offline')), fake(TimeoutError('slow')), fake([], status=403),
                    fake(b'<html>'), fake({'message': 'rate limited'})):
            result = update.check(get=get, current='0.6.0')
            self.assertFalse(result['ok'])
            self.assertTrue(result['error'])
            self.assertTrue(result['log'][-1]['text'].startswith('检查失败'))
        self.assertFalse(update.check(get=fake([]), current='dev')['ok'])

    def test_only_github_is_contacted(self):
        self.assertTrue(update.RELEASES_API.startswith('https://api.github.com/repos/SumitaRinku/CCguard/'))
        source = (SCRIPTS / 'app_update.py').read_text(encoding='utf-8')
        self.assertNotIn('claude.ai', source)
        self.assertNotIn('anthropic.com', source)

    def test_notes_are_plain_and_bounded(self):
        lines = update.plain_notes('| a | b |\n|---|---|\n# H\n' + '- x' * 1 + '\n' + ('长' * 300 + '\n') * 30)
        self.assertEqual(lines[:2], ['H', 'x'])
        self.assertEqual(lines[-1], '…')
        self.assertLessEqual(sum(len(line) for line in lines), update.NOTES_LIMIT + 1)
        self.assertNotIn('·', ''.join(update.plain_notes('- a\n- b')))

    def test_allowed_url(self):
        self.assertTrue(update.allowed_url(PAGE))
        self.assertTrue(update.allowed_url(PAGE + '/tag/v1.0.0'))
        for bad in ('https://github.com/SumitaRinku/CCguard', 'https://github.com/SumitaRinku/CCguard/releasesX',
                    'https://evil.example/' + PAGE, None, 5):
            self.assertFalse(update.allowed_url(bad), bad)


class Cli(unittest.TestCase):
    def test_update_check_exit_code_follows_result(self):
        with patch.object(update, 'check', return_value={'ok': True}), patch('sys.stdout'):
            self.assertEqual(monitor.main(['update-check']), 0)
        with patch.object(update, 'check', return_value={'ok': False}), patch('sys.stdout'):
            self.assertEqual(monitor.main(['update-check']), 1)


if __name__ == '__main__':
    unittest.main()
