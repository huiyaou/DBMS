"use strict";

const $ = (selector) => document.querySelector(selector);
const root = $("#app");
const state = { user: null, mode: "login", page: "dashboard", survey: null, dirty: false, busy: false, filter: "", offset: 0, list: null, preview: null };
const labels = { draft: "草稿", published: "已发布", closed: "已关闭", expired: "已截止" };
const types = { single_choice: "单选题", multiple_choice: "多选题", text: "文本填空", number: "数字填空" };
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clone = (value) => JSON.parse(JSON.stringify(value));
const uid = () => crypto.randomUUID();
const brand = (light = false) => `<div class="brand ${light ? "brand-light" : ""}"><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span><span>问卷工坊</span></div>`;
const badge = (status) => `<span class="badge ${esc(status)}">${labels[status] || esc(status)}</span>`;
const dateLabel = (date) => date ? new Date(date).toLocaleDateString("zh-CN") : "—";
const getPath = (path) => path.split(".").reduce((obj, key) => obj?.[key], state.survey);
function setPath(path, value, remove = false) {
  const keys = path.split(".");
  const last = keys.pop();
  const parent = keys.reduce((obj, key) => obj[key], state.survey);
  if (remove) delete parent[last]; else parent[last] = value;
}
function toast(message, error = false) {
  const node = $("#toast"); node.textContent = message; node.className = `visible${error ? " error" : ""}`;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { node.className = ""; }, 4500);
}
function confirmAction(title, description, ok = "确定") {
  const dialog = $("#confirm-dialog");
  $("#confirm-title").textContent = title; $("#confirm-description").textContent = description; $("#confirm-ok").textContent = ok;
  return new Promise((resolve) => {
    const finish = (answer) => { dialog.close(); dialog.oncancel = null; resolve(answer); };
    $("#confirm-ok").onclick = () => finish(true); $("#confirm-cancel").onclick = () => finish(false);
    dialog.oncancel = (event) => { event.preventDefault(); finish(false); }; dialog.showModal();
  });
}
async function api(path, { method = "GET", body } = {}) {
  const response = await fetch(`/api${path}`, { method, credentials: "same-origin", headers: method === "GET" ? {} : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof data.detail === "string" ? data.detail : data.detail?.message || "填写内容格式有误，请检查题目、选项和数字设置。";
    const error = new Error(message); error.status = response.status; throw error;
  }
  return data;
}
async function run(action) {
  if (state.busy) return;
  state.busy = true; document.body.classList.add("busy");
  try { await action(); }
  catch (error) {
    if (error.status === 401) { state.user = null; renderAuth(); }
    toast(error.message === "Failed to fetch" ? "无法连接服务，请检查服务是否仍在运行。" : error.message, true);
  } finally { state.busy = false; document.body.classList.remove("busy"); }
}
function shell(content) {
  return `<div class="shell"><aside class="sidebar">${brand()}<div class="sidebar-subtitle">从一个好问题开始</div><button class="nav-item" data-action="dashboard"><span class="nav-icon" aria-hidden="true">▤</span>我的问卷</button><div class="sidebar-bottom"><p class="sidebar-caption">整理你的想法，<br>让每个问题都有回响。</p><div class="account"><div class="avatar">${esc(state.user.username.slice(0, 1))}</div><div><div class="account-name">${esc(state.user.username)}</div><button data-action="logout">退出登录</button></div></div></div></aside><main class="workspace">${content}</main></div>`;
}
function renderAuth() {
  const register = state.mode === "register";
  root.innerHTML = `<div class="auth-layout"><section class="auth-story">${brand(true)}<div class="story-copy"><div class="eyebrow">ASK. LISTEN. UNDERSTAND.</div><h1>好的发现，<br>从好的问题开始。</h1><p>把想了解的事，变成一份清晰的问卷。用简单的方式，收集不同的声音。</p><div class="story-steps"><span><b>01</b>写下问题</span><span><b>02</b>整理问卷</span><span><b>03</b>分享链接</span></div></div><div class="story-shape" aria-hidden="true"></div><div class="story-footer">一份问卷 · 更多理解</div></section><main class="auth-main"><section class="auth-card"><div class="eyebrow">YOUR QUESTIONNAIRE WORKSPACE</div><h1>${register ? "创建你的账号" : "欢迎回来"}</h1><p>${location.pathname.startsWith("/survey/") ? "登录后即可查看这份问卷。" : "登录你的空间，开始整理下一份问卷。"}</p><div class="auth-tabs"><button data-action="auth-mode" data-mode="login" class="${!register ? "active" : ""}">登录</button><button data-action="auth-mode" data-mode="register" class="${register ? "active" : ""}">注册</button></div><form id="auth-form"><label class="field"><span>用户名</span><input name="username" required maxlength="64" autocomplete="username" placeholder="请输入用户名"></label><label class="field"><span>密码</span><input name="password" type="password" required minlength="8" maxlength="128" autocomplete="${register ? "new-password" : "current-password"}" placeholder="8～128 个字符"></label>${register ? '<label class="field"><span>确认密码</span><input name="confirm" type="password" required minlength="8" maxlength="128" autocomplete="new-password" placeholder="再次输入密码"></label>' : ""}<p class="error-inline" id="auth-error" role="alert"></p><button class="button primary wide" type="submit">${register ? "注册并进入工作台" : "登录工作台"}<span aria-hidden="true">→</span></button></form><p class="fineprint">你的账号用于创建和管理自己的问卷</p></section></main></div>`;
}
async function loadDashboard() {
  const params = new URLSearchParams({ offset: state.offset, limit: 12 });
  if (state.filter) params.set("status", state.filter);
  state.list = await api(`/surveys?${params}`);
  state.page = "dashboard"; state.survey = null; state.fill = null; state.dirty = false;
  history.replaceState(null, "", "/"); renderDashboard();
}
function renderDashboard() {
  const data = state.list, counts = data.counts;
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const rows = data.items.map((s) => `<div class="survey-row"><div class="survey-main"><span class="document-icon" aria-hidden="true"><i></i><i></i><i></i></span><div style="min-width:0"><button class="survey-title" data-action="open" data-id="${s.id}">${esc(s.title || "未命名问卷")}</button><div class="survey-detail">${s.questions.length} 道题目 · ${s.settings.allow_anonymous ? "允许匿名" : "实名填写"}</div></div></div><div>${badge(s.effective_status)}</div><div class="survey-date">${dateLabel(s.updated_at)}<br>最近修改</div><div class="survey-actions"><button class="button ghost small" data-action="open" data-id="${s.id}">${s.status === "draft" ? "编辑" : "管理"}<span aria-hidden="true">→</span></button></div></div>`).join("");
  root.innerHTML = shell(`<header class="page-heading"><div><div class="eyebrow">MY WORKSPACE</div><h1>我的问卷</h1><p>从这里开始，构建、整理和分享你的问卷。</p></div><button class="button primary" data-action="create">＋ 新建问卷</button></header><section class="summary-grid" aria-label="问卷概览">${[["全部问卷", total], ["草稿", counts.draft], ["已发布", counts.published], ["已关闭 / 截止", counts.closed + counts.expired]].map(([name, count]) => `<div class="summary"><span>${name}</span><strong>${count.toString().padStart(2, "0")}</strong></div>`).join("")}</section><section class="list-panel"><div class="list-toolbar"><div class="filter-tabs">${[["", "全部"], ...Object.entries(labels)].map(([key, value]) => `<button class="${state.filter === key ? "active" : ""}" data-action="filter" data-filter="${key}">${value}</button>`).join("")}</div><span class="hint">共 ${data.total} 份</span></div>${rows ? `<div class="list-column-head"><span>问卷名称</span><span>状态</span><span class="list-date-label">更新时间</span><span></span></div>${rows}` : `<div class="empty"><div class="empty-icon" aria-hidden="true">▤</div><h3>${state.filter ? "这里还没有问卷" : "你的第一份问卷，从这里开始"}</h3><p>${state.filter ? "试试切换其他状态，或创建一份新的问卷。" : "写下想问的问题，再把它分享给你想了解的人。"}</p><button class="button secondary" data-action="create">＋ 创建问卷</button></div>`}<div class="pagination"><span>${data.total ? `${data.offset + 1}–${data.offset + data.items.length} / ${data.total}` : "暂无记录"}</span><div class="button-row"><button class="button ghost small" data-action="previous" ${state.offset === 0 ? "disabled" : ""}>上一页</button><button class="button ghost small" data-action="next" ${state.offset + 12 >= data.total ? "disabled" : ""}>下一页</button></div></div></section>`);
  root.querySelectorAll(".survey-row").forEach((row, i) => {
    if (data.items[i].status !== "draft") addResultsButton(row.querySelector(".survey-actions"), data.items[i].id);
  });
}
function markDirty() { state.dirty = true; const node = $("#save-label"); if (node) node.textContent = "有未保存的修改"; }
function localDate(value) {
  if (!value) return "";
  const date = new Date(value); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
function inputField(path, label, { type = "text", placeholder = "", min, max, step, value } = {}) {
  const current = value ?? (type === "datetime-local" ? localDate(getPath(path)) : getPath(path)) ?? "";
  return `<label class="field"><span>${label}</span><input type="${type}" data-bind="${path}" value="${esc(current)}" placeholder="${esc(placeholder)}" ${min !== undefined ? `min="${min}"` : ""} ${max !== undefined ? `max="${max}"` : ""} ${step ? `step="${step}"` : ""}></label>`;
}
function targetOptions(index, selected) {
  return [["NEXT", "顺序进入下一题"], ["END", "结束问卷"], ...state.survey.questions.slice(index + 1).map((q, offset) => [q.id, `第 ${index + offset + 2} 题 · ${q.title || types[q.type]}`])].map(([value, name]) => `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(name)}</option>`).join("");
}
function ruleCard(q, index, rule, r) {
  const path = `questions.${index}.logic.rules.${r}`, condition = rule.condition;
  let conditionInputs;
  if (q.type === "single_choice") conditionInputs = `<label class="field"><span>当选择</span><select data-bind="${path}.condition.value">${q.options.map((o) => `<option value="${esc(o.id)}" ${condition.value === o.id ? "selected" : ""}>${esc(o.label || "未命名选项")}</option>`).join("")}</select></label>`;
  else if (q.type === "multiple_choice") conditionInputs = `<label class="field"><span>匹配方式</span><select data-bind="${path}.condition.operator">${[["contains_any", "包含任意一项"], ["contains_all", "包含所有选项"], ["equals_set", "恰好选择这些项"]].map(([value, name]) => `<option value="${value}" ${value === condition.operator ? "selected" : ""}>${name}</option>`).join("")}</select></label><label class="field"><span>选择选项（可多选）</span><select multiple data-bind="${path}.condition.value">${q.options.map((o) => `<option value="${esc(o.id)}" ${condition.value.includes(o.id) ? "selected" : ""}>${esc(o.label || "未命名选项")}</option>`).join("")}</select></label>`;
  else conditionInputs = `<label class="field"><span>当数值</span><select data-rule-operator="${index},${r}">${[["eq", "等于"], ["gt", "大于"], ["gte", "大于等于"], ["lt", "小于"], ["lte", "小于等于"], ["between", "位于闭区间"]].map(([value, name]) => `<option value="${value}" ${value === condition.operator ? "selected" : ""}>${name}</option>`).join("")}</select></label>${condition.operator === "between" ? inputField(`${path}.condition.value.0`, "区间最小值", { type: "number", step: "any" }) + inputField(`${path}.condition.value.1`, "区间最大值", { type: "number", step: "any" }) : inputField(`${path}.condition.value`, "比较数值", { type: "number", step: "any" })}`;
  return `<div class="rule"><div class="rule-header"><span>条件 ${r + 1}</span><button type="button" data-action="remove-rule" data-index="${index}" data-rule="${r}" aria-label="删除条件 ${r + 1}">删除</button></div><div class="rule-grid">${conditionInputs}</div><label class="target-row"><span>满足时跳到</span><select data-bind="${path}.target">${targetOptions(index, rule.target)}</select></label></div>`;
}
function questionCard(q, index) {
  const path = `questions.${index}`, editable = state.survey.status === "draft";
  let fields = "";
  if (q.options) fields += `<div class="options-list">${q.options.map((option, o) => `<div class="option-row"><span class="option-marker ${q.type === "multiple_choice" ? "square" : ""}" aria-hidden="true"></span><input class="input" aria-label="第 ${index + 1} 题选项 ${o + 1}" data-bind="${path}.options.${o}.label" maxlength="200" value="${esc(option.label)}" placeholder="选项内容"><button type="button" data-action="remove-option" data-index="${index}" data-option="${o}" aria-label="删除选项 ${o + 1}">×</button></div>`).join("")}</div><button type="button" class="button ghost small" data-action="add-option" data-index="${index}">＋ 添加选项</button>`;
  if (q.type === "multiple_choice") fields += `<div class="validation-grid">${inputField(`${path}.validation.min_choices`, "至少选择", { type: "number", min: 0, max: 50, placeholder: "不限" })}${inputField(`${path}.validation.max_choices`, "最多选择", { type: "number", min: 0, max: 50, placeholder: "不限" })}</div><p class="hint" style="margin-top:8px">设置相同的最少和最多数量，可要求恰好选择指定项数。</p>`;
  if (q.type === "text") fields += `<div class="validation-grid">${inputField(`${path}.validation.min_length`, "最少字数", { type: "number", min: 0, max: 100000, placeholder: "不限" })}${inputField(`${path}.validation.max_length`, "最多字数", { type: "number", min: 0, max: 100000, placeholder: "不限" })}</div>`;
  if (q.type === "number") fields += `<div class="validation-grid">${inputField(`${path}.validation.min_value`, "最小值", { type: "number", step: "any", placeholder: "不限" })}${inputField(`${path}.validation.max_value`, "最大值", { type: "number", step: "any", placeholder: "不限" })}</div><label class="check" style="margin-top:13px"><input type="checkbox" data-bind="${path}.validation.integer_only" ${q.validation.integer_only ? "checked" : ""}>仅允许整数</label>`;
  return `<section class="card question-card" id="question-${index}"><div class="card-title"><div class="question-heading"><span class="question-number">${String(index + 1).padStart(2, "0")}</span><span>${types[q.type]}</span></div><div class="question-tools"><button type="button" data-action="up" data-index="${index}" ${index === 0 ? "disabled" : ""} aria-label="上移第 ${index + 1} 题">↑ 上移</button><button type="button" data-action="down" data-index="${index}" ${index === state.survey.questions.length - 1 ? "disabled" : ""} aria-label="下移第 ${index + 1} 题">↓ 下移</button><button type="button" class="delete" data-action="remove-question" data-index="${index}">删除</button></div></div><label class="field"><span>题目标题</span><input data-bind="${path}.title" maxlength="200" value="${esc(q.title)}" placeholder="写下你想问的问题"></label><div class="question-meta"><span class="question-type">${q.type.includes("choice") ? "选项设置" : "填写要求"}</span><label class="check"><input type="checkbox" data-bind="${path}.required" ${q.required ? "checked" : ""}>必答</label></div>${fields}<div class="logic-section"><div class="logic-title"><span>跳转设置</span>${q.type !== "text" && editable ? `<button type="button" class="button ghost small" data-action="add-rule" data-index="${index}">＋ 添加条件</button>` : ""}</div>${q.logic.rules.map((r, ri) => ruleCard(q, index, r, ri)).join("")}<label class="target-row"><span>${q.logic.rules.length ? "均不满足时" : "回答后"}</span><select data-bind="${path}.logic.default_target">${targetOptions(index, q.logic.default_target)}</select></label>${q.logic.rules.length > 1 ? '<p class="hint" style="margin-top:8px">多个条件满足时，使用从上到下第一个匹配项。</p>' : ""}</div></section>`;
}
function renderEditor() {
  state.page = "editor"; const s = state.survey, editable = s.status === "draft";
  const share = `${location.origin}${s.share_url}`;
  root.innerHTML = shell(`<button class="back" data-action="dashboard">← 返回我的问卷</button><header class="page-heading editor-head"><div><div class="eyebrow">QUESTIONNAIRE STUDIO</div><div class="editor-heading-title"><h1>${editable ? "编辑问卷" : "管理问卷"}</h1>${badge(s.effective_status)}</div><p class="save-label" id="save-label">${state.dirty ? "有未保存的修改" : `已保存 · ${new Date(s.updated_at).toLocaleString("zh-CN")}`}</p></div><div class="button-row"><button class="button secondary" data-action="preview">预览</button>${editable ? '<button class="button secondary" data-action="save">保存草稿</button><button class="button primary" data-action="publish">发布问卷 ↗</button>' : s.status === "published" ? '<button class="button danger" data-action="close">关闭问卷</button>' : ""}</div></header>${!editable ? `<div class="note editor-notice">${s.status === "closed" ? "这份问卷已关闭。" : "这份问卷已发布，题目与填写策略已固定。你可以复制链接或调整截止时间。"}</div>` : ""}<form id="editor-form"><div class="editor-layout"><div class="editor-main"><fieldset ${!editable ? "disabled" : ""}><section class="card"><div class="card-title"><h2>问卷信息</h2><span class="hint">让填写者了解这份问卷</span></div><label class="field"><span>问卷标题</span><input data-bind="title" maxlength="200" value="${esc(s.title)}" placeholder="例如：校园生活体验调查"></label><label class="field"><span>问卷说明</span><textarea data-bind="description" maxlength="2000" placeholder="简单介绍调查目的、填写时间等">${esc(s.description)}</textarea></label></section>${s.questions.map(questionCard).join("")}</fieldset>${editable ? `<section class="add-question"><p>继续添加你想了解的问题</p><div class="button-row">${Object.entries(types).map(([type, label]) => `<button type="button" class="button secondary small" data-action="add-question" data-type="${type}">＋ ${label}</button>`).join("")}</div></section>` : ""}</div><aside class="editor-aside"><section class="card settings-card"><h3>填写设置</h3><fieldset ${!editable ? "disabled" : ""}><label class="check"><input type="checkbox" data-bind="settings.allow_anonymous" ${s.settings.allow_anonymous ? "checked" : ""}>允许填写者选择匿名</label><label class="check"><input type="checkbox" data-bind="settings.allow_multiple_submissions" ${s.settings.allow_multiple_submissions ? "checked" : ""}>允许同一账号多次填写</label>${inputField("settings.expires_at", "截止时间", { type: "datetime-local" })}<p class="hint" style="margin-top:8px">留空表示不设截止时间</p></fieldset>${s.status === "published" ? `<hr><h3>调整截止时间</h3><label class="field"><span>新的截止时间</span><input type="datetime-local" id="new-deadline" value="${esc(localDate(s.settings.expires_at))}"></label><button type="button" class="button secondary wide" data-action="deadline" style="margin-top:12px">更新截止时间</button>` : ""}${!editable ? `<hr><h3>问卷链接</h3><div class="share-box"><label class="field"><span>访问地址</span><input readonly value="${esc(share)}" id="share-link"></label><button type="button" class="button secondary wide" data-action="copy" style="margin-top:10px">复制链接</button></div>` : '<div class="note">草稿可以随时保存。发布前请检查题目与跳转设置，发布后题目结构将固定。</div>'}<hr><p class="hint">共 ${s.questions.length} 道题目<br>填写者需先登录；选择匿名时，创建者看不到其身份。</p></section></aside></div></form>`);
  if (!editable) addResultsButton(root.querySelector(".editor-head > .button-row"), s.id, "查看结果");
}
function content() { const s = state.survey; return { title: s.title, description: s.description, settings: clone(s.settings), questions: clone(s.questions) }; }
async function saveDraft() {
  if (!$("#editor-form").reportValidity()) throw new Error("请检查数字或日期输入。");
  state.survey = await api(`/surveys/${state.survey.id}`, { method: "PUT", body: { ...content(), draft_revision: state.survey.draft_revision } });
  state.dirty = false;
}
function makeQuestion(type) {
  const q = { id: uid(), type, title: "", required: false, validation: {}, logic: { rules: [], default_target: "NEXT" } };
  if (type.includes("choice")) q.options = [{ id: uid(), label: "选项 1" }, { id: uid(), label: "选项 2" }];
  if (type === "number") q.validation.integer_only = false;
  return q;
}
function cleanTargets() {
  const ids = state.survey.questions.map((q) => q.id);
  state.survey.questions.forEach((q, i) => {
    const valid = (target) => ["NEXT", "END"].includes(target) || ids.indexOf(target) > i;
    q.logic.rules = q.logic.rules.filter((r) => valid(r.target));
    if (!valid(q.logic.default_target)) q.logic.default_target = "NEXT";
  });
}
function renderPreview(data, fromEditor = false) {
  state.page = "preview"; state.preview = { data, fromEditor };
  const cards = data.questions.map((q, i) => {
    let input;
    if (q.options) input = q.options.map((o) => `<label class="check"><input disabled type="${q.type === "single_choice" ? "radio" : "checkbox"}" name="preview-${i}">${esc(o.label || "未命名选项")}</label>`).join("");
    else input = q.type === "text" ? '<textarea class="input" disabled placeholder="填写你的回答" rows="3"></textarea>' : '<input class="input" type="number" disabled placeholder="填写数字">';
    const v = q.validation, hints = [];
    if (v.min_choices !== undefined) hints.push(`至少选 ${v.min_choices} 项`); if (v.max_choices !== undefined) hints.push(`最多选 ${v.max_choices} 项`);
    if (v.min_length !== undefined) hints.push(`至少 ${v.min_length} 字`); if (v.max_length !== undefined) hints.push(`最多 ${v.max_length} 字`);
    if (v.min_value !== undefined) hints.push(`最小值 ${v.min_value}`); if (v.max_value !== undefined) hints.push(`最大值 ${v.max_value}`); if (v.integer_only) hints.push("仅限整数");
    return `<section class="card preview-question"><h3>${i + 1}. ${esc(q.title || "未命名题目")}${q.required ? '<span class="required-star">*</span>' : ""}</h3>${input}${hints.length ? `<p class="hint">${hints.join(" · ")}</p>` : ""}</section>`;
  }).join("");
  root.innerHTML = `<main class="preview-wrap"><header class="preview-top">${brand()}<button class="button secondary small" data-action="${fromEditor ? "back-editor" : "dashboard"}">${fromEditor ? "返回编辑" : "我的问卷"}</button></header><div class="card preview-hero"><span class="badge">问卷预览</span><h1>${esc(data.title || "未命名问卷")}</h1><p>${esc(data.description || "感谢你了解这份问卷。")}</p></div><p class="note" style="margin-bottom:20px">当前为预览模式，不保存回答。实际填写请使用发布后的问卷链接。</p>${cards || '<div class="card empty"><p>还没有添加题目</p></div>'}<p class="hint" style="text-align:center">问卷工坊 · 让每个问题都有回响</p></main>`;
}
async function loadInitialView() {
  if (location.pathname.startsWith("/survey/")) {
    try { const code = location.pathname.split("/")[2]; startFilling(await api(`/public/surveys/${encodeURIComponent(code)}`), code); }
    catch (error) {
      if (error.status === 401) throw error;
      root.innerHTML = `<main class="preview-wrap"><header class="preview-top">${brand()}</header><section class="card preview-error"><h2>暂时无法查看问卷</h2><p>${esc(error.message)}</p><button class="button primary" data-action="dashboard">返回我的问卷</button></section></main>`;
    }
  } else await loadDashboard();
}
async function leaveEditor() {
  return !state.dirty || await confirmAction(state.page === "fill" ? "离开填写页面？" : "离开编辑页面？", "还有未提交或未保存的内容，离开后这些内容将丢失。", "确认离开");
}
root.addEventListener("submit", (event) => {
  event.preventDefault();
  if (event.target.id === "auth-form") run(async () => {
    const form = new FormData(event.target), password = form.get("password");
    if (state.mode === "register" && password !== form.get("confirm")) { $("#auth-error").textContent = "两次输入的密码不一致"; return; }
    try {
      state.user = await api(`/auth/${state.mode}`, { method: "POST", body: { username: form.get("username"), password } });
      state.dirty = false; await loadInitialView(); toast(state.mode === "register" ? "注册成功，欢迎来到问卷工坊" : "登录成功");
    } catch (error) { $("#auth-error").textContent = error.message; }
  });
  else if (event.target.id === "editor-form") run(async () => { await saveDraft(); renderEditor(); toast("草稿已保存"); });
  else if (event.target.id === "fill-form") run(async () => advanceFill());
});
function bindInput(event) {
  const node = event.target;
  if (node.dataset.ruleOperator) {
    if (event.type !== "change") return;
    const [i, r] = node.dataset.ruleOperator.split(",").map(Number);
    const condition = state.survey.questions[i].logic.rules[r].condition;
    condition.operator = node.value; condition.value = node.value === "between" ? [0, 0] : 0;
    markDirty(); renderEditor(); return;
  }
  const path = node.dataset.bind; if (!path || !state.survey || state.survey.status !== "draft") return;
  let value = node.value, remove = false;
  if (node.type === "checkbox") value = node.checked;
  else if (node.multiple) value = Array.from(node.selectedOptions, (o) => o.value);
  else if (node.type === "number") {
    remove = value === "" && path.includes(".validation.");
    value = value === "" ? null : Number(value);
  } else if (node.type === "datetime-local") value = value ? new Date(value).toISOString() : null;
  setPath(path, value, remove); markDirty();
}
root.addEventListener("input", bindInput); root.addEventListener("change", bindInput);
root.addEventListener("click", (event) => {
  const button = event.target.closest("[data-action]"); if (!button || button.disabled) return;
  const action = button.dataset.action;
  run(async () => {
    if (await handleAnswerAction(action, button)) return;
    if (action === "auth-mode") { state.mode = button.dataset.mode; renderAuth(); return; }
    if (action === "dashboard") { if (await leaveEditor()) { state.filter = ""; state.offset = 0; await loadDashboard(); } return; }
    if (action === "logout") {
      if (!await leaveEditor()) return;
      await api("/auth/logout", { method: "POST" }); state.user = null; state.survey = null; state.fill = null; state.results = null; state.dirty = false; state.mode = "login"; renderAuth(); return;
    }
    if (action === "filter") { state.filter = button.dataset.filter; state.offset = 0; await loadDashboard(); return; }
    if (action === "previous" || action === "next") { state.offset += action === "next" ? 12 : -12; await loadDashboard(); return; }
    if (action === "create") { state.survey = await api("/surveys", { method: "POST", body: {} }); state.dirty = false; renderEditor(); return; }
    if (action === "open") { state.survey = await api(`/surveys/${button.dataset.id}`); state.dirty = false; renderEditor(); return; }
    if (action === "save") { await saveDraft(); renderEditor(); toast("草稿已保存"); return; }
    if (action === "preview") { renderPreview(clone(state.survey), true); window.scrollTo(0, 0); return; }
    if (action === "back-editor") { renderEditor(); return; }
    if (action === "publish") {
      if (!await confirmAction("发布这份问卷？", "发布后题目、选项、跳转与填写策略将固定。请确认内容已检查完成。", "确认发布")) return;
      await saveDraft(); renderEditor();
      state.survey = await api(`/surveys/${state.survey.id}/publish`, { method: "POST", body: { draft_revision: state.survey.draft_revision } });
      renderEditor(); toast("问卷已发布，可以复制链接了"); return;
    }
    if (action === "close") {
      if (!await confirmAction("关闭这份问卷？", "关闭后访问链接将不再开放，这份问卷不能重新发布。", "关闭问卷")) return;
      state.survey = await api(`/surveys/${state.survey.id}/close`, { method: "POST" }); renderEditor(); toast("问卷已关闭"); return;
    }
    if (action === "deadline") {
      const value = $("#new-deadline").value;
      state.survey = await api(`/surveys/${state.survey.id}/deadline`, { method: "PATCH", body: { expires_at: value ? new Date(value).toISOString() : null } });
      renderEditor(); toast("截止时间已更新"); return;
    }
    if (action === "copy") {
      try { await navigator.clipboard.writeText(`${location.origin}${state.survey.share_url}`); toast("链接已复制"); }
      catch { $("#share-link").select(); toast("请复制已选中的问卷链接"); }
      return;
    }
    const index = Number(button.dataset.index), q = state.survey?.questions[index];
    if (action === "add-question") {
      if (state.survey.questions.length >= 200) throw new Error("最多添加 200 道题目");
      state.survey.questions.push(makeQuestion(button.dataset.type)); markDirty(); renderEditor();
      const card = $(`#question-${state.survey.questions.length - 1}`); card.scrollIntoView({ behavior: "smooth", block: "center" }); card.querySelector("input").focus({ preventScroll: true }); return;
    }
    if (action === "remove-question") { state.survey.questions.splice(index, 1); cleanTargets(); }
    else if (action === "up" || action === "down") { const next = index + (action === "up" ? -1 : 1); [state.survey.questions[index], state.survey.questions[next]] = [state.survey.questions[next], q]; cleanTargets(); }
    else if (action === "add-option") { if (q.options.length >= 50) throw new Error("每题最多添加 50 个选项"); q.options.push({ id: uid(), label: "" }); }
    else if (action === "remove-option") {
      const removed = q.options.splice(Number(button.dataset.option), 1)[0];
      q.logic.rules = q.logic.rules.filter((r) => {
        if (q.type === "single_choice") return r.condition.value !== removed.id;
        r.condition.value = r.condition.value.filter((v) => v !== removed.id); return r.condition.value.length;
      });
    } else if (action === "add-rule") {
      if (q.logic.rules.length >= 50) throw new Error("每题最多配置 50 条跳转条件");
      if (q.options && !q.options.length) throw new Error("请先添加选项");
      q.logic.rules.push({ id: uid(), condition: { operator: q.type === "multiple_choice" ? "contains_any" : "eq", value: q.type === "number" ? 0 : q.type === "multiple_choice" ? [q.options[0].id] : q.options[0].id }, target: "END" });
    } else if (action === "remove-rule") q.logic.rules.splice(Number(button.dataset.rule), 1);
    else return;
    markDirty(); renderEditor();
  });
});
window.addEventListener("beforeunload", (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });
installAnswerHandlers();
run(async () => {
  try { state.user = await api("/auth/me"); }
  catch (error) { if (error.status === 401) { renderAuth(); return; } throw error; }
  await loadInitialView();
});
