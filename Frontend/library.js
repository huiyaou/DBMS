"use strict";

function libraryButton(action, text, data = {}, style = 'secondary') {
  return `<button type="button" class="button ${style} small" data-action="${action}" ${Object.entries(data).map(([k,v]) => `data-${k}="${esc(v)}"`).join(' ')}>${text}</button>`;
}

function renderVersionManager(q) {
  const available=q.versions.filter(v=>!v.archived);
  state.selectedVersions ||= {};
  const selected=available.find(v=>v.id===state.selectedVersions[q.id]) || available.at(-1);
  if(selected) state.selectedVersions[q.id]=selected.id;
  else delete state.selectedVersions[q.id];
  const title=q.versions[0]?.content.title || '未命名题目';
  const versionName=id=>{const v=q.versions.find(v=>v.id===id);return v ? `V${v.number}` : '未知版本';};
  const validationLabels={min_choices:'最少选择数',max_choices:'最多选择数',min_length:'最短文本长度',max_length:'最长文本长度',min_value:'最小值',max_value:'最大值',integer_only:'仅允许整数'};
  const detail=selected ? `<section class="version-detail" aria-label="${versionName(selected.id)} 版本详情"><header class="version-detail-head"><div><span class="version-tag">${versionName(selected.id)}</span><h3>${esc(selected.content.title)}</h3></div><span class="version-status ${selected.archived?'archived':''}">${selected.archived?'已删除':'可使用'}</span></header><p class="hint">${types[selected.content.type]} · ${dateLabel(selected.created_at)} · ${selected.parent_id ? `基于 ${versionName(selected.parent_id)} 创建` : '初始版本'}</p><div class="version-content-preview">${selected.content.options ? `<h4>选项</h4><ol class="version-options">${selected.content.options.map(o=>`<li>${esc(o.label)}</li>`).join('')}</ol>` : `<p class="hint">${selected.content.type==='number'?'填写数值':'填写文本'}</p>`}<dl class="version-validation">${Object.entries(selected.content.validation).map(([k,v])=>`<div><dt>${validationLabels[k] || esc(k)}</dt><dd>${typeof v==='boolean'?(v?'是':'否'):esc(v)}</dd></div>`).join('')}</dl></div>${selected.archived ? '<p class="hint deleted-version-note">此版本已从可选列表删除，历史引用和已发布问卷保持原样。</p>' : `<div class="version-detail-actions">${libraryButton('library-use','加入问卷',{id:q.id,version:selected.id},'primary')}${libraryButton('version-edit','编辑为新版本',{id:q.id,version:selected.id})}${libraryButton('bank-add','加入题库',{id:q.id,version:selected.id})}${libraryButton('question-stats','统计',{id:q.id,version:selected.id})}${selected.can_delete ? libraryButton('version-delete','删除此版本',{id:q.id,version:selected.id},'danger') : ''}</div>`}</section>` : '<div class="library-empty">暂无可用版本</div>';
  return `<article class="card library-question" data-question-card="${q.id}"><header class="library-card-head"><div><span class="library-kicker">${q.is_owner?'我的题目':'共享题目'}</span><h2>${esc(title)}</h2><p class="hint">${available.length} 个可用版本</p></div><div class="button-row">${libraryButton('question-usage','使用情况',{id:q.id})}${q.is_owner?libraryButton('question-share','共享',{id:q.id})+libraryButton('question-delete','删除题目',{id:q.id},'danger'):''}</div></header><div class="version-manager"><nav class="version-rail" aria-label="${esc(title)}的版本列表"><div class="version-rail-label">版本记录</div><ol>${available.map(v=>`<li class="${v.archived?'archived':''}"><button type="button" class="version-select ${selected?.id===v.id?'active':''}" data-action="version-select" data-id="${q.id}" data-version="${v.id}" aria-pressed="${selected?.id===v.id}"><strong>V${v.number}</strong><span>${v.archived?'已删除':v.parent_id?`基于 ${versionName(v.parent_id)}`:'初始版本'}</span></button>${v.can_delete && !v.archived ? `<button type="button" class="version-rail-delete" data-action="version-delete" data-id="${q.id}" data-version="${v.id}" aria-label="删除 V${v.number}" title="删除 V${v.number}">删除</button>`:''}</li>`).join('')}</ol></nav>${detail}</div></article>`;
}

