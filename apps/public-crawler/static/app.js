const $ = (selector) => document.querySelector(selector);
const api = async (path, options = {}) => {
  const response = await fetch(path, { cache: 'no-store', ...options });
  const type = response.headers.get('content-type') || '';
  const body = type.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(body?.error || `请求失败（${response.status}）`);
  return body;
};

let latestResults = [];
let lastEventsKey = '';

function safeText(value) {
  return String(value ?? '');
}

function statusLabel(status) {
  return ({ idle: '待开始', running: '采集中', completed: '已完成', stopped: '已停止', failed: '异常停止' })[status] || '待开始';
}

function renderStatus(data) {
  $('#metricSeen').textContent = data.pages_seen ?? 0;
  $('#metricOk').textContent = data.pages_ok ?? 0;
  $('#metricFound').textContent = data.discovered ?? 0;
  const status = $('#runStatus');
  status.textContent = statusLabel(data.status);
  status.className = `status-pill ${safeText(data.status)}`;
  $('#startButton').disabled = Boolean(data.running);
  $('#stopButton').disabled = !data.running;
  $('#liveDot').classList.toggle('paused', !data.running);
  const max = Number(data.max_pages || 0);
  const seen = Number(data.pages_seen || 0);
  $('#progressBar').style.width = data.running && max ? `${Math.min(100, (seen / max) * 100)}%` : (data.status === 'completed' ? '100%' : '0%');
  if (data.started_at) {
    const date = new Date(data.started_at);
    $('#resultSubline').textContent = `${Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN')} · ${statusLabel(data.status)}`;
  } else {
    $('#resultSubline').textContent = '暂无任务记录';
  }
}

function renderEvents(events = []) {
  const key = JSON.stringify(events);
  if (key === lastEventsKey) return;
  lastEventsKey = key;
  const container = $('#eventList');
  container.replaceChildren();
  if (!events.length) {
    const empty = document.createElement('div');
    empty.className = 'event-placeholder';
    empty.textContent = '开始任务后，这里会显示采集进度和站点规则。';
    container.append(empty);
    return;
  }
  for (const item of events.slice(-45).reverse()) {
    const row = document.createElement('div');
    row.className = `event-item ${safeText(item.kind)}`;
    const time = document.createElement('span');
    time.className = 'event-time';
    time.textContent = safeText(item.time);
    const message = document.createElement('span');
    message.className = 'event-message';
    message.textContent = safeText(item.message);
    row.append(time, message);
    container.append(row);
  }
}

function statusForRow(item) {
  if (item.error) return { text: item.status_code ? `HTTP ${item.status_code}` : '已跳过', error: true };
  if (item.status_code) return { text: `HTTP ${item.status_code}`, error: item.status_code >= 400 };
  return { text: '待处理', error: false };
}

function openDetails(item) {
  api(`/api/page/${encodeURIComponent(item.id)}`).then((page) => {
    $('#detailTitle').textContent = page.title || page.h1 || '无标题页面';
    const link = $('#detailUrl');
    link.textContent = page.url || '';
    link.href = page.url || '#';
    $('#detailStatus').textContent = page.error ? page.error : `HTTP ${page.status_code || '—'}`;
    $('#detailDepth').textContent = `深度 ${page.depth}`;
    $('#detailSize').textContent = `${Math.max(0, Number(page.bytes_read || 0) / 1024).toFixed(1)} KB`;
    $('#detailDescription').textContent = page.description || '页面没有提供摘要。';
    $('#detailText').textContent = page.text || page.error || '没有可显示的正文。';
    $('#detailDialog').showModal();
  }).catch((error) => showMessage(error.message));
}

