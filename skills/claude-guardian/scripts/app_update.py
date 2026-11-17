"""Manual update check for CCGuard: run only when the user clicks.

One request: https://api.github.com/repos/SumitaRinku/CCguard/releases (the public release list).
Nothing is downloaded or installed; newer versions and their notes are shown and the release page
opens in the user's own browser. Contacts only GitHub, never Claude or Anthropic.
(scripts/update_check.py is a different tool: it compares the Skill files with upstream.)
"""
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

from version import __version__

REPO = 'SumitaRinku/CCguard'
RELEASES_API = 'https://api.github.com/repos/%s/releases?per_page=20' % REPO
RELEASES_PAGE = 'https://github.com/%s/releases' % REPO
TIMEOUT = 10
NOTES_LIMIT = 4000


class UpdateError(Exception):
    pass


def parse_version(text):
    """'v0.6.0' / '0.6.0' -> (0, 6, 0); None when it is not a plain X.Y.Z."""
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', str(text or '').strip())
    return tuple(int(part) for part in match.groups()) if match else None


def allowed_url(url):
    """Only this repository's release pages and assets may be opened from the panel."""
    return isinstance(url, str) and (url == RELEASES_PAGE or url.startswith(RELEASES_PAGE + '/'))


def plain_notes(markdown):
    """Release body as short plain lines for the panel (shown as text, never as HTML)."""
    lines, size = [], 0
    for raw in str(markdown or '').splitlines():
        line = raw.strip()
        if not line or line.startswith('|') or set(line) <= set('-|: '):
            continue
        line = re.sub(r'^#+\s*', '', line)
        line = re.sub(r'^[-*]\s+', '', line)
        line = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
        line = re.sub(r'`([^`]*)`', r'\1', line)
        line = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', line)
        size += len(line)
        if size > NOTES_LIMIT:
            lines.append('…')
            break
        lines.append(line)
    return lines


def http_get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'CCGuard/' + __version__,
                                                  'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.status, response.read(4 * 1024 * 1024)


def check(get=http_get, current=__version__, clock=time.time):
    """Newer published releases than `current`, newest first; never raises."""
    log = []

    def note(text, ok=None):
        log.append({'time': time.strftime('%H:%M:%S', time.localtime(clock())), 'text': text, 'ok': ok})

    result = {'ok': False, 'current': current, 'update': False, 'releases': [], 'page_url': RELEASES_PAGE,
              'checked_at': int(clock()), 'log': log}
    try:
        mine = parse_version(current)
        if mine is None:
            raise UpdateError('当前版本号无法识别：%s' % current)
        note('请求 ' + RELEASES_API + '，读取已发布的版本')
        status, body = get(RELEASES_API)
        if status != 200:
            raise UpdateError('GitHub 返回 HTTP %s' % status)
        try:
            items = json.loads(body.decode('utf-8'))
        except ValueError:
            raise UpdateError('GitHub 返回的不是 JSON') from None
        if not isinstance(items, list):
            raise UpdateError('GitHub 返回格式不对')
        newer = []
        for item in items:
            if not isinstance(item, dict) or item.get('draft') or item.get('prerelease'):
                continue
            number = parse_version(item.get('tag_name'))
            if number is None or number <= mine:
                continue
            installer = next((asset.get('browser_download_url') for asset in item.get('assets') or []
                              if isinstance(asset, dict) and str(asset.get('name', '')).startswith('CCGuard-Setup-')
                              and str(asset.get('name', '')).endswith('.exe')), None)
            page = item.get('html_url')
            newer.append({'number': number, 'version': '.'.join(map(str, number)),
                          'name': str(item.get('name') or item.get('tag_name')),
                          'date': str(item.get('published_at') or '')[:10],
                          'page_url': page if allowed_url(page) else RELEASES_PAGE,
                          'installer_url': installer if allowed_url(installer) else None,
                          'notes': plain_notes(item.get('body'))})
        newer.sort(key=lambda entry: entry['number'], reverse=True)
        for entry in newer:
            entry.pop('number')
        result.update(ok=True, update=bool(newer), releases=newer,
                      latest=newer[0]['version'] if newer else current)
        note('发现新版本 %s' % newer[0]['version'] if newer else '已是最新版本 %s' % current, True if not newer else None)
    except (UpdateError, urllib.error.URLError, OSError, ValueError) as error:
        reason = getattr(error, 'reason', None) or error
        result['error'] = str(reason)
        note('检查失败：%s' % reason, False)
    return result


def release_notes(path=None):
    """The bundled update log: [{version, date, items}], newest first; [] if unreadable."""
    if path is None:
        import monitor  # resolves the asset folder for both the script and the frozen exe
        path = monitor.ICON_DIR / 'release-notes.json'
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    notes = [entry for entry in data if isinstance(entry, dict) and parse_version(entry.get('version'))
             and isinstance(entry.get('items'), list)]
    return sorted(notes, key=lambda entry: parse_version(entry['version']), reverse=True)
