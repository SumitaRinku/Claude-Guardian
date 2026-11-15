'use strict';
// Pure logic checks for the monitor page; no browser and no DOM.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const mon = require('../skills/claude-guardian/assets/monitor/monitor.js');

assert.deepEqual(mon.decideAlerts(null, {proxy_core: 'fail'}, 0, 1000, {}), []);
assert.deepEqual(mon.decideAlerts({proxy_core: 'ok'}, {proxy_core: 'ok'}, 0, 1000, {}), []);
assert.deepEqual(mon.decideAlerts({proxy_core: 'ok'}, {proxy_core: 'fail'}, 1000, 5000, {}),
  [{id: 'proxy_core', state: 'fail', kind: 'problem'}]);
assert.deepEqual(mon.decideAlerts({proxy_core: 'ok'}, {proxy_core: 'degraded'}, 1000, 5000, {}),
  [{id: 'proxy_core', state: 'degraded', kind: 'problem'}]);
assert.deepEqual(mon.decideAlerts({proxy_core: 'ok'}, {proxy_core: 'fail'}, 1000, 5000, {proxy_core: 4500}), []);
assert.deepEqual(mon.decideAlerts({proxy_core: 'ok'}, {proxy_core: 'fail'}, 1000, 6000, {proxy_core: 4500}),
  [{id: 'proxy_core', state: 'fail', kind: 'problem'}]);
assert.deepEqual(mon.decideAlerts({proxy_core: 'fail'}, {proxy_core: 'ok'}, 0, 1000, {}),
  [{id: 'proxy_core', state: 'ok', kind: 'recovered'}]);
assert.deepEqual(mon.decideAlerts({tun_adapter: 'unknown'}, {tun_adapter: 'ok'}, 0, 1000, {}),
  [{id: 'tun_adapter', state: 'ok', kind: 'recovered'}]);
assert.deepEqual(mon.decideAlerts({tun_adapter: 'ok'}, {tun_adapter: 'unknown'}, 0, 1000, {}), []);

assert.deepEqual(mon.statesOf({checks: [{id: 'a', state: 'ok'}, {id: 'b', state: 'fail'}]}), {a: 'ok', b: 'fail'});
assert.deepEqual(mon.statesOf(null), {});
assert.equal(mon.overallView({overall: 'fail'})[0], '防护已失效');
assert.equal(mon.overallView({overall: 'ok'})[2], 'ok');
assert.equal(mon.overallView({})[2], 'unknown');
assert.equal(mon.labelOf('strict_route'), '严格路由');
assert.equal(mon.labelOf('unknown_id'), 'unknown_id');
assert.match(mon.alertText({id: 'strict_route', state: 'degraded', kind: 'problem'}), /严格路由/);
assert.match(mon.alertText({id: 'strict_route', state: 'ok', kind: 'recovered'}), /已恢复/);

const assets = path.join(__dirname, '../skills/claude-guardian/assets/monitor');
const html = fs.readFileSync(path.join(assets, 'monitor.html'), 'utf8');
const css = fs.readFileSync(path.join(assets, 'monitor.css'), 'utf8');
const js = fs.readFileSync(path.join(assets, 'monitor.js'), 'utf8');
for (const text of [html, css]) {
  assert.ok(!/https?:\/\//.test(text), 'assets must not reference external origins');
  assert.ok(!/<script(?![^>]*src=)/i.test(text), 'html must not use inline scripts');
  assert.ok(!/\son[a-z]+\s*=/i.test(text), 'html must not use inline handlers');
}
assert.ok(html.includes('src="monitor.js"'));
assert.ok(!/document\.cookie|localStorage|sessionStorage|indexedDB/.test(js));
assert.ok(js.includes("fetch('state'"));
console.log('Monitor interaction logic checks passed; no browser executed');
