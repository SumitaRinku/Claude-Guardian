"""State history store, timeline segments and per-check guidance; no window, no system probes."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/claude-guardian/scripts'))

history = importlib.import_module('monitor_history')
guide = importlib.import_module('monitor_guide')
engine = importlib.import_module('monitor')


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'sub' / 'history.jsonl'
        self.clock = Clock(10_000_000)

    def tearDown(self):
        self.tmp.cleanup()

    def lines(self):
        return [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines()]

    def test_session_writes_start_changes_beat_and_stop(self):
        log = history.History(self.path, clock=self.clock).open()
        self.assertEqual(log.record({'a': 'ok', 'b': 'ok'}), [
            {'t': 10_000_000, 'id': 'a', 's': 'ok'}, {'t': 10_000_000, 'id': 'b', 's': 'ok'}])
        self.clock.now += 10
        self.assertEqual(log.record({'a': 'ok', 'b': 'fail'}), [{'t': 10_000_010, 'id': 'b', 's': 'fail'}])
        self.clock.now += 10
        self.assertEqual(log.record({'a': 'ok', 'b': 'fail'}), [])
        self.clock.now += history.BEAT_SECONDS
        log.record({'a': 'ok', 'b': 'fail'})
        log.close()
        kinds = [item.get('e') or item['id'] for item in self.lines()]
        self.assertEqual(kinds, ['start', 'a', 'b', 'b', 'beat', 'stop'])

    def test_only_ids_and_states_are_stored(self):
        log = history.History(self.path, clock=self.clock).open()
        log.record({'tun_adapter': 'fail'})
        for item in self.lines():
            self.assertLessEqual(set(item), {'t', 'e', 'id', 's'})

    def test_open_drops_expired_and_corrupt_lines(self):
        self.path.parent.mkdir(parents=True)
        old = {'t': self.clock.now - history.KEEP_SECONDS - 5, 'e': 'start'}
        fresh = {'t': self.clock.now - 60, 'id': 'a', 's': 'ok'}
        self.path.write_text('\n'.join([json.dumps(old), 'not json', '{"t": "x"}', '[1]',
                                        json.dumps({'t': 1, 'id': 3, 's': 'ok'}), json.dumps(fresh)]) + '\n',
                             encoding='utf-8')
        log = history.History(self.path, clock=self.clock).open()
        self.assertEqual(log.snapshot()[0], fresh)
        self.assertEqual(self.lines()[0], fresh)
        self.assertEqual(self.lines()[-1]['e'], 'start')

    def test_new_session_restates_every_check(self):
        first = history.History(self.path, clock=self.clock).open()
        first.record({'a': 'ok'})
        first.close()
        second = history.History(self.path, clock=self.clock).open()
        self.assertEqual(len(second.record({'a': 'ok'})), 1)

    def test_unwritable_path_keeps_working_in_memory(self):
        self.path.parent.mkdir(parents=True)
        blocker = self.path.parent / 'file'
        blocker.write_text('x', encoding='utf-8')
        log = history.History(blocker / 'history.jsonl', clock=self.clock).open()
        log.record({'a': 'fail'})
        self.assertFalse(log.writable)
        self.assertEqual(log.snapshot()[-1]['s'], 'fail')

    def test_history_lives_next_to_the_config(self):
        self.assertEqual(history.history_path(Path(self.tmp.name) / 'monitor.json').name, 'history.jsonl')
        self.assertEqual(history.history_path(Path(self.tmp.name) / 'monitor.json').parent,
                         Path(self.tmp.name).resolve())


def rec(t, check=None, state=None, event=None):
    return {'t': t, 'e': event} if event else {'t': t, 'id': check, 's': state}


class Timeline(unittest.TestCase):
    def test_states_become_segments_until_now(self):
        records = [rec(100, event='start'), rec(100, 'a', 'ok'), rec(200, 'a', 'fail'), rec(260, 'a', 'ok')]
        self.assertEqual(history.timeline(records, 400, 1000, ['a'])['a'], [
            {'s': 100, 'e': 200, 'state': 'ok'}, {'s': 200, 'e': 260, 'state': 'fail'},
            {'s': 260, 'e': 400, 'state': 'ok'}])

    def test_stopped_and_crashed_sessions_leave_gaps(self):
        records = [rec(0, event='start'), rec(0, 'a', 'ok'), rec(50, event='stop'),
                   rec(100, event='start'), rec(100, 'a', 'degraded'), rec(130, event='beat'),
                   rec(300, event='start'), rec(300, 'a', 'ok')]
        self.assertEqual(history.timeline(records, 400, 1000, ['a'])['a'], [
            {'s': 0, 'e': 50, 'state': 'ok'}, {'s': 100, 'e': 130, 'state': 'degraded'},
            {'s': 300, 'e': 400, 'state': 'ok'}])

    def test_window_clips_and_not_live_ends_at_last_record(self):
        records = [rec(0, event='start'), rec(0, 'a', 'fail'), rec(900, event='beat')]
        self.assertEqual(history.timeline(records, 1000, 500, ['a'])['a'], [{'s': 500, 'e': 1000, 'state': 'fail'}])
        self.assertEqual(history.timeline(records, 1000, 500, ['a'], live=False)['a'],
                         [{'s': 500, 'e': 900, 'state': 'fail'}])

    def test_records_outside_a_session_and_unknown_ids_are_ignored(self):
        records = [rec(10, 'a', 'fail'), rec(20, event='start'), rec(20, 'zz', 'fail'), rec(20, 'a', 'ok')]
        segments = history.timeline(records, 30, 100, ['a'])
        self.assertEqual(segments, {'a': [{'s': 20, 'e': 30, 'state': 'ok'}]})

    def test_last_change(self):
        records = [rec(1, 'a', 'ok'), rec(5, 'a', 'fail'), rec(9, 'b', 'ok'), rec(20, 'a', 'fail')]
        self.assertEqual(history.last_change(records, 'a'), 5)
        self.assertIsNone(history.last_change(records, 'b'))


class Guide(unittest.TestCase):
    def test_every_check_is_described(self):
        self.assertEqual(set(guide.CHECKS), set(engine.CHECK_IDS))
        self.assertEqual(set(guide.PRIMARY), set(engine.CHECK_IDS))

    def test_every_failure_code_the_engine_emits_has_steps(self):
        source = (ROOT / 'skills/claude-guardian/scripts/monitor.py').read_text(encoding='utf-8')
        import re
        emitted = set(re.findall(r"add\('\w+', '(?:fail|degraded)', '([A-Z0-9_]+)'", source))
        self.assertGreaterEqual(len(emitted), 12)
        self.assertLessEqual(emitted, set(guide.STEPS))

    def test_ok_has_no_steps_and_unknown_codes_fall_back(self):
        self.assertEqual(guide.guide('proxy_core', 'ok', 'PROXY_CORE_RUNNING')['steps'], [])
        self.assertEqual(guide.guide('proxy_core', 'unknown', 'NEW_CODE')['steps'], guide.UNKNOWN_STEPS)
        self.assertEqual(guide.guide('firewall_block', 'fail', 'NEW_CODE')['steps'],
                         guide.STEPS['DEFAULT_OUTBOUND_ALLOW'])

    def test_steps_are_actions_not_disclaimers(self):
        for code, steps in guide.STEPS.items():
            for step in steps:
                self.assertNotIn('·', step, code)
                self.assertLessEqual(len(step), 90, code)


if __name__ == '__main__':
    unittest.main()
