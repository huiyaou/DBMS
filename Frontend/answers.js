"use strict";

// 实际填写与统计界面。通用账号和问卷编辑逻辑继续由 app.js 提供。
function startFilling(survey, code) {
  state.fill = { survey, code, answers: {}, path: survey.questions.length ? [survey.questions[0].id] : [], index: 0, attempt_id: uid(), is_anonymous: false, stage: survey.can_submit ? "question" : "done", receipt: null };
  state.survey = null; state.page = "fill"; state.dirty = false;
  renderFill();
}
function fillQuestion() {
  return state.fill.survey.questions.find(q => q.id === state.fill.path[state.fill.index]);
}
function fillHints(q) {
  const v = q.validation, hints = [];
  for (const [key, label] of [["min_choices", "至少选择"], ["max_choices", "最多选择"], ["min_length", "最少字数"], ["max_length", "最多字数"], ["min_value", "最小值"], ["max_value", "最大值"]]) if (v[key] !== undefined) hints.push(`${label} ${v[key]}`);
  if (v.integer_only) hints.push("仅限整数");
  return hints.join(" · ");
}
function fillValueLabel(q, value) {
  if (value === undefined) return "未填写";
  if (q.options) {
    const values = Array.isArray(value) ? value : [value];
    return values.map(id => q.options.find(o => o.id === id)?.label ?? id).join("、");
  }
  return String(value);
}
function renderFill() {
  state.page = "fill";
  const f = state.fill, survey = f.survey;
  const header = `<header class="preview-top">${brand()}<button class="button secondary small" data-action="dashboard">我的问卷</button></header>`;
  let body;
  if (f.stage === "done") {
    body = `<section class="card submission-success"><div class="success-symbol" aria-hidden="true">✓</div><h1>${f.receipt ? "提交成功，感谢你的参与" : "你已经填写过这份问卷"}</h1><p>${esc(survey.title)}</p><p class="hint">${f.receipt ? `提交时间：${new Date(f.receipt.submitted_at).toLocaleString("zh-CN")}` : "这份问卷每个账号只能提交一次，你的填写记录已保存。"}</p><div class="button-row">${survey.settings.allow_multiple_submissions ? '<button class="button primary" data-action="fill-again">再次填写</button>' : ""}<button class="button secondary" data-action="dashboard">返回我的问卷</button></div></section>`;
  } else if (f.stage === "review") {
    const rows = f.path.map((id, i) => { const q = survey.questions.find(q => q.id === id); return `<div class="review-row"><h3>${i + 1}. ${esc(q.title)}</h3><p>${esc(fillValueLabel(q, f.answers[id]))}</p></div>`; }).join("");
    body = `<section class="card preview-hero"><div class="eyebrow">READY TO SUBMIT</div><h1>检查你的回答</h1><p>${esc(survey.title)} · 实际经过 ${f.path.length} 道题目</p></section><section class="card">${rows}</section><section class="card">${survey.settings.allow_anonymous ? `<label class="check"><input id="fill-anonymous" type="checkbox" ${f.is_anonymous ? "checked" : ""}>匿名提交，不向创建者展示我的身份</label><p class="hint" style="margin-top:10px">系统仍使用登录账号控制填写次数。请避免在回答中主动填写不想公开的个人信息。</p>` : `<p class="hint">本次以账号 ${esc(state.user.username)} 实名提交。</p>`}<div class="fill-actions"><button class="button secondary" data-action="fill-back-review">返回修改</button><button class="button primary" data-action="fill-submit">确认提交</button></div></section>`;
  } else {
    const q = fillQuestion(), value = f.answers[q.id];
    const number = survey.questions.findIndex(item => item.id === q.id) + 1;
    let input;
    if (q.options) input = `<div class="fill-options">${q.options.map(o => `<label class="fill-option"><input name="fill-answer" type="${q.type === "single_choice" ? "radio" : "checkbox"}" value="${esc(o.id)}" ${(Array.isArray(value) ? value.includes(o.id) : value === o.id) ? "checked" : ""}><span>${esc(o.label)}</span></label>`).join("")}</div>`;
    else input = q.type === "text" ? `<label class="field"><span>你的回答</span><textarea id="fill-answer" maxlength="100000" rows="5" placeholder="请输入你的回答">${esc(value)}</textarea></label>` : `<label class="field"><span>你的回答</span><input id="fill-answer" type="number" step="${q.validation.integer_only ? "1" : "any"}" value="${esc(value)}" placeholder="请输入数字"></label>`;
    body = `<section class="card preview-hero"><span class="badge published">正在填写</span><h1>${esc(survey.title)}</h1><p>${esc(survey.description)}</p>${survey.has_submitted && survey.settings.allow_multiple_submissions ? '<p class="hint" style="margin-top:10px">你已提交过回答，这份问卷允许再次填写。</p>' : ""}</section><form id="fill-form" novalidate><section class="card fill-card"><div class="fill-step"><span>第 ${number} 题 / 共 ${survey.questions.length} 题</span><span>${types[q.type]}</span></div><div class="fill-progress"><span style="width:${number / survey.questions.length * 100}%"></span></div><h2>${esc(q.title)}${q.required ? '<span class="required-star">*</span>' : ""}</h2>${input}${fillHints(q) ? `<p class="hint" style="margin-top:14px">${esc(fillHints(q))}</p>` : ""}<p id="fill-error" class="error-inline fill-error" role="alert" tabindex="-1"></p><div class="fill-actions"><button class="button secondary" type="button" data-action="fill-previous" ${f.index === 0 ? "disabled" : ""}>上一题</button><button class="button primary" type="submit">下一步 →</button></div></section><p class="hint" style="text-align:center">根据你的回答，部分题目可能会自动跳过。提交后才会保存填写记录。</p></form>`;
  }
  root.innerHTML = `<main class="preview-wrap">${header}${body}</main>`;
}
function captureFillValue() {
  const q = fillQuestion();
  if (q.options) {
    const values = Array.from(document.querySelectorAll('input[name="fill-answer"]:checked'), node => node.value);
    return q.type === "single_choice" ? values[0] : values.length ? values : undefined;
  }
  const input = $("#fill-answer");
  if (q.type === "number") return input.value === "" ? undefined : input.valueAsNumber;
  return input.value.trim() || undefined;
}
function checkFillValue(q, value) {
  const v = q.validation;
  if (q.type === "number" && $("#fill-answer")?.validity.badInput) return "请输入有效数字";
  if (value === undefined) return q.required ? "此题为必答题，请先填写" : "";
  if (q.type === "multiple_choice") {
    const min = Math.max(v.min_choices ?? 0, q.required ? 1 : 0);
    if (value.length < min) return `至少选择 ${min} 项`;
    if (v.max_choices !== undefined && value.length > v.max_choices) return `最多选择 ${v.max_choices} 项`;
  }
  if (q.type === "text") {
    const length = Array.from(value).length;
    if (length < (v.min_length ?? 0)) return `至少输入 ${v.min_length} 字`;
    if (length > (v.max_length ?? 100000)) return `最多输入 ${v.max_length ?? 100000} 字`;
  }
  if (q.type === "number") {
    if (!Number.isFinite(value) || Math.abs(value) > Number.MAX_SAFE_INTEGER) return "请输入可准确表示的有限数值";
    if (v.integer_only && !Number.isInteger(value)) return "必须输入整数";
    if (v.min_value !== undefined && value < v.min_value) return `不能小于 ${v.min_value}`;
    if (v.max_value !== undefined && value > v.max_value) return `不能大于 ${v.max_value}`;
  }
  return "";
}
function fillCondition(condition, value) {
  const x = condition.value;
  switch (condition.operator) {
    case "eq": return value === x;
    case "gt": return value > x;
    case "gte": return value >= x;
    case "lt": return value < x;
    case "lte": return value <= x;
    case "between": return value >= x[0] && value <= x[1];
    case "contains_any": return x.some(id => value.includes(id));
    case "contains_all": return x.every(id => value.includes(id));
    case "equals_set": return value.length === x.length && x.every(id => value.includes(id));
    default: return false;
  }
}
function storeFillValue(value) {
  const id = fillQuestion().id;
  if (value === undefined) delete state.fill.answers[id]; else state.fill.answers[id] = value;
}
function advanceFill() {
  const f = state.fill, q = fillQuestion(), value = captureFillValue();
  const message = checkFillValue(q, value);
  if (message) { $("#fill-error").textContent = message; $("#fill-error").focus(); return; }
  storeFillValue(value); state.dirty = true;
  let target = q.logic.default_target;
  if (value !== undefined) target = q.logic.rules.find(rule => fillCondition(rule.condition, value))?.target ?? target;
  const position = f.survey.questions.findIndex(item => item.id === q.id);
  const next = target === "END" ? null : target === "NEXT" ? f.survey.questions[position + 1]?.id : target;
  if (!next) { f.path = f.path.slice(0, f.index + 1); f.stage = "review"; }
  else {
    if (f.path[f.index + 1] !== next) f.path = [...f.path.slice(0, f.index + 1), next];
    f.index += 1;
  }
  for (const id of Object.keys(f.answers)) if (!f.path.includes(id)) delete f.answers[id];
  renderFill(); window.scrollTo(0, 0);
}

