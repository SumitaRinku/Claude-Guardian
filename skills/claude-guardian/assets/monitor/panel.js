'use strict';
// Desktop panel (pywebview). All data comes from window.pywebview.api; no network requests.

const LOG_LIMIT = 300;
const STATES = ['ok', 'degraded', 'fail', 'unknown'];
const STATE_TEXT = { ok: '正常', degraded: '降级', fail: '失效', unknown: '未知' };
const PAGES = ['status', 'history', 'log', 'settings'];
const DESIGN_WIDTH = 900;

function stateClass(value) {
  return STATES.includes(value) ? value : 'unknown';
}

function pad(value) {
  return String(value).padStart(2, '0');
}

function clock(epoch, withDate) {
  const d = new Date(epoch * 1000);
  const time = pad(d.getHours()) + ':' + pad(d.getMinutes());
  return withDate ? (d.getMonth() + 1) + '/' + d.getDate() + ' ' + time : time;
}

function subtitleText(snap) {
  if (!snap.checked_at) return '正在读取…';
  const d = new Date(snap.checked_at * 1000);
  return '上次采集 ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
}

// Segments [{s, e, state}] -> positioned blocks in percent of the window ending at `now`.
function barBlocks(segments, now, window) {
  const begin = now - window;
  const multiDay = window > 86400;
  return (segments || []).map(seg => {
    const s = Math.max(seg.s, begin);
    const e = Math.min(seg.e, now);
    return {
      left: (s - begin) / window * 100,
      width: Math.max(0, e - s) / window * 100,
      state: stateClass(seg.state),
      title: clock(s, multiDay) + '–' + clock(e, multiDay) + ' ' + (STATE_TEXT[seg.state] || seg.state)
    };
  }).filter(block => block.width > 0);
}

