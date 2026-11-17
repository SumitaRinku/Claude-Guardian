'use strict';
// Pure logic checks for the WebView desktop panel; no browser and no DOM.
const assert = require('node:assert/strict');
const panel = require('../skills/claude-guardian/assets/monitor/panel.js');

assert.equal(panel.stateClass('fail'), 'fail');
assert.equal(panel.stateClass('weird'), 'unknown');
assert.equal(panel.stateClass(undefined), 'unknown');

assert.equal(panel.subtitleText({checked_at: 0}), '正在读取…');
assert.match(panel.subtitleText({checked_at: 1700000000}), /^上次采集 \d\d:\d\d:\d\d$/);

const blocks = panel.barBlocks([{s: 0, e: 50, state: 'ok'}, {s: 50, e: 60, state: 'fail'},
  {s: 80, e: 80, state: 'ok'}, {s: -50, e: 10, state: 'weird'}], 100, 100);
assert.deepEqual(blocks.map(b => [b.left, b.width, b.state]), [[0, 50, 'ok'], [50, 10, 'fail'], [0, 10, 'unknown']]);
assert.match(blocks[1].title, /失效$/);
assert.match(panel.barBlocks([{s: 0, e: 3600, state: 'ok'}], 604800, 604800)[0].title, /^\d+\/\d+ /);

assert.deepEqual(panel.codeParts('改配置里的 `a.b`。'), [
  {code: false, text: '改配置里的 '}, {code: true, text: 'a.b'}, {code: false, text: '。'}]);
assert.deepEqual(panel.codeParts('no code'), [{code: false, text: 'no code'}]);

const rows = [{text: 'a'}, {text: 'b'}];
assert.deepEqual(panel.mergeLog(rows, {rebuild: false, rows: [{text: 'c'}]}, 10).map(r => r.text), ['a', 'b', 'c']);
assert.deepEqual(panel.mergeLog(rows, {rebuild: true, rows: [{text: 'z'}]}, 10).map(r => r.text), ['z']);
assert.deepEqual(panel.mergeLog(rows, {rebuild: false, rows: [{text: 'c'}]}, 2).map(r => r.text), ['b', 'c']);
assert.equal(rows.length, 2, 'mergeLog must not mutate its input');

assert.equal(panel.logLine({time: '12:00:00', kind: '状态', text: 'x'}), '12:00:00  [状态]  x');
assert.deepEqual(Array.from(panel.base64ToBytes(Buffer.from([0, 1, 254, 255]).toString('base64'))), [0, 1, 254, 255]);
assert.equal(panel.LOG_LIMIT, 300);

console.log('monitor-panel: ok');