async function renderLibrary(tab = state.libraryTab || 'questions') {
  [state.library, state.banks] = await Promise.all([api('/questions'), api('/banks')]);
  state.libraryTab = tab; state.page = 'library'; state.questionDirty = false;
  const questions = state.library;
  const active = questions.flatMap(q => q.versions.filter(v => !v.archived));
  const rows = questions.map(renderVersionManager).join('');
  const banks = state.banks.map(b => `<article class="card library-bank"><header class="library-card-head"><div><span class="library-kicker">个人题库</span><h2>${esc(b.name)}</h2><p class="hint">${b.items.length} 道题目</p></div><div class="button-row">${libraryButton('bank-rename','重命名',{bank:b.id})}${libraryButton('bank-delete','删除题库',{bank:b.id},'danger')}</div></header>${b.items.map(i => {
    const q = questions.find(x=>x.id===i.question_id), v=q?.versions.find(x=>x.id===i.version_id);
    return `<div class="version-row"><div><h3>${esc(v?.content.title || '题目不可用')}</h3><p class="hint">${v ? `V${v.number} · ${types[v.content.type]}` : '请移除此条目'}</p></div><div class="button-row">${v && !v.archived ? libraryButton('library-use','加入问卷',{id:i.question_id,version:i.version_id},'primary')+libraryButton('bank-switch','切换版本',{bank:b.id,id:i.question_id}) : ''}${libraryButton('bank-remove','移除',{bank:b.id,id:i.question_id},'danger')}</div></div>`;
  }).join('') || '<p class="library-empty">题库还没有题目。在“题目”中选择一个版本，点击“加入题库”。</p>'}</article>`).join('');
  root.innerHTML = shell(`<header class="page-heading"><div><div class="eyebrow">QUESTION LIBRARY</div><h1>题目与题库</h1><p>管理常用题目，选择版本加入草稿或已发布问卷。</p></div><div class="button-row">${libraryButton('question-new','＋ 新建题目',{},'primary')}${libraryButton('bank-create','＋ 新建题库')}</div></header><div class="library-overview"><span><b>${questions.length}</b> 道题目</span><span><b>${active.length}</b> 个可用版本</span><span><b>${state.banks.length}</b> 个题库</span></div><div class="library-toolbar"><div class="filter-tabs"><button class="${tab==='questions'?'active':''}" data-action="library-tab" data-tab="questions">题目</button><button class="${tab==='banks'?'active':''}" data-action="library-tab" data-tab="banks">题库</button></div>${state.survey ? libraryButton('back-editor','返回当前问卷') : ''}</div><p class="hint library-help">编辑任意版本会生成新版本；已发布问卷中的原题始终保持原样。删除仅移出可选列表，历史引用继续保留。</p>${tab === 'banks' ? banks || '<div class="card library-empty">还没有题库，点击右上角新建题库。</div>' : rows || '<div class="card library-empty">还没有可用题目，点击右上角新建题目。</div>'}`);
}

function libraryDialog(title, body, submitText, callback) {
  document.querySelector('#library-dialog')?.remove();
  const dialog = document.createElement('dialog'); dialog.id='library-dialog'; dialog.className='library-dialog';
  dialog.innerHTML=`<form id="library-dialog-form"><header><h2>${esc(title)}</h2><button type="button" class="dialog-x" aria-label="关闭">×</button></header><div class="dialog-content">${body}</div><p class="error-inline" role="alert"></p><div class="dialog-actions"><button type="button" class="button secondary dialog-cancel">${submitText ? '取消' : '关闭'}</button>${submitText ? `<button class="button primary" type="submit">${esc(submitText)}</button>` : ''}</div></form>`;
  document.body.append(dialog);
  dialog.querySelector('.dialog-x').onclick=()=>dialog.close();
  dialog.querySelector('.dialog-cancel').onclick=()=>dialog.close();
  dialog.querySelector('form').onsubmit=async event=>{
    event.preventDefault();
    const button=dialog.querySelector('[type=submit]'); if (!button) return;
    button.disabled=true;
    try { await callback(new FormData(event.target)); dialog.close(); }
    catch(error) { dialog.querySelector('.error-inline').textContent=error.message; }
    finally { button.disabled=false; }
  };
  dialog.showModal();
}

