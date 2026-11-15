'use strict';

const LABELS = {
  proxy_core: '代理核心',
  tun_adapter: 'TUN 网卡',
  default_route: '默认路由',
  firewall_block: '防火墙默认阻止',
  guardian_rules: '放行规则',
  core_ipv6: '核心 IPv6',
  strict_route: '严格路由',
  dns_hijack: 'DNS 接管',
  dns_servers: '网卡 DNS',
  os_ipv6: '系统 IPv6'
};
const OVERALL = {
  ok: ['防护正常', '所有检查项通过。', 'ok'],
  degraded: ['有降级项', '防护仍生效，但有配置项与预期不一致。', 'warn'],
  fail: ['防护已失效', '关键检查项未通过，流量可能不再受保护。', 'fail'],
  unknown: ['状态未知', '部分检查无法读取，先核实，不要据此放行。', 'unknown']
};
const STATE_TEXT = { ok: '正常', degraded: '降级', fail: '失效', unknown: '未知' };

function labelOf(id) {
  return LABELS[id] || id;
}

function decideAlerts(prev, next, cooldownMs, now, lastSent) {
  const events = [];
  if (!prev) return events;
  for (const id of Object.keys(next)) {
    const before = prev[id];
    const after = next[id];
    if (!before || before === after) continue;
    const sent = lastSent[id] || 0;
    if (after === 'fail' || after === 'degraded') {
      if (now - sent < cooldownMs) continue;
      events.push({id, state: after, kind: 'problem'});
    } else if (after === 'ok' && before !== 'ok') {
      events.push({id, state: 'ok', kind: 'recovered'});
    }
  }
  return events;
}

function alertText(event) {
  const label = labelOf(event.id);
  return event.kind === 'recovered'
    ? '已恢复：' + label + ' 回到正常'
    : '防护告警：' + label + ' ' + (STATE_TEXT[event.state] || event.state);
}

function statesOf(state) {
  const result = {};
  for (const check of (state && state.checks) || []) result[check.id] = check.state;
  return result;
}

function overallView(state) {
  return OVERALL[(state && state.overall) || 'unknown'] || OVERALL.unknown;
}

function bind() {
  const $ = id => document.getElementById(id);
  let previous = null;
  let lastSent = {};
  let cooldown = 120000;

  $('notify').onclick = async () => {
    if (typeof Notification === 'undefined') return;
    const result = await Notification.requestPermission();
    $('notify').textContent = result === 'granted' ? '通知已开启' : '通知未授权';
    $('notify').disabled = result !== 'granted';
  };
  if (typeof Notification === 'undefined') {
    $('notify').disabled = true;
    $('notify').textContent = '浏览器不支持通知';
  } else if (Notification.permission === 'granted') {
    $('notify').textContent = '通知已开启';
    $('notify').disabled = true;
  }

  function fire(events) {
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
    for (const event of events) {
      try {
        new Notification('Claude-Guardian', { body: alertText(event), tag: 'guardian-' + event.id, silent: false });
      } catch (_) { /* 通知失败不影响监测 */ }
    }
  }

  function render(state) {
    const [title, summary, cls] = overallView(state);
    $('overall').textContent = title;
    $('overall').className = cls;
    $('summary').textContent = summary;
    $('checked').textContent = state.checked_at
      ? '上次读取：' + new Date(state.checked_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      : '尚未读取';
    document.title = 'CCGuard · ' + title;

    const box = $('checks');
    for (const check of state.checks || []) {
      let card = document.getElementById('card-' + check.id);
      if (!card) {
        card = document.createElement('article');
        card.className = 'card';
        card.id = 'card-' + check.id;
        const heading = document.createElement('h2');
        heading.textContent = labelOf(check.id);
        const badge = document.createElement('span');
        badge.className = 'badge';
        const detail = document.createElement('p');
        card.append(heading, badge, detail);
        box.append(card);
      }
      card.className = 'card ' + check.state;
      const badge = card.querySelector('.badge');
      badge.className = 'badge ' + check.state;
      badge.textContent = STATE_TEXT[check.state] || check.state;
      card.querySelector('p').textContent = check.code || '—';
    }
  }

  async function poll() {
    try {
      const response = await fetch('state', { cache: 'no-store' });
      if (!response.ok) throw new Error('state');
      const state = await response.json();
      if (state.cooldown_seconds) cooldown = state.cooldown_seconds * 1000;
      const next = statesOf(state);
      const events = decideAlerts(previous, next, cooldown, Date.now(), lastSent);
      for (const event of events) if (event.kind === 'problem') lastSent[event.id] = Date.now();
      fire(events);
      previous = next;
      render(state);
    } catch (_) {
      $('overall').textContent = '界面连接已结束';
      $('overall').className = 'unknown';
      $('summary').textContent = '防护保持原状态，重新打开监测入口即可。';
      return;
    }
    setTimeout(poll, 1000);
  }

  poll();
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { decideAlerts, alertText, statesOf, overallView, labelOf, LABELS, OVERALL };
} else if (typeof document !== 'undefined') {
  bind();
}
