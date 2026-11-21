const $ = (selector) => document.querySelector(selector);
const request = async (url, options = {}) => {
  const response = await fetch(url, { cache: 'no-store', ...options });
  const type = response.headers.get('content-type') || '';
  const body = type.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(body?.error || `请求失败：${response.status}`);
  return body;
};

let lastActivity = '';

function showMessage(message, error = false) {
  const el = $('#formMessage');
  el.textContent = String(message || '');
  el.style.color = error ? 'var(--red)' : 'var(--green)';
  if (message) setTimeout(() => { if (el.textContent === message) el.textContent = ''; }, 5000);
}

function formatTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function renderTasks(tasks) {
  const list = $('#taskList');
  list.replaceChildren();
  $('#taskCountText').textContent = tasks.length ? `${tasks.length} 个任务 · 每个任务串行执行` : '还没有任务';
  if (!tasks.length) {
    const empty = document.createElement('div'); empty.className = 'empty-state';
    const symbol = document.createElement('div'); symbol.className = 'empty-symbol'; symbol.textContent = '↻';
    const strong = document.createElement('strong'); strong.textContent = '创建一个自动化任务';
    const hint = document.createElement('span'); hint.textContent = '任务保存后可手动运行，也可启用周期调度。';
    empty.append(symbol,strong,hint); list.append(empty); return;
  }
  for (const task of tasks) {
    const row = document.createElement('article'); row.className = 'task-row';
    const main = document.createElement('div'); main.className = 'task-main';
    const titleLine = document.createElement('div'); titleLine.className = 'task-titleline';
    const title = document.createElement('strong'); title.className = 'task-title'; title.textContent = task.name; title.title = task.name;
    const badge = document.createElement('span'); badge.className = `task-state ${task.running ? 'running' : (task.active ? 'active' : '')}`;
    badge.textContent = task.running ? '执行中' : (task.queued ? '排队中' : (task.active ? '定时已启用' : '已暂停'));
    titleLine.append(title,badge);
    const details = document.createElement('div'); details.className = 'task-details';
    details.textContent = `${task.seeds.length} 个起始网址 · ${task.max_pages} 页上限 · 深度 ${task.max_depth} · ${task.interval_hours} 小时运行一次${task.active ? ` · 下次 ${formatTime(task.next_run_at)}` : ''}`;
    main.append(titleLine,details);
    const actions = document.createElement('div'); actions.className = 'task-actions';
    const run = document.createElement('button'); run.className = 'mini-btn primary'; run.textContent = task.running || task.queued ? '已排队' : '运行一次'; run.disabled = Boolean(task.running || task.queued); run.dataset.action = 'run'; run.dataset.id = task.id;
    const toggle = document.createElement('button'); toggle.className = `mini-btn ${task.active ? 'pause' : ''}`; toggle.textContent = task.active ? '暂停定时' : '启用定时'; toggle.dataset.action = 'toggle'; toggle.dataset.id = task.id;
    actions.append(run,toggle); row.append(main,actions); list.append(row);
  }
}

function renderRuns(runs) {
  const body = $('#runsBody'); body.replaceChildren();
  if (!runs.length) {
    const row=document.createElement('tr'); row.className='empty-row'; const cell=document.createElement('td'); cell.colSpan=5; cell.textContent='暂无运行记录'; row.append(cell); body.append(row); return;
  }
  for (const run of runs) {
    const row=document.createElement('tr');
    const task=document.createElement('td'); task.className='run-name'; task.textContent=run.task_name; task.title=run.task_name;
    const state=document.createElement('td'); const badge=document.createElement('span'); badge.className=`state-tag ${run.status}`; badge.textContent=({running:'运行中',completed:'已完成',stopped:'已停止',failed:'异常'})[run.status]||run.status; state.append(badge);
    const changed=document.createElement('td'); changed.className='change-count'; changed.textContent=run.changed_count||0;
    const date=document.createElement('td'); date.textContent=formatTime(run.started_at);
    const action=document.createElement('td'); const button=document.createElement('button'); button.className='table-btn'; button.textContent='查看'; button.dataset.run=run.id; action.append(button);
    row.append(task,state,changed,date,action); body.append(row);
  }
}