function renderResults(results = []) {
  latestResults = results;
  const filter = $('#searchInput').value.trim().toLocaleLowerCase();
  const filtered = results.filter((item) => `${item.title} ${item.url} ${item.description}`.toLocaleLowerCase().includes(filter));
  const body = $('#resultsBody');
  body.replaceChildren();
  $('#tableCount').textContent = `${filtered.length}`;
  const hasRun = Boolean(results.length);
  $('#exportCsv').disabled = !hasRun;
  $('#exportJson').disabled = !hasRun;
  if (!filtered.length) {
    const row = document.createElement('tr');
    row.className = 'empty-row';
    const cell = document.createElement('td');
    cell.colSpan = 5;
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    const icon = document.createElement('div');
    icon.className = 'empty-icon';
    icon.textContent = filter ? '⌕' : '↗';
    const strong = document.createElement('strong');
    strong.textContent = filter ? '没有匹配的结果' : '结果会显示在这里';
    const detail = document.createElement('span');
    detail.textContent = filter ? '试试其他关键词。' : '填写网址并开始任务后，页面摘要会自动保存。';
    empty.append(icon, strong, detail);
    cell.append(empty);
    row.append(cell);
    body.append(row);
    return;
  }
  for (const item of filtered) {
    const row = document.createElement('tr');
    row.className = 'data-row';
    row.tabIndex = 0;
    row.setAttribute('role', 'button');
    row.setAttribute('aria-label', `查看 ${item.title || item.url}`);
    const title = document.createElement('td');
    title.className = 'page-title-cell';
    title.textContent = item.title || item.h1 || '无标题页面';
    title.title = item.title || item.h1 || '无标题页面';
    const url = document.createElement('td');
    url.className = 'url-cell';
    url.textContent = item.url;
    url.title = item.url;
    const depth = document.createElement('td');
    const depthTag = document.createElement('span');
    depthTag.className = 'depth-tag';
    depthTag.textContent = `${item.depth} 层`;
    depth.append(depthTag);
    const status = document.createElement('td');
    const statusText = statusForRow(item);
    const statusTag = document.createElement('span');
    statusTag.className = `http-tag ${statusText.error ? 'error' : ''}`;
    statusTag.textContent = statusText.text;
    status.append(statusTag);
    const date = document.createElement('td');
    date.textContent = item.fetched_at ? new Date(item.fetched_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—';
    row.append(title, url, depth, status, date);
    row.addEventListener('click', () => openDetails(item));
    row.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openDetails(item); } });
    body.append(row);
  }
}

function showMessage(message, isError = true) {
  const el = $('#formMessage');
  el.textContent = safeText(message);
  el.style.color = isError ? 'var(--bad)' : 'var(--good)';
  if (message) window.setTimeout(() => { if (el.textContent === message) el.textContent = ''; }, 6000);
}

async function refresh() {
  try {
    const data = await api('/api/state');
    renderStatus(data);
    renderEvents(data.events || []);
    renderResults(data.results || []);
  } catch (error) {
    showMessage(error.message);
  }
}

$('#startButton').addEventListener('click', async () => {
  const payload = {
    seeds: $('#seeds').value,
    max_pages: Number($('#maxPages').value),
    max_depth: Number($('#maxDepth').value),
    delay_seconds: Number($('#delay').value),
  };
  showMessage('正在创建任务…', false);
  $('#startButton').disabled = true;
  try {
    await api('/api/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    showMessage('任务已启动。', false);
    await refresh();
  } catch (error) {
    showMessage(error.message);
    $('#startButton').disabled = false;
  }
});

$('#stopButton').addEventListener('click', async () => {
  try {
    await api('/api/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    showMessage('已请求停止。', false);
    await refresh();
  } catch (error) { showMessage(error.message); }
});

$('#searchInput').addEventListener('input', () => renderResults(latestResults));
$('#exportCsv').addEventListener('click', () => { window.location.href = '/api/export?format=csv'; });
$('#exportJson').addEventListener('click', () => { window.location.href = '/api/export?format=json'; });
$('#closeDialog').addEventListener('click', () => $('#detailDialog').close());
$('#detailDialog').addEventListener('click', (event) => { if (event.target === $('#detailDialog')) $('#detailDialog').close(); });

refresh();
window.setInterval(refresh, 1800);
