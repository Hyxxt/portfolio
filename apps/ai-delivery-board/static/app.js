const API = "/api/tasks";
const STATUS = {todo:"待开始", doing:"进行中", done:"已完成"};
const PRIORITY = {high:"高优先级", medium:"中优先级", low:"低优先级"};
let tasks = [];
let toastTimer;

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value="") => String(value).replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]));

async function request(url, options={}) {
  const response = await fetch(url, {headers:{"Content-Type":"application/json", ...(options.headers||{})}, ...options});
  const data = await response.json().catch(()=>({error:"服务器返回了无法读取的数据。"}));
  if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
  return data;
}

function formatDate(value) {
  if (!value) return "未设置截止日期";
  const [year, month, day] = value.split("-");
  return `${year}.${month}.${day}`;
}

function isOverdue(task) {
  return task.due_date && task.status !== "done" && task.due_date < new Date().toISOString().slice(0,10);
}

function renderCard(task) {
  const overdue = isOverdue(task);
  return `<article class="task-card" draggable="true" data-id="${task.id}" aria-label="任务：${escapeHtml(task.title)}">
    <div class="task-card-top"><span class="priority ${task.priority}">${PRIORITY[task.priority]}</span><div class="card-actions"><button data-action="edit" data-id="${task.id}" aria-label="编辑任务">✎</button><button data-action="delete" data-id="${task.id}" aria-label="删除任务">×</button></div></div>
    <h3>${escapeHtml(task.title)}</h3>${task.description?`<p>${escapeHtml(task.description)}</p>`:""}
    <div class="card-footer"><span class="due-date ${overdue?"overdue":""}">${task.due_date?`${overdue?"已逾期 · ":"截止 "}${formatDate(task.due_date)}`:"未设置截止日期"}</span><select class="card-status" data-action="status" data-id="${task.id}" aria-label="更改任务状态">${Object.entries(STATUS).map(([key,label])=>`<option value="${key}" ${task.status===key?"selected":""}>${label}</option>`).join("")}</select></div>
  </article>`;
}

function render() {
  const search = $("#searchInput").value.trim().toLowerCase();
  const priority = $("#priorityFilter").value;
  const visible = tasks.filter(task => (!priority || task.priority===priority) && (!search || `${task.title} ${task.description}`.toLowerCase().includes(search)));
  for (const status of Object.keys(STATUS)) {
    const columnTasks = visible.filter(task => task.status===status);
    const listId = status === "todo" ? "#listTodo" : status === "doing" ? "#listDoing" : "#listDone";
    $(listId).innerHTML = columnTasks.length ? columnTasks.map(renderCard).join("") : `<div class="empty-state">${search||priority?"没有匹配的任务":"还没有任务"}</div>`;
    const countId = status === "todo" ? "#countTodo" : status === "doing" ? "#countDoing" : "#countDone";
    $(countId).textContent = columnTasks.length;
  }
  $("#statTotal").textContent = tasks.length;
  $("#statTodo").textContent = tasks.filter(t=>t.status==="todo").length;
  $("#statDoing").textContent = tasks.filter(t=>t.status==="doing").length;
  $("#statDone").textContent = tasks.filter(t=>t.status==="done").length;
  $("#visibleCount").textContent = `${visible.length} 项`;
  bindCardEvents();
}

async function loadTasks() {
  const data = await request(API);
  tasks = data.tasks;
  render();
  $("#apiStatus").textContent = "API 已连接 · 本地保存";
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(()=>toast.classList.remove("show"), 2400);
}

