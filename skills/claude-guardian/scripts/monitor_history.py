"""Local state history for the monitor panels: check ids and states only, no addresses or paths.

One JSON object per line in history.jsonl next to the monitor config:
  {"t": 1700000000, "e": "start"}            a panel started monitoring
  {"t": 1700000000, "id": "tun_adapter", "s": "fail"}   a check entered a state
  {"t": 1700000300, "e": "beat"}             still monitoring (bounds a crashed session)
  {"t": 1700000400, "e": "stop"}             the panel exited normally
"""
import json
import os
from pathlib import Path
import threading
import time

KEEP_SECONDS = 7 * 86400
BEAT_SECONDS = 300
FILE_NAME = 'history.jsonl'


def history_path(config_path):
    return Path(config_path).resolve().parent / FILE_NAME


def parse(lines):
    records = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if not isinstance(item, dict) or not isinstance(item.get('t'), (int, float)):
            continue
        if item.get('e') in ('start', 'stop', 'beat') or (
                isinstance(item.get('id'), str) and isinstance(item.get('s'), str)):
            records.append(item)
    return records


class History:
    def __init__(self, path, clock=time.time, keep=KEEP_SECONDS):
        self.path = Path(path)
        self.clock = clock
        self.keep = keep
        self.lock = threading.Lock()
        self.records = []
        self.last = {}
        self.last_write = 0
        self.writable = True

    def open(self):
        """Load what is kept, drop older lines from the file, and mark a new session."""
        now = self.clock()
        try:
            lines = self.path.read_text(encoding='utf-8').splitlines()
        except (OSError, UnicodeDecodeError):
            lines = []
        loaded = parse(lines)
        self.records = [item for item in loaded if item['t'] >= now - self.keep]
        if len(self.records) != len(lines):
            self._rewrite()
        self._append([{'t': int(now), 'e': 'start'}])
        return self

    def record(self, states):
        """Append the checks whose state changed; a beat when nothing was written for a while."""
        now = int(self.clock())
        changed = [{'t': now, 'id': check_id, 's': state}
                   for check_id, state in sorted(states.items()) if self.last.get(check_id) != state]
        if changed:
            self.last.update({item['id']: item['s'] for item in changed})
            self._append(changed)
        elif now - self.last_write >= BEAT_SECONDS:
            self._append([{'t': now, 'e': 'beat'}])
        return changed

    def close(self):
        self._append([{'t': int(self.clock()), 'e': 'stop'}])

    def snapshot(self, since=0):
        with self.lock:
            return [item for item in self.records if item['t'] >= since]

    def _append(self, items):
        with self.lock:
            self.records.extend(items)
            cutoff = self.clock() - self.keep
            if self.records and self.records[0]['t'] < cutoff:
                self.records = [item for item in self.records if item['t'] >= cutoff]
            self.last_write = items[-1]['t']
            if not self.writable:
                return
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open('a', encoding='utf-8') as handle:
                    for item in items:
                        handle.write(json.dumps(item, separators=(',', ':')) + '\n')
            except OSError:
                # The panel keeps working from memory; history simply stops persisting.
                self.writable = False

    def _rewrite(self):
        tmp = self.path.with_suffix('.tmp')
        try:
            tmp.write_text(''.join(json.dumps(item, separators=(',', ':')) + '\n' for item in self.records),
                           encoding='utf-8')
            os.replace(tmp, self.path)
        except OSError:
            pass


def timeline(records, now, window, check_ids, live=True):
    """Per check, [{'s': start, 'e': end, 'state': state}] clipped to the window.

    Time outside any monitoring session has no segment (shown as "not monitored"). A session
    without a stop record ends at its last record; the open session ends at `now` when live.
    """
    begin = now - window
    segments = {check_id: [] for check_id in check_ids}
    current = {}
    active = False
    last_seen = None

    def add(check_id, start, end, state):
        start, end = max(start, begin), min(end, now)
        if check_id in segments and end > start:
            row = segments[check_id]
            if row and row[-1]['state'] == state and row[-1]['e'] >= start:
                row[-1]['e'] = end
            else:
                row.append({'s': start, 'e': end, 'state': state})

    def close(end):
        for check_id, (state, since) in current.items():
            add(check_id, since, end, state)
        current.clear()

    for item in sorted(records, key=lambda record: record['t']):
        moment = item['t']
        event = item.get('e')
        if event == 'start':
            if active:
                close(last_seen)
            active = True
        elif not active:
            continue
        elif event == 'stop':
            close(moment)
            active = False
        elif 'id' in item:
            previous = current.get(item['id'])
            if previous is not None:
                add(item['id'], previous[1], moment, previous[0])
            current[item['id']] = (item['s'], moment)
        last_seen = moment
    if active:
        close(now if live else last_seen)
    return segments


def last_change(records, check_id):
    """Time the check last entered a different state, or None."""
    changes = [item for item in records if item.get('id') == check_id]
    for index in range(len(changes) - 1, 0, -1):
        if changes[index]['s'] != changes[index - 1]['s']:
            return changes[index]['t']
    return None
