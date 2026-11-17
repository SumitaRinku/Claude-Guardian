'use strict';
// Pure logic checks for the WebView desktop panel; no browser and no DOM.
const assert = require('node:assert/strict');
const panel = require('../skills/claude-guardian/assets/monitor/panel.js');

assert.equal(panel.stateClass('fail'), 'fail');
assert.equal(panel.stateClass('weird'), 'unknown');
assert.equal(panel.stateClass(undefined), 'unknown');

const empty = panel.subtitleText({checked_at: 0, target: 'demo', rows: []});
assert.equal(empty, '上次采集 — · 目标 demo');
const full = panel.subtitleText({checked_at: 1700000000, ago: '刚刚', target: 'demo',
  rows: [{}], counts: {ok: 7, degraded: 1, fail: 1, unknown: 1}});
assert.match(full, /（刚刚） · 目标 demo · 正常 7 \/ 降级 1 \/ 失效 1 \/ 未知 1$/);

const rows = [{text: 'a'}, {text: 'b'}];
assert.deepEqual(panel.mergeLog(rows, {rebuild: false, rows: [{text: 'c'}]}, 10).map(r => r.text), ['a', 'b', 'c']);
assert.deepEqual(panel.mergeLog(rows, {rebuild: true, rows: [{text: 'z'}]}, 10).map(r => r.text), ['z']);
assert.deepEqual(panel.mergeLog(rows, {rebuild: false, rows: [{text: 'c'}]}, 2).map(r => r.text), ['b', 'c']);
assert.equal(rows.length, 2, 'mergeLog must not mutate its input');

assert.equal(panel.logLine({time: '12:00:00', kind: '状态', text: 'x'}), '12:00:00  [状态]  x');
assert.deepEqual(Array.from(panel.base64ToBytes(Buffer.from([0, 1, 254, 255]).toString('base64'))), [0, 1, 254, 255]);
assert.equal(panel.LOG_LIMIT, 300);

console.log('monitor-panel: ok');
