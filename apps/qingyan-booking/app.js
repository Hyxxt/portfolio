const $ = selector => document.querySelector(selector);
const toast = $('#toast');
let toastTimer;
function notify(message) {
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 2600);
}
async function api(path, options = {}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败，请稍后重试');
  return data;
}
function localDateString(date) {
  return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0');
}
function addChatLine(text, who = 'bot') {
  const row = document.createElement('div');
  row.className = 'chat-line ' + (who === 'user' ? 'user-line' : 'bot-line');
  if (who === 'bot') {
    const avatar = document.createElement('div');
    avatar.className = 'bot-avatar'; avatar.textContent = '✳'; row.appendChild(avatar);
  }
  const wrap = document.createElement('div'); wrap.className = 'bubble-wrap';
  if (who === 'bot') { const speaker = document.createElement('span'); speaker.className = 'speaker'; speaker.textContent = '轻颜顾问'; wrap.appendChild(speaker); }
  const bubble = document.createElement('div'); bubble.className = 'bubble'; bubble.textContent = text; wrap.appendChild(bubble); row.appendChild(wrap);
  $('#chatMessages').appendChild(row); $('#chatMessages').scrollTop = $('#chatMessages').scrollHeight;
}
async function sendMessage(message) {
  const clean = message.trim(); if (!clean) return;
  addChatLine(clean, 'user'); $('#chatInput').value = '';
  const submit = $('#chatForm').querySelector('button'); submit.disabled = true;
  try {
    const data = await api('/api/chat', { method: 'POST', body: JSON.stringify({ message: clean }) });
    addChatLine(data.reply); if (data.handoff) notify('已识别为需要人工跟进的特殊情况');
  } catch (error) { addChatLine('服务暂时不可用，请稍后再试，或直接联系门店顾问。'); notify(error.message); }
  finally { submit.disabled = false; $('#chatInput').focus(); }
}
$('#chatForm').addEventListener('submit', event => { event.preventDefault(); sendMessage($('#chatInput').value); });
document.querySelectorAll('[data-message]').forEach(button => button.addEventListener('click', () => sendMessage(button.dataset.message)));

function renderServices(services) {
  const symbols = ['◌', '✧', '☼'];
  $('#serviceGrid').replaceChildren();
  $('#serviceSelect').innerHTML = '<option value="">请选择项目</option>';
  services.forEach((service, index) => {
    const option = document.createElement('option'); option.value = service.name; option.textContent = service.name; $('#serviceSelect').appendChild(option);
    const card = document.createElement('article'); card.className = 'service-card';
    card.innerHTML = '<div class="service-visual visual-' + (index + 1) + '"><span class="service-symbol">' + (symbols[index] || '✳') + '</span></div><div class="service-body"><div class="service-meta"><span>CARE ' + String(index + 1).padStart(2, '0') + '</span><span>' + service.duration + ' MIN</span></div><h3></h3><p>轻柔护理，具体方案由专业顾问结合实际情况确认。</p><div class="service-bottom"><span class="service-price"></span><a class="service-book" href="#book" data-service="">预约咨询 ↗</a></div></div>';
    card.querySelector('h3').textContent = service.name; card.querySelector('.service-price').textContent = service.price;
    card.querySelector('[data-service]').dataset.service = service.name; $('#serviceGrid').appendChild(card);
  });
  document.querySelectorAll('[data-service]').forEach(link => link.addEventListener('click', () => { $('#serviceSelect').value = link.dataset.service; }));
}
async function refreshAppointments() {
  const tbody = $('#appointmentRows'); tbody.innerHTML = '<tr><td colspan="6" class="empty-row">正在读取预约…</td></tr>';
  try {
    const result = await api('/api/appointments'); tbody.replaceChildren();
    if (!result.appointments.length) { tbody.innerHTML = '<tr><td colspan="6" class="empty-row">暂时没有预约记录。提交一笔测试预约后会显示在这里。</td></tr>'; return; }
    result.appointments.forEach(item => {
      const row = document.createElement('tr');
      [item.name, item.phone, item.service, item.visit_date + ' ' + item.visit_time, item.note || '—'].forEach(value => { const cell = document.createElement('td'); cell.textContent = value; row.appendChild(cell); });
      const actions = document.createElement('td'); const status = document.createElement('span');
      status.className = 'status-pill ' + (item.status === '已确认' ? 'confirmed' : ''); status.textContent = item.status; actions.appendChild(status);
      if (item.status === '待确认') ['已确认', '已取消'].forEach(nextStatus => {
        const button = document.createElement('button'); button.className = 'table-action'; button.textContent = nextStatus;
        button.addEventListener('click', async () => { try { await api('/api/appointments/' + item.id, { method: 'PATCH', body: JSON.stringify({ status: nextStatus }) }); notify('预约已' + (nextStatus === '已确认' ? '确认' : '取消')); refreshAppointments(); } catch (error) { notify(error.message); } });
        actions.appendChild(button);
      });
      row.appendChild(actions); tbody.appendChild(row);
    });
  } catch (error) { tbody.innerHTML = '<tr><td colspan="6" class="empty-row">无法读取预约，请确认本地服务正在运行。</td></tr>'; }
}
$('#bookingForm').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget; const submit = form.querySelector('button[type="submit"]'); submit.disabled = true;
  const payload = Object.fromEntries(new FormData(form).entries());
  try {
    const result = await api('/api/appointments', { method: 'POST', body: JSON.stringify(payload) });
    form.hidden = true; $('#bookingSuccess').hidden = false; $('#successText').textContent = result.message + '预约编号 #' + result.id + '。'; notify('预约意向提交成功'); refreshAppointments();
  } catch (error) { notify(error.message); } finally { submit.disabled = false; }
});
$('#bookAnother').addEventListener('click', () => { $('#bookingForm').reset(); $('#bookingForm').hidden = false; $('#bookingSuccess').hidden = true; });
$('#staffToggle').addEventListener('click', async () => { const panel = $('#staffPanel'); panel.hidden = !panel.hidden; if (!panel.hidden) { await refreshAppointments(); panel.scrollIntoView({ behavior: 'smooth', block: 'start' }); } });
$('#refreshAppointments').addEventListener('click', refreshAppointments);
async function initialize() {
  const today = new Date(); $('#visitDate').min = localDateString(today);
  const maximum = new Date(today); maximum.setDate(maximum.getDate() + 90); $('#visitDate').max = localDateString(maximum);
  try { const data = await api('/api/services'); renderServices(data.services); }
  catch (error) { notify('无法连接服务端，请用 start.bat 启动应用'); }
}
initialize();