async function loadResults(id) {
  const [survey, statistics, records] = await Promise.all([api(`/surveys/${id}`), api(`/surveys/${id}/statistics`), api(`/surveys/${id}/responses`)]);
  state.results = { survey, statistics, records, selected: "", question: null };
  state.page = "results"; state.survey = survey; state.dirty = false;
  renderResults(); window.scrollTo(0, 0);
}
function statisticCard(q, number) {
  const countText = `${q.answered_count} 份回答 · ${q.participant_count} 人`;
  let body;
  if (q.options.length) body = q.options.map(o => `<div class="result-option"><div><span>${esc(o.label)}</span><span>${o.count} 次${q.type === "single_choice" ? ` · ${o.people_count} 人` : ""}</span></div><div class="result-bar"><span style="width:${q.answered_count ? o.count / q.answered_count * 100 : 0}%"></span></div></div>`).join("");
  else {
    const average = q.type === "number" ? `<div class="average"><span>平均值</span><strong>${q.average === null ? "暂无数据" : Number(q.average).toLocaleString("zh-CN", {maximumFractionDigits: 4})}</strong></div>` : "";
    body = `${average}${q.answers.length ? `<div class="answer-values">${q.answers.map(a => `<div><p>${esc(a.value)}</p><span>${new Date(a.submitted_at).toLocaleString("zh-CN")}</span></div>`).join("")}</div>` : '<p class="hint">还没有人回答这道题。</p>'}`;
    if (q.answered_count > q.limit || q.offset) body += `<div class="answer-pager"><span>${q.offset + 1}–${q.offset + q.answers.length} / ${q.answered_count}</span>${state.results.selected ? `<div class="button-row"><button class="button ghost small" data-action="question-prev" ${q.offset === 0 ? "disabled" : ""}>上一组</button><button class="button ghost small" data-action="question-next" ${q.offset + q.limit >= q.answered_count ? "disabled" : ""}>下一组</button></div>` : `<button class="button ghost small" data-action="question-detail" data-question="${esc(q.question_id)}">查看全部内容 →</button>`}</div>`;
  }
  return `<section class="card statistic-card"><div class="card-title"><h2>${number}. ${esc(q.title)}</h2><span class="badge">${types[q.type]}</span></div><p class="hint">${countText}</p>${body}</section>`;
}
function renderResults() {
  state.page = "results";
  const r = state.results, s = r.survey, stats = r.statistics;
  const questions = r.selected ? [r.question] : stats.questions;
  const rows = r.records.items.map(record => `<details class="response-record"><summary><span>${esc(record.respondent_name)}${record.is_anonymous ? ' <span class="badge">匿名</span>' : ""}</span><span>${new Date(record.submitted_at).toLocaleString("zh-CN")} · 展开回答</span></summary><div>${record.answers.map(a => { const q = s.questions.find(q => q.id === a.question_id); return `<div class="record-answer"><h3>${esc(q?.title || "题目")}</h3><p>${esc(q ? fillValueLabel(q, a.value) : a.value)}</p></div>`; }).join("")}</div></details>`).join("");
  root.innerHTML = shell(`<button class="back" data-action="dashboard">← 返回我的问卷</button><header class="page-heading"><div><div class="eyebrow">RESPONSES & INSIGHTS</div><h1>问卷结果</h1><p>${esc(s.title || "未命名问卷")}</p></div><div class="button-row"><button class="button secondary" data-action="open" data-id="${s.id}">管理问卷</button><button class="button primary" data-action="refresh-results">刷新结果</button></div></header><section class="summary-grid results-summary"><div class="summary"><span>提交份数</span><strong>${stats.response_count}</strong></div><div class="summary"><span>参与人数</span><strong>${stats.participant_count}</strong></div><div class="summary"><span>题目数量</span><strong>${s.questions.length}</strong></div></section><p class="note results-note">每次有效填写计为一份回答，参与人数按账号去重。被跳过或未回答的题目不计入该题统计；允许多次填写时，同一人可能产生多份回答。</p><div class="results-filter"><h2>题目统计</h2><label class="field"><span>查看范围</span><select id="results-question"><option value="">整个问卷</option>${s.questions.map((q, i) => `<option value="${esc(q.id)}" ${r.selected === q.id ? "selected" : ""}>第 ${i + 1} 题 · ${esc(q.title)}</option>`).join("")}</select></label></div>${questions.map(q => statisticCard(q, s.questions.findIndex(item => item.id === q.question_id) + 1)).join("") || '<div class="card"><p class="hint">问卷还没有题目。</p></div>'}<section class="card response-records"><div class="card-title"><h2>填写记录</h2><span class="hint">共 ${r.records.total} 份</span></div>${rows || '<p class="hint">分享问卷链接后，收到的回答会显示在这里。</p>'}<div class="answer-pager"><span>${r.records.total ? `${r.records.offset + 1}–${r.records.offset + r.records.items.length} / ${r.records.total}` : "暂无记录"}</span><div class="button-row"><button class="button ghost small" data-action="records-prev" ${r.records.offset === 0 ? "disabled" : ""}>上一页</button><button class="button ghost small" data-action="records-next" ${r.records.offset + r.records.limit >= r.records.total ? "disabled" : ""}>下一页</button></div></div></section>`);
}
async function chooseResultQuestion(id, offset = 0) {
  const r = state.results;
  if (!id) { r.selected = ""; r.question = null; }
  else {
    r.question = await api(`/surveys/${r.survey.id}/statistics/${encodeURIComponent(id)}?offset=${offset}&limit=20`);
    r.selected = id;
  }
  renderResults();
}
async function handleAnswerAction(action, button) {
  if (action === "results") { await loadResults(button.dataset.id); return true; }
  if (action === "refresh-results") { await loadResults(state.results.survey.id); toast("结果已更新"); return true; }
  if (action === "question-detail") { await chooseResultQuestion(button.dataset.question); return true; }
  if (action === "question-prev" || action === "question-next") { const q = state.results.question; await chooseResultQuestion(q.question_id, Math.max(0, q.offset + (action === "question-next" ? q.limit : -q.limit))); return true; }
  if (action === "records-prev" || action === "records-next") {
    const r = state.results, offset = Math.max(0, r.records.offset + (action === "records-next" ? r.records.limit : -r.records.limit));
    r.records = await api(`/surveys/${r.survey.id}/responses?offset=${offset}&limit=${r.records.limit}`); renderResults(); return true;
  }
  if (action === "fill-previous") { storeFillValue(captureFillValue()); state.fill.index -= 1; renderFill(); window.scrollTo(0, 0); return true; }
  if (action === "fill-back-review") { state.fill.stage = "question"; renderFill(); return true; }
  if (action === "fill-again") { startFilling({...state.fill.survey, can_submit: true, has_submitted: true}, state.fill.code); return true; }
  if (action === "fill-submit") {
    const f = state.fill;
    f.is_anonymous = $("#fill-anonymous")?.checked ?? false;
    const answers = Object.entries(f.answers).map(([question_id, value]) => ({ question_id, value }));
    f.receipt = await api(`/public/surveys/${encodeURIComponent(f.code)}/responses`, {method: "POST", body: {attempt_id: f.attempt_id, is_anonymous: f.is_anonymous, answers}});
    state.dirty = false; f.stage = "done"; renderFill(); window.scrollTo(0, 0); return true;
  }
  return false;
}
function installAnswerHandlers() {
  root.addEventListener("input", event => { if (state.page === "fill" && event.target.closest("#fill-form")) state.dirty = true; });
  root.addEventListener("change", event => {
    if (event.target.id === "results-question") run(() => chooseResultQuestion(event.target.value));
    if (event.target.id === "fill-anonymous") state.fill.is_anonymous = event.target.checked;
  });
}

function addResultsButton(container, surveyId, label = "结果") {
  const button = document.createElement("button");
  button.type = "button"; button.className = "button secondary small";
  button.dataset.action = "results"; button.dataset.id = surveyId;
  button.textContent = label; container.prepend(button);
}