// Text with `code` spans -> [{code: bool, text}].
function codeParts(text) {
  return String(text).split('`').map((part, index) => ({ code: index % 2 === 1, text: part })).filter(p => p.text);
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
  let toastTimer = 0;
  let lastOverall = '';
  let historyWindow = 86400;
  let historyTimer = 0;
  let openCheck = null;
  let openKey = '';
  let fitted = false;

  function toast(text) {
    const node = $('toast');
    node.textContent = text;
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.hidden = true; }, 3500);
  }

  function select(page) {
    if (!PAGES.includes(page)) return;
    active = page;
    for (const button of document.querySelectorAll('.nav')) button.classList.toggle('active', button.dataset.page === page);
    for (const section of document.querySelectorAll('.page')) section.classList.toggle('active', section.id === 'page-' + page);
    if (page !== 'status') closeDrawer();
    clearInterval(historyTimer);
    if (page === 'history') {
      loadHistory();
      historyTimer = setInterval(loadHistory, 30000);
    }
    if (page === 'settings') loadSettings();
    if (page === 'log') scrollLog();
  }

  function fillBar(node, segments, now, window) {
    node.textContent = '';
    for (const block of barBlocks(segments, now, window)) {
      const piece = document.createElement('i');
      piece.className = block.state;
      piece.style.left = block.left + '%';
      piece.style.width = block.width + '%';
      piece.title = block.title;
      node.append(piece);
    }
  }

  function fillCode(node, text) {
    for (const part of codeParts(text)) {
      if (part.code) {
        const code = document.createElement('code');
        code.textContent = part.text;
        node.append(code);
      } else {
        node.append(part.text);
      }
    }
  }

  function card(row) {
    let node = cards[row.id];
    if (!node) {
      node = document.createElement('button');
      node.type = 'button';
      node.innerHTML = '<h3></h3><span class="chip"></span>';
      node.querySelector('h3').textContent = row.label;
      node.onclick = () => (openCheck === row.id ? closeDrawer() : openDrawer(row.id));
      $('cards').append(node);
      cards[row.id] = node;
    }
    const cls = stateClass(row.state);
    node.className = 'card ' + cls + (openCheck === row.id ? ' selected' : '');
    const chip = node.querySelector('.chip');
    chip.className = 'chip ' + cls;
    chip.textContent = row.state_text;
  }

  async function openDrawer(checkId) {
    const detail = await api().detail(checkId);
    if (!detail) return;
    openCheck = checkId;
    openKey = detail.state + detail.code;
    $('drawer-title').textContent = detail.label;
    $('drawer-chip').className = 'chip ' + stateClass(detail.state);
    $('drawer-chip').textContent = detail.state_text;
    $('drawer-checks').textContent = detail.checks;
    const steps = $('drawer-steps');
    steps.textContent = '';
    for (const step of detail.steps) {
      const item = document.createElement('li');
      fillCode(item, step);
      steps.append(item);
    }
    steps.hidden = !detail.steps.length;
    fillBar($('drawer-bar'), detail.segments, detail.now, detail.window);
    $('drawer-changed').textContent = detail.changed_at ? '最近变化 ' + clock(detail.changed_at, true) : '';
    $('drawer-code').textContent = detail.code;
    $('drawer').hidden = false;
    for (const [id, node] of Object.entries(cards)) node.classList.toggle('selected', id === checkId);
  }

  function closeDrawer() {
    openCheck = null;
    $('drawer').hidden = true;
    for (const node of Object.values(cards)) node.classList.remove('selected');
  }

  async function loadHistory() {
    const data = await api().timeline(historyWindow);
    const box = $('history');
    box.textContent = '';
    for (const row of data.rows) {
      const line = document.createElement('div');
      line.className = 'history-row';
      const label = document.createElement('span');
      label.textContent = row.label;
      const bar = document.createElement('div');
      bar.className = 'bar';
      fillBar(bar, row.segments, data.now, data.window);
      line.append(label, bar);
      box.append(line);
    }
    const axis = document.createElement('div');
    axis.className = 'axis';
    axis.innerHTML = '<span></span><div><span></span><span>现在</span></div>';
    axis.querySelector('div span').textContent = data.window > 86400 ? '7 天前' : '24 小时前';
    box.append(axis);
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
      kind.textContent = row.kind;
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
    $('subtitle').textContent = subtitleText(snap);
    $('banner').className = 'banner ' + cls;
    $('headline').textContent = snap.headline;
    $('detail').textContent = snap.detail;
    $('detail').title = snap.detail;
    const badge = $('badge');
    badge.hidden = !snap.problems;
    badge.textContent = snap.problems || '';
    badge.className = 'badge ' + stateClass(snap.worst);
    if (lastOverall !== cls) {
      $('logo').src = 'logo-' + cls + '.png';
      lastOverall = cls;
    }
    for (const row of snap.rows) {
      card(row);
      if (row.id === openCheck && row.state + row.code !== openKey) openDrawer(row.id);
    }
    renderLog(snap.log);
    logTotal = snap.log.total;
    if (snap.notice) toast(snap.notice);
    if (!fitted && snap.rows.length) {
      fitted = true;
      requestAnimationFrame(fitWindow);
    }
  }

  // Size the window to the status page's natural content, once, after the cards exist.
  async function fitWindow() {
    try { await document.fonts.ready; } catch (_) { /* 字体未就绪不影响尺寸计算 */ }
    const page = $('page-status');
    const style = getComputedStyle(page);
    const main = $('page-status').closest('main');
    const top = main.querySelector('.top');
    const mainHeight = top.offsetHeight + page.querySelector('.inner').offsetHeight +
      parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
    const side = document.querySelector('.sidebar');
    const sideHeight = Array.from(side.children).reduce((sum, child) => sum + child.offsetHeight, 0) + 120;
    // +2: sub-pixel rounding would otherwise leave a 1px scroll range.
    await api().fit(DESIGN_WIDTH, Math.ceil(Math.max(mainHeight, sideHeight)) + 2, window.innerWidth, window.innerHeight);
  }

  async function poll() {
    try {
      render(await api().snapshot(logTotal));
    } catch (error) {
      toast('读取状态失败：' + error);
    }
    setTimeout(poll, 1000);
  }

  async function loadSettings() {
    const s = await api().settings();
    $('interval').value = s.interval;
    $('cooldown').value = s.cooldown;
    for (const box of document.querySelectorAll('input[name=notify]')) box.checked = !!s.notify[box.value];
    $('paused').checked = s.paused;
  }

  function form() {
    const notify = {};
    for (const box of document.querySelectorAll('input[name=notify]')) notify[box.value] = box.checked;
    return { interval: $('interval').value, cooldown: $('cooldown').value, notify, paused: $('paused').checked };
  }

  async function act(promise) {
    const result = await promise;
    if (result && result.message) toast(result.message);
    return result;
  }

  async function askClose() {
    const choices = await api().close_choices();
    const canHide = choices.includes('hide');
    const dialog = $('close-dialog');
    $('close-question').textContent = canHide ? '隐藏到托盘继续监测，还是退出？' : '退出后监测会停止。';
    dialog.querySelector('[value=hide]').hidden = !canHide;
    dialog.querySelector('[value=exit]').className = canHide ? 'btn' : 'btn primary';
    if (!dialog.open) dialog.showModal();
  }

  for (const button of document.querySelectorAll('.nav')) button.onclick = () => select(button.dataset.page);
  for (const button of document.querySelectorAll('.seg')) {
    button.onclick = () => {
      historyWindow = Number(button.dataset.window);
      for (const other of document.querySelectorAll('.seg')) other.classList.toggle('active', other === button);
      loadHistory();
    };
  }
  $('refresh').onclick = () => act(api().refresh());
  $('drawer-close').onclick = closeDrawer;
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
    toast(done ? '已复制' : '复制失败');
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
    if (event.key === 'Escape' && openCheck) closeDrawer();
    if (event.ctrlKey && ['1', '2', '3', '4'].includes(event.key)) {
      event.preventDefault();
      select(PAGES[Number(event.key) - 1]);
    }
  });
  document.addEventListener('contextmenu', event => {
    if (!event.target.closest('.log, .drawer, input')) event.preventDefault();
  });

  window.CCGuard = { askClose, select, openDrawer, closeDrawer };

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
  module.exports = { stateClass, subtitleText, barBlocks, codeParts, clock, mergeLog, logLine, base64ToBytes, LOG_LIMIT };
} else if (typeof window !== 'undefined') {
  if (window.pywebview && window.pywebview.api) bind();
  else window.addEventListener('pywebviewready', bind, { once: true });
}