function openModal(task=null, status="todo") {
  $("#taskForm").reset();
  $("#taskId").value = task?.id || "";
  $("#taskTitle").value = task?.title || "";
  $("#taskDescription").value = task?.description || "";
  $("#taskStatus").value = task?.status || status;
  $("#taskPriority").value = task?.priority || "medium";
  $("#taskDueDate").value = task?.due_date || "";
  $("#formError").textContent = "";
  $("#modalTitle").textContent = task ? "编辑任务" : "新建任务";
  $("#saveTask").textContent = task ? "保存修改" : "保存任务";
  $("#modalBackdrop").hidden = false;
  document.body.style.overflow = "hidden";
  setTimeout(()=>$("#taskTitle").focus(),50);
}

function closeModal() {
  $("#modalBackdrop").hidden = true;
  document.body.style.overflow = "";
}

function bindCardEvents() {
  document.querySelectorAll(".task-card").forEach(card=>{
    card.addEventListener("dragstart", event=>{
      card.classList.add("dragging");
      event.dataTransfer.setData("text/plain", card.dataset.id);
      event.dataTransfer.effectAllowed = "move";
    });
    card.addEventListener("dragend", ()=>card.classList.remove("dragging"));
  });
  document.querySelectorAll(".column").forEach(column=>{
    column.ondragover = event=>{event.preventDefault(); column.classList.add("drag-over")};
    column.ondragleave = event=>{if(!column.contains(event.relatedTarget)) column.classList.remove("drag-over")};
    column.ondrop = async event=>{
      event.preventDefault(); column.classList.remove("drag-over");
      const id = Number(event.dataTransfer.getData("text/plain"));
      if(id) await updateTask(id,{status:column.dataset.status},"任务状态已更新");
    };
  });
}

async function updateTask(id, patch, successMessage="已保存") {
  try { await request(`${API}/${id}`,{method:"PATCH",body:JSON.stringify(patch)}); await loadTasks(); showToast(successMessage); }
  catch(error) { showToast(error.message); }
}

document.addEventListener("click", async event=>{
  const addButton=event.target.closest("[data-add-status]");
  if(addButton){openModal(null,addButton.dataset.addStatus);return}
  const action=event.target.closest("[data-action]");
  if(!action)return;
  const id=Number(action.dataset.id), task=tasks.find(item=>item.id===id);
  if(action.dataset.action==="edit"&&task) openModal(task);
  if(action.dataset.action==="delete"&&task){
    if(!window.confirm(`确定删除“${task.title}”吗？`))return;
    try{await request(`${API}/${id}`,{method:"DELETE"});await loadTasks();showToast("任务已删除")}
    catch(error){showToast(error.message)}
  }
});

document.addEventListener("change", event=>{
  if(event.target.matches('[data-action="status"]')) updateTask(Number(event.target.dataset.id),{status:event.target.value});
});

$("#taskForm").addEventListener("submit",async event=>{
  event.preventDefault();
  const id=$("#taskId").value;
  const payload={title:$("#taskTitle").value,description:$("#taskDescription").value,status:$("#taskStatus").value,priority:$("#taskPriority").value,due_date:$("#taskDueDate").value};
  try{
    await request(id?`${API}/${id}`:API,{method:id?"PATCH":"POST",body:JSON.stringify(payload)});
    closeModal();await loadTasks();showToast(id?"修改已保存":"任务已创建");
  }catch(error){$("#formError").textContent=error.message}
});

$("#addTaskTop").addEventListener("click",()=>openModal());
$("#closeModal").addEventListener("click",closeModal);
$("#cancelModal").addEventListener("click",closeModal);
$("#modalBackdrop").addEventListener("click",event=>{if(event.target.id==="modalBackdrop")closeModal()});
document.addEventListener("keydown",event=>{if(event.key==="Escape"&&!$("#modalBackdrop").hidden)closeModal()});
$("#searchInput").addEventListener("input",render);
$("#priorityFilter").addEventListener("change",render);

loadTasks().catch(error=>{
  $("#apiStatus").textContent="API 未连接";
  $("#apiStatus").style.background="#fff0eb";
  $("#apiStatus").style.color="#b6533d";
  showToast(`无法加载任务：${error.message}`);
});