function getLibraryVersion(button) {
  const question=state.library.find(q=>q.id===button.dataset.id);
  const version=question?.versions.find(v=>v.id===button.dataset.version);
  if (!version) throw new Error('题目版本不可用，请刷新列表');
  return {question,version};
}

function renderQuestionEditor(content, questionId=null, parentId=null) {
  state.page='library-editor';
  state.questionEdit={content:clone(content), questionId, parentId};
  const q=state.questionEdit.content;
  const v=q.validation;
  const field=(key,label)=>`<label class="field"><span>${label}</span><input type="number" step="${q.type==='number'?'any':'1'}" ${q.type==='number'?'':'min="0"'} name="${key}" value="${esc(v[key] ?? '')}"></label>`;
  root.innerHTML=shell(`<button class="back" data-action="library">← 返回题目库</button><header class="page-heading"><div><div class="eyebrow">QUESTION EDITOR</div><h1>${parentId ? '编辑为新版本' : '新建题目'}</h1><p>${parentId ? '保存后生成新版本，来源版本及已发布问卷保持原样。' : '保存后可以共享、加入题库或直接加入问卷。'}</p></div></header><form id="question-editor-form" class="card standalone-question"><label class="field question-title-field"><span>题目标题${parentId ? ' · 固定' : ''}</span><input name="title" required maxlength="200" value="${esc(q.title)}" ${parentId ? 'readonly aria-readonly="true"' : ''} placeholder="例如：你的年龄">${parentId ? '<small class="hint">同一道题的不同版本共用标题，只能修改题型、选项和校验条件。</small>' : ''}</label><label class="field"><span>题目类型</span><select id="question-editor-type" name="type">${Object.entries(types).map(([type,label])=>`<option value="${type}" ${q.type===type?'selected':''}>${label}</option>`).join('')}</select></label>${q.options ? `<div class="library-option-head"><h3>选项</h3>${libraryButton('question-editor-option-add','＋ 添加选项')}</div><div class="options-list">${q.options.map((o,i)=>`<div class="option-row"><span class="version-tag">${i+1}</span><input type="hidden" name="option-id" value="${esc(o.id)}"><input class="input" name="option-label" aria-label="选项 ${i+1}" maxlength="200" required value="${esc(o.label)}">${libraryButton('question-editor-option-remove','移除',{index:i},'ghost')}</div>`).join('')}</div>` : ''}<div class="validation-grid">${q.type==='multiple_choice'?field('min_choices','最少选择数')+field('max_choices','最多选择数'):q.type==='text'?field('min_length','最短文本长度')+field('max_length','最长文本长度'):q.type==='number'?field('min_value','最小值')+field('max_value','最大值'):''}</div>${q.type==='number'?`<label class="check"><input type="checkbox" name="integer_only" ${v.integer_only?'checked':''}>仅允许整数</label>`:''}<p class="hint library-help">必答、题目顺序和跳转规则在具体问卷中配置。</p><div class="button-row"><button type="submit" class="button primary">${parentId?'保存为新版本':'保存题目'}</button>${libraryButton('library','取消')}</div><p class="error-inline" id="question-editor-error" role="alert"></p></form>`);
}

document.addEventListener('input', event=>{
  if(event.target.closest('#question-editor-form')) state.questionDirty=true;
});

function readQuestionEditor() {
  const form=document.querySelector('#question-editor-form');
  const data=new FormData(form), old=state.questionEdit.content;
  const q={...clone(old), title:state.questionEdit.parentId ? old.title : data.get('title'), validation:{}};
  if (old.options) q.options=data.getAll('option-label').map((label,i)=>({id:data.getAll('option-id')[i],label}));
  const keys={single_choice:[],multiple_choice:['min_choices','max_choices'],text:['min_length','max_length'],number:['min_value','max_value']}[old.type];
  for (const key of keys) if (data.get(key)!=='') q.validation[key]=Number(data.get(key));
  if (old.type==='number') q.validation.integer_only=data.has('integer_only');
  return q;
}

