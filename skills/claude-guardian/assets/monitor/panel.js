'use strict';
// Desktop panel (pywebview). All data comes from window.pywebview.api; no network requests.

const LOG_LIMIT = 300;
const IDLE_STATUS = '只读监测 · 不联网 · 不改系统';
const STATES = ['ok', 'degraded', 'fail', 'unknown'];

function stateClass(value) {
  return STATES.includes(value) ? value : 'unknown';
}

function subtitleText(snap) {
  let text = '上次采集 ' + (snap.checked_at
    ? new Date(snap.checked_at * 1000).toLocaleTimeString('zh-CN', { hour12: false }) + '（' + snap.ago + '）'
    : '—');
  text += ' · 目标 ' + (snap.target || '—');
  if (snap.rows && snap.rows.length) {
    const c = snap.counts || {};
    text += ' · 正常 ' + (c.ok || 0) + ' / 降级 ' + (c.degraded || 0) + ' / 失效 ' + (c.fail || 0) + ' / 未知 ' + (c.unknown || 0);
  }
  return text;
}

function mergeLog(rows, delta, limit) {
  const merged = delta.rebuild ? delta.rows.slice() : rows.concat(delta.rows);
  return merged.length > limit ? merged.slice(merged.length - limit) : merged;
}

function logLine(row) {
  return row.time + '  [' + row.kind + ']  ' + row.text;
}

