const $ = selector => document.querySelector(selector);
const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]));
let customers = [];
let toastTimer;

async function request(url, options={}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `请求失败 (${response.status})`);
  return data;
}
function money(value) { return `¥${Number(value || 0).toLocaleString("zh-CN", {maximumFractionDigits:0})}`; }
function showToast(message) {
  const toast = $("#toast"); toast.textContent = message; toast.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.remove("show"), 2500);
}
function renderOverview(data) {
  $("#metricOrders").textContent = data.orders;
  $("#metricRevenue").textContent = money(data.revenue);
  $("#metricRepeat").textContent = `${data.repeat_rate}%`;
  $("#metricRepeatCount").textContent = data.repeat_customers;
  $("#metricDue").textContent = data.due_followups;
  $("#dataNote").textContent = data.data_note;
  const maxRevenue = Math.max(1, ...data.trend.map(x => x.revenue));
  $("#trendChart").innerHTML = data.trend.map(item => {
    const height = Math.max(4, Math.round(item.revenue / maxRevenue * 82));
    return `<div class="trend-item"><span class="trend-value">${item.revenue ? money(item.revenue) : "—"}</span><div class="trend-bar" style="height:${height}px"></div><span class="trend-label">${escapeHtml(item.month)}</span></div>`;
  }).join("");
  const maxChannel = Math.max(1, ...data.channels.map(x => x.n));
  $("#channelChart").innerHTML = data.channels.length ? data.channels.map(item => `<div class="channel-row"><span>${escapeHtml(item.channel)}</span><div class="channel-track"><div class="channel-fill" style="width:${Math.round(item.n/maxChannel*100)}%"></div></div><b>${item.n}</b></div>`).join("") : `<div class="empty">暂无订单</div>`;
}
function renderCustomers() {
  const q = $("#search").value.trim().toLowerCase();
  const segment = $("#segmentFilter").value;
  const followup = $("#followupFilter").value;
  const visible = customers.filter(c => {
    const haystack = `${c.customer_id} ${c.last_product} ${c.country} ${c.last_channel}`.toLowerCase();
    return (!q || haystack.includes(q)) && (!segment || c.segment === segment) && (!followup || c.followup_status === followup);
  });
  $("#customerCount").textContent = `${visible.length} 位客户`;
  $("#emptyState").hidden = visible.length > 0;
  $("#customerList").innerHTML = visible.map(c => {
    const contacted = c.followup_status === "contacted";
    return `<article class="customer-card">
      <div class="customer-top"><div class="customer-identity"><div class="avatar">${escapeHtml(c.customer_id.slice(-2))}</div><div><div class="customer-id">${escapeHtml(c.customer_id)} <span class="badge ${escapeHtml(c.segment)}">${escapeHtml(c.segment)}</span></div><div class="customer-sub">${escapeHtml(c.country)} · ${escapeHtml(c.last_channel)}</div></div></div><div class="score">${c.score}<small> 规则分</small></div></div>
      <div class="customer-facts"><span>累计订单<b>${c.orders}</b></span><span>累计消费<b>${money(c.spend)}</b></span><span>距上次购买<b>${c.days_since_last} 天</b></span><span>最近商品<b>${escapeHtml(c.last_product)}</b></span></div>
      <div class="recommendation"><div class="recommendation-text"><strong>${escapeHtml(c.next_action)}</strong><p>${escapeHtml(c.reason)}</p></div><button class="follow-button ${contacted?"contacted":""}" data-customer="${escapeHtml(c.customer_id)}" data-status="${contacted?"pending":"contacted"}">${contacted?"恢复待联系":"标记已联系"}</button></div>
    </article>`;
  }).join("");
}
async function refresh() {
  try {
    const [overview, customerData] = await Promise.all([request("/api/overview"), request("/api/customers")]);
    renderOverview(overview); customers = customerData.customers; renderCustomers();
  } catch (error) {
    $("#customerList").innerHTML = `<div class="empty">无法连接本地服务：${escapeHtml(error.message)}</div>`;
    showToast(error.message);
  }
}

$("#search").addEventListener("input", renderCustomers);
$("#segmentFilter").addEventListener("change", renderCustomers);
$("#followupFilter").addEventListener("change", renderCustomers);
$("#customerList").addEventListener("click", async event => {
  const button = event.target.closest("[data-customer]"); if (!button) return;
  button.disabled = true;
  try {
    await request(`/api/followups/${encodeURIComponent(button.dataset.customer)}/status`, {
      method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({status:button.dataset.status})
    });
    await refresh(); showToast(button.dataset.status === "contacted" ? "已记录联系状态" : "已恢复待联系");
  } catch (error) { showToast(error.message); button.disabled = false; }
});
$("#csvFile").addEventListener("change", async event => {
  const file = event.target.files[0]; if (!file) return;
  const resultBox = $("#importResult"); resultBox.hidden = false; resultBox.classList.remove("error"); resultBox.textContent = "正在校验并导入 CSV…";
  try {
    const data = await request("/api/import", {method:"POST", headers:{"Content-Type":"text/csv; charset=utf-8"}, body:await file.text()});
    resultBox.innerHTML = `新增 ${data.inserted} 条，重复跳过 ${data.skipped_duplicates} 条，校验拒绝 ${data.rejected} 条。` + (data.errors.length ? `<br>${data.errors.map(e=>`第 ${e.row} 行：${escapeHtml(e.error)}`).join("<br>")}` : "");
    await refresh(); showToast(`导入完成：新增 ${data.inserted} 条`);
  } catch (error) { resultBox.classList.add("error"); resultBox.textContent = error.message; showToast(error.message); }
  finally { event.target.value = ""; }
});

refresh();