document.addEventListener('change', event=>{
  if(event.target.id!=='question-editor-type') return;
  state.questionDirty=true;
  const old=readQuestionEditor(), edit=state.questionEdit;
  const q=makeQuestion(event.target.value); q.title=old.title;
  renderQuestionEditor(q,edit.questionId,edit.parentId);
});
document.addEventListener('submit', event=>{
  if(event.target.id!=='question-editor-form') return;
  event.preventDefault();
  run(async()=>{
    try {
      const {questionId,parentId}=state.questionEdit;
      await api(questionId?`/questions/${questionId}/versions`:'/questions',{method:'POST',body:{content:readQuestionEditor(),parent_id:parentId}});
      await renderLibrary('questions'); toast(parentId?'新版本已保存':'题目已创建');
    } catch(error) { const node=document.querySelector('#question-editor-error'); if(node) node.textContent=error.message; else throw error; }
  });
});

async function chooseSurvey(question,version) {
  const surveys=[]; let offset=0;
  while(true) {
    const page=await api(`/surveys?limit=100&offset=${offset}`); surveys.push(...page.items);
    offset+=page.items.length; if(offset>=page.total || !page.items.length) break;
  }
  const candidates=surveys.filter(s=>['draft','published'].includes(s.status));
  if(!candidates.length) throw new Error('还没有草稿或已发布问卷，请先新建问卷');
  libraryDialog('加入问卷',`<p class="hint">选择一份问卷。已发布问卷只追加新题，原有题目不可修改；同一题目的不同版本不能重复加入。</p><label class="field"><span>目标问卷</span><select name="survey_id" required>${candidates.map(s=>{const duplicate=s.questions.some(q=>q.source_question_id===question.id);return `<option value="${s.id}" ${duplicate?'disabled':''}>${esc(s.title || '未命名问卷')} · ${labels[s.effective_status]}${duplicate?'（已包含此题）':''}</option>`;}).join('')}</select></label>`, '确认加入', async data=>{
    const id=data.get('survey_id'); if(!id) throw new Error('没有可加入的问卷');
    if(state.survey?.id===id && state.dirty) throw new Error('当前问卷有未保存内容，请返回编辑页保存后再加入');
    const latest=await api(`/surveys/${id}`);
    const saved=await api(`/surveys/${id}/questions`,{method:'POST',body:{question_id:question.id,version_id:version.id,draft_revision:latest.draft_revision}});
    if(state.survey?.id===id) state.survey=saved;
    toast('题目已加入所选问卷');
  });
}