function base64ToBytes(text) {
  const raw = atob(text);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

function bind() {
  const $ = id => document.getElementById(id);
  const api = () => window.pywebview.api;
  const cards = {};
  let logRows = [];
  let logTotal = 0;
  let active = 'status';
  let statusTimer = 0;
  let last = '';

  function status(text) {
    const node = $('status');
    node.textContent = text;
    node.classList.add('flash');
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => { node.textContent = IDLE_STATUS; node.classList.remove('flash'); }, 6000);
  }

  function select(page) {
    active = page;
    for (const button of document.querySelectorAll('.nav')) button.classList.toggle('active', button.dataset.page === page);
    for (const section of document.querySelectorAll('.page')) section.classList.toggle('active', section.id === 'page-' + page);
    if (page === 'settings') loadSettings();
    if (page === 'log') scrollLog();
  }

  function card(row) {
    let node = cards[row.id];
    if (!node) {
      node = document.createElement('article');
      node.innerHTML = '<div class="card-head"><h3></h3><span class="chip"></span></div><p></p><div class="code"></div>';
      node.querySelector('h3').textContent = row.label;
      node.querySelector('p').textContent = row.description || '';
      $('cards').append(node);
      cards[row.id] = node;
    }
    const cls = stateClass(row.state);
    node.className = 'card ' + cls;
    const chip = node.querySelector('.chip');
    chip.className = 'chip ' + cls;
    chip.textContent = row.state_text;
    node.querySelector('.code').textContent = row.code;
  }

  function renderLog(delta) {
    if (!delta.rebuild && !delta.rows.length) return;
    logRows = mergeLog(logRows, delta, LOG_LIMIT);
    const box = $('log');
    const stick = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    if (delta.rebuild) box.textContent = '';
    for (const row of delta.rows) {
      const line = document.createElement('div');
      line.className = 'log-row ' + (row.level || 'info');
      const time = document.createElement('time');
      time.textContent = row.time;
      const kind = document.createElement('span');
      kind.className = 'kind';
      kind.textContent = '[' + row.kind + ']';
      const text = document.createElement('span');
      text.className = 'text';
      text.textContent = row.text;
      line.append(time, kind, text);
      box.append(line);
    }
    while (box.children.length > LOG_LIMIT) box.firstChild.remove();
    if (stick) scrollLog();
  }

  function scrollLog() {
    const box = $('log');
    box.scrollTop = box.scrollHeight;
  }

  function render(snap) {
    const cls = stateClass(snap.overall);
    $('pill').className = 'pill ' + cls;
    $('pill').textContent = snap.overall_text;
    $('subtitle').textContent = subtitleText(snap);
    $('banner').className = 'banner ' + (snap.checked_at ? cls : 'unknown');
    $('headline').textContent = snap.headline;
    $('detail').textContent = snap.detail;
    const badge = $('badge');
    badge.hidden = !snap.problems;
    badge.textContent = snap.problems || '';
    badge.className = 'badge ' + stateClass(snap.worst);
    if (last !== cls) {
      $('logo').src = 'logo-' + cls + '.png';
      document.title = 'CCGuard · ' + snap.overall_text;
      last = cls;
    }
    for (const row of snap.rows) card(row);
    renderLog(snap.log);
    logTotal = snap.log.total;
    if (snap.notice) status(snap.notice);
  }

  async function poll() {
    try {
      render(await api().snapshot(logTotal));
    } catch (error) {
      status('读取状态失败：' + error);
    }
    setTimeout(poll, 1000);
  }

  async function loadSettings() {
    const s = await api().settings();
    $('interval').value = s.interval;
    $('cooldown').value = s.cooldown;
    for (const box of document.querySelectorAll('input[name=notify]')) box.checked = !!s.notify[box.value];
    $('paused').checked = s.paused;
    $('config-path').textContent = '配置文件：' + s.config_path;
  }

  function form() {
    const notify = {};
    for (const box of document.querySelectorAll('input[name=notify]')) notify[box.value] = box.checked;
    return { interval: $('interval').value, cooldown: $('cooldown').value, notify, paused: $('paused').checked };
  }

  async function act(promise) {
    const result = await promise;
    if (result && result.message) status(result.message);
    return result;
  }

  async function askClose() {
    const choices = await api().close_choices();
    const canHide = choices.includes('hide');
    const dialog = $('close-dialog');
    $('close-question').textContent = canHide ? '要隐藏到托盘继续监测，还是直接关闭？' : '关闭后监测会停止。确定关闭吗？';
    $('close-detail').textContent = canHide
      ? '隐藏后托盘盾牌图标继续按状态变色并提醒；直接关闭会停止监测。'
      : '本次未启动托盘，窗口隐藏后将无法找回；需要后台提醒请用 --tray 启动。';
    dialog.querySelector('[value=hide]').hidden = !canHide;
    dialog.querySelector('[value=exit]').className = canHide ? 'btn' : 'btn primary';
    if (!dialog.open) dialog.showModal();
  }

  for (const button of document.querySelectorAll('.nav')) button.onclick = () => select(button.dataset.page);
  $('refresh').onclick = () => act(api().refresh());
  $('settings').onsubmit = event => { event.preventDefault(); act(api().apply(form(), false)); };
  $('save').onclick = () => act(api().apply(form(), true));
  $('open-config').onclick = () => act(api().open_config());
  $('copy-log').onclick = async () => {
    const text = await api().log_text();
    const area = document.createElement('textarea');
    area.value = text;
    document.body.append(area);
    area.select();
    const done = document.execCommand('copy');
    area.remove();
    status(done ? '已复制 ' + logRows.length + ' 条日志到剪贴板' : '复制失败');
  };
  $('clear-log').onclick = async () => {
    const result = await act(api().clear_log());
    logRows = [];
    logTotal = result.total;
    $('log').textContent = '';
  };
  $('autostart').onchange = async event => {
    const result = await act(api().set_autostart(event.target.checked));
    event.target.checked = result.enabled;
  };
  for (const button of $('close-dialog').querySelectorAll('button')) {
    button.onclick = () => {
      $('close-dialog').close();
      if (button.value !== 'cancel') api().close(button.value);
    };
  }
  document.addEventListener('keydown', event => {
    if (event.key === 'F5') { event.preventDefault(); act(api().refresh()); }
    if (event.ctrlKey && ['1', '2', '3'].includes(event.key)) {
      event.preventDefault();
      select(['status', 'log', 'settings'][Number(event.key) - 1]);
    }
  });
  document.addEventListener('contextmenu', event => {
    if (!event.target.closest('.log, .code, .path, input')) event.preventDefault();
  });

  window.CCGuard = { askClose, select };

  (async () => {
    try {
      for (const font of await api().fonts()) {
        const face = new FontFace(font.family, base64ToBytes(font.data));
        document.fonts.add(await face.load());
      }
    } catch (_) { /* 字体加载失败不影响面板 */ }
  })();
  api().autostart_status().then(result => { $('autostart').checked = result.enabled; });
  poll();
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { stateClass, subtitleText, mergeLog, logLine, base64ToBytes, LOG_LIMIT };
} else if (typeof window !== 'undefined') {
  if (window.pywebview && window.pywebview.api) bind();
  else window.addEventListener('pywebviewready', bind, { once: true });
}
