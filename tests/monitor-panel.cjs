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

assert.deepEqual(panel.scoreView(null), {cls: 'unknown', value: '—', label: '未检测', ip: '', facts: null});
assert.equal(panel.scoreView({ok: false}).label, '检测失败');
const sv = panel.scoreView({ok: true, score: 88, label: '纯净', level: 'ok', ip: '203.0.*.*', ipv6: true,
  facts: {location: 'Japan', network: 'AS1 X', kind: '住宅', timezone: 'Asia/Tokyo', flags: ['VPN', 'Tor']}});
assert.equal(sv.value, '88');
assert.equal(sv.ip, '出口 203.0.*.*（IPv6）');
assert.equal(sv.facts.flags, 'VPN、Tor');
assert.equal(panel.scoreView({ok: true, score: 1, label: 'x', level: 'weird', ip: '', facts: {flags: []}}).facts.flags, '无');

assert.equal(panel.updateView(null).download, null);
assert.match(panel.updateView({ok: false, error: 'offline'}).text, /检查失败：offline/);
assert.deepEqual(panel.updateView({ok: true, update: false}), {text: '已是最新版本', download: null});
const uv = panel.updateView({ok: true, update: true, releases: [{version: '0.7.0', date: '2026-12-01',
  installer_url: 'https://github.com/SumitaRinku/CCguard/releases/download/v0.7.0/CCGuard-Setup-0.7.0.exe',
  page_url: 'https://github.com/SumitaRinku/CCguard/releases/tag/v0.7.0'}]});
assert.equal(uv.text, '有新版本 0.7.0（2026-12-01 发布）');
assert.match(uv.download, /CCGuard-Setup-0\.7\.0\.exe$/);
assert.match(panel.updateView({ok: true, update: true, releases: [{version: '0.7.0', date: '', installer_url: null,
  page_url: 'https://github.com/SumitaRinku/CCguard/releases/tag/v0.7.0'}]}).download, /tag\/v0\.7\.0$/);

assert.equal(panel.logLine({time: '12:00:00', kind: '状态', text: 'x'}), '12:00:00  [状态]  x');
assert.deepEqual(Array.from(panel.base64ToBytes(Buffer.from([0, 1, 254, 255]).toString('base64'))), [0, 1, 254, 255]);
assert.equal(panel.LOG_LIMIT, 300);

console.log('monitor-panel: ok');