async function handleLibraryAction(action, button) {
  if(action==='library') {
    if(state.page==='library-editor' && state.questionDirty && !await confirmAction('放弃题目修改？','当前题目的修改尚未保存。','放弃修改')) return true;
    await renderLibrary(); return true;
  }
  if(action==='version-select') {
    state.selectedVersions ||= {}; state.selectedVersions[button.dataset.id]=button.dataset.version;
    const q=state.library.find(q=>q.id===button.dataset.id);
    root.querySelector(`[data-question-card="${q.id}"]`).outerHTML=renderVersionManager(q); return true;
  }
  if(action==='library-tab') { await renderLibrary(button.dataset.tab); return true; }
  if(action==='published-add') { await renderLibrary('questions'); return true; }
  if(action==='question-new') { renderQuestionEditor(makeQuestion('single_choice')); return true; }
  if(action==='version-edit') { const {question,version}=getLibraryVersion(button); renderQuestionEditor(version.content,question.id,version.id); return true; }
  if(action==='question-editor-option-add' || action==='question-editor-option-remove') {
    state.questionDirty=true;
    const q=readQuestionEditor(), edit=state.questionEdit;
    if(action.endsWith('-add')) { if(q.options.length>=50) throw new Error('最多 50 个选项'); q.options.push({id:uid(),label:''}); }
    else q.options.splice(Number(button.dataset.index),1);
    renderQuestionEditor(q,edit.questionId,edit.parentId); return true;
  }
  if(action==='library-use') { const {question,version}=getLibraryVersion(button); await chooseSurvey(question,version); return true; }
  if(action==='version-delete' || action==='question-delete') {
    const deletionText=action==='version-delete'?'此版本将不再提供选用，题库中使用此版本的条目会移除。草稿和已发布问卷中已复用的题目及答卷保持不变。':'题目将从常用题目列表中移除，所有题库中的对应条目也会移除。草稿和已发布问卷中已复用的题目及答卷保持不变。';
    if(!await confirmAction(action==='version-delete'?'删除这个版本？':'删除这道常用题目？',deletionText,'删除')) return true;
    await api(`/questions/${button.dataset.id}${action==='version-delete'?`/versions/${button.dataset.version}`:''}`,{method:'DELETE'});
    await renderLibrary(); toast('已删除'); return true;
  }
  if(action==='bank-create' || action==='bank-rename') {
    const bank=state.banks?.find(b=>b.id===button.dataset.bank);
    libraryDialog(bank?'重命名题库':'新建题库',`<label class="field"><span>题库名称</span><input name="name" required maxlength="200" value="${esc(bank?.name || '')}" placeholder="例如：校园调查常用题"></label>`,'保存',async data=>{
      await api(bank?`/banks/${bank.id}`:'/banks',{method:bank?'PATCH':'POST',body:{name:data.get('name')}}); await renderLibrary('banks');
    }); return true;
  }
  if(action==='bank-delete') { if(await confirmAction('删除这个题库？','移除题库和其中的条目，题目及已发布问卷继续保留。','删除')) {await api(`/banks/${button.dataset.bank}`,{method:'DELETE'});await renderLibrary('banks');} return true; }
  if(action==='bank-remove') { await api(`/banks/${button.dataset.bank}/items/${button.dataset.id}`,{method:'DELETE'}); await renderLibrary('banks');return true; }
  if(action==='bank-add') {
    const {question,version}=getLibraryVersion(button);
    if(!state.banks.length) throw new Error('请先新建一个题库');
    libraryDialog('加入题库',`<label class="field"><span>目标题库</span><select name="bank">${state.banks.map(b=>`<option value="${b.id}">${esc(b.name)}</option>`).join('')}</select></label><p class="hint">同一道题再次加入时，将切换该题库选定的版本。</p>`,'加入',async data=>{await api(`/banks/${data.get('bank')}/items`,{method:'PUT',body:{question_id:question.id,version_id:version.id}});await renderLibrary();toast('已加入题库');}); return true;
  }
  if(action==='bank-switch') {
    const q=state.library.find(q=>q.id===button.dataset.id);
    libraryDialog('切换题库版本',`<label class="field"><span>选择版本</span><select name="version">${q.versions.filter(v=>!v.archived).map(v=>`<option value="${v.id}">V${v.number} · ${esc(v.content.title)}</option>`).join('')}</select></label>`,'切换',async data=>{await api(`/banks/${button.dataset.bank}/items`,{method:'PUT',body:{question_id:q.id,version_id:data.get('version')}});await renderLibrary('banks');});return true;
  }
  if(action==='question-share') {
    libraryDialog('共享题目', '<label class="field"><span>对方用户名</span><input name="username" required maxlength="64" placeholder="输入已注册用户的用户名"></label><p class="hint">对方可以选用题目或创建新版本；问卷和答卷不会一并共享。</p>', '共享', async data=>{await api(`/questions/${button.dataset.id}/share`,{method:'POST',body:{username:data.get('username')}});toast('已共享');});return true;
  }
  if(action==='question-usage') {
    const items=await api(`/questions/${button.dataset.id}/usage`);
    libraryDialog('题目使用情况',`<p class="hint">显示你拥有的问卷。</p>${items.map(s=>`<div class="usage-row"><b>${esc(s.title || '未命名问卷')}</b>${badge(s.status)}</div>`).join('') || '<p>尚未使用此题。</p>'}`,null);return true;
  }
  if(action==='question-stats') {
    const x=await api(`/questions/${button.dataset.id}/versions/${button.dataset.version}/statistics`);
    libraryDialog('版本统计',`<p class="hint">统计范围：你拥有且引用此版本的 ${x.survey_count} 份问卷。</p><div class="library-overview"><span><b>${x.answered_count}</b> 次有效回答</span><span><b>${x.participant_count}</b> 位参与者</span></div>${x.options.map(o=>`<div class="usage-row"><span>${esc(o.label)}</span><b>${o.count} 次</b></div>`).join('')}${x.type==='number'?`<p>平均值：<b>${x.average ?? '暂无'}</b></p>`:''}${x.answers.length?`<div class="stat-values">${x.answers.map(a=>`<span>${esc(a)}</span>`).join('')}</div>`:''}${!x.answered_count?'<p>暂无回答。</p>':''}`,null);return true;
  }
  return false;
}