function renderActivity(events) {
  const key=JSON.stringify(events);
  if (key===lastActivity) return;
  lastActivity=key;
  const list=$('#activityList'); list.replaceChildren();
  if (!events.length) { const p=document.createElement('div'); p.className='activity-empty'; p.textContent='任务启动后，队列状态与采集进度会显示在这里。'; list.append(p); return; }
  for (const event of [...events].reverse().slice(0,36)) {
    const row=document.createElement('div'); row.className=`activity-row ${event.kind||''}`;
    const time=document.createElement('span'); time.className='activity-time'; time.textContent=event.time||'';
    const text=document.createElement('span'); text.className='activity-text'; text.textContent=event.message||'';
    row.append(time,text); list.append(row);
  }
}

function render(data) {
  renderTasks(data.tasks||[]); renderRuns(data.runs||[]); renderActivity(data.events||[]);
  $('#metricTasks').textContent=(data.tasks||[]).length;
  $('#metricQueue').textContent=data.queue_size||0;
  const active=data.active_run||{};
  $('#metricState').textContent=active.run_id?'运行中':'空闲';
  $('#metricState').style.color=active.run_id?'var(--teal-dark)':'#718294';
  $('#metricSub').textContent=active.run_id?`任务 #${active.task_id} · ${formatTime(active.started_at)}`:'等待任务';
  const latest=(data.runs||[])[0]; $('#metricChanges').textContent=latest?.changed_count||0;
  $('#queueBadge').textContent=data.queue_size?`${data.queue_size} 个任务待执行`:'队列空闲';
  $('#queueBadge').classList.toggle('busy',Boolean(data.queue_size||active.run_id));
  $('#liveDot').classList.toggle('paused',!active.run_id);
}

async function refresh() {
  try { render(await request('/api/state')); }
  catch (err) { showMessage(err.message,true); }
}

$('#taskForm').addEventListener('submit',async (event)=>{
  event.preventDefault();
  const payload={name:$('#taskName').value.trim(),seeds:$('#seeds').value,max_pages:Number($('#maxPages').value),max_depth:Number($('#maxDepth').value),interval_hours:Number($('#interval').value)};
  const button=$('#taskForm button[type="submit"]'); button.disabled=true;
  try {
    await request('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    showMessage('任务已保存，当前为暂停状态。');
    $('#taskName').value=''; $('#seeds').value=''; await refresh();
  } catch(err) { showMessage(err.message,true); }
  finally { button.disabled=false; }
});

$('#taskList').addEventListener('click',async(event)=>{
  const button=event.target.closest('button[data-action]'); if(!button)return;
  const {action,id}=button.dataset; button.disabled=true;
  try {
    await request(`/api/tasks/${encodeURIComponent(id)}/${action}`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    await refresh();
  } catch(err) { showMessage(err.message,true); }
  finally { button.disabled=false; }
});

$('#runsBody').addEventListener('click',async(event)=>{
  const button=event.target.closest('button[data-run]'); if(!button)return;
  const runId=button.dataset.run;
  try {
    const data=await request(`/api/run/${encodeURIComponent(runId)}`);
    $('#reportTitle').textContent=`${data.run.task_name} · ${formatTime(data.run.started_at)}`;
    const lines=[
      `状态：${data.run.status}`,
      `处理页面：${data.run.pages_seen} · 成功：${data.run.pages_ok} · 变化：${data.run.changed_count} · 重复：${data.run.duplicate_count} · 异常：${data.run.error_count}`,
      '',
      ...(data.pages||[]).map(page=>`${page.change_type.toUpperCase()}  ${page.title||'无标题'}\n${page.url}${page.error?`\n${page.error}`:''}`),
    ];
    $('#reportContent').textContent=lines.join('\n');
    const downloads=document.createElement('div'); downloads.className='download-actions';
    for (const format of ['csv','json']) { const a=document.createElement('a'); a.className='download-link'; a.href=`/api/export?run=${encodeURIComponent(runId)}&format=${format}`; a.textContent=`下载 ${format.toUpperCase()}`; downloads.append(a); }
    const report=document.createElement('a'); report.className='download-link'; report.href=`/api/report/${encodeURIComponent(runId)}`; report.textContent='下载 Markdown 报告'; downloads.append(report);
    $('#reportContent').append(document.createTextNode('\n\n')); $('#reportContent').append(downloads);
    $('#reportDialog').showModal();
  } catch(err) { showMessage(err.message,true); }
});

$('#refreshButton').addEventListener('click',refresh);
$('#closeDialog').addEventListener('click',()=>$('#reportDialog').close());
$('#reportDialog').addEventListener('click',(event)=>{if(event.target===$('#reportDialog'))$('#reportDialog').close();});

refresh(); setInterval(refresh,2200);
