"use strict";
/* 隐盾前端逻辑（Apple / iOS 风格）
   原则：组件退居次要，注意力留给对话本身。
   高频操作（上传、发送、任务）直接可达；低频与破坏性操作需折叠或二次确认。

   ── 本轮改版的两个人机问题 ──
   ① 任务只有一个 3 项下拉框（会议/活动/对外），名字宏大、无法判断该选哪个。
      → 换成「具体意图选择器」：12 个说人话的选项，分 3 组，带一句场景示例，
        可搜索，键盘全可达。选项来自 intents.js，仍映射到后端的 3 个模板键。
   ② 「高级设置」折叠在侧栏里，用户不知道里面有东西。
      → 拆开：身份是决定能读哪些材料的关键设置，直接常驻显示；
        额外处理要求用「一行按钮原地展开」，填了会显示摘要。
   ── 组件契约 ──
   · 选择器是「控件层」，因此可以是玻璃；对话区仍是内容层，保持实色。
   · 每个可点元素 ≥44px（--tap），键盘可达，ARIA 用 listbox/option 语义。 */

const el = id => document.getElementById(id);
let sessionId = null, files = [], library = [], busy = false, ready = false, localReady = false;

const MAX_TURNS = 20;

/* 顶层状态：本次对话的任务意图（intents.js 里的 id）与身份键 */
let currentIntentId = null;
let currentIdentity = null;
let configTasks = {};       /* 后端模板键 → {name, desc} */
let configIdentities = {};  /* 身份键 → {name, desc} */

const actionNames = {
  DELETE: '删除敏感值', LOCAL_AGGREGATE: '本地汇总', GENERALIZE: '降低精度',
  PSEUDONYMIZE: '替换为代号', RETAIN: '受控保留', PAUSE: '暂停发送'
};

const SHIELD_SVG =
  '<svg viewBox="0 0 40 40" width="44" height="44" aria-hidden="true">' +
  '<path d="M20 3.4 L33 8.9 V19.1 C33 26.8 27.3 32.7 20 36 C12.7 32.7 7 26.8 7 19.1 V8.9 Z" ' +
  'fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>' +
  '<path d="M20 12.2 L26 14.5 V19.2 C26 23.1 23 26.3 20 27.9 C17 26.3 14 23.1 14 19.2 V14.5 Z" ' +
  'fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" opacity=".65"/>' +
  '<circle cx="20" cy="20" r="1.9" fill="currentColor"/></svg>';

const CHIP_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" fill="none" ' +
  'stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M4 7h16M4 12h10M4 17h13"/></svg>';

const ARROW_ICON =
  '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" fill="none" ' +
  'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5.5 15.5 12 9 18.5"/></svg>';

const CHECK_ICON =
  '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true" fill="none" ' +
  'stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M3.2 8.4 6.4 11.6 12.8 4.8"/></svg>';

const SEARCH_ICON =
  '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" fill="none" ' +
  'stroke="currentColor" stroke-width="1.9" stroke-linecap="round">' +
  '<circle cx="10.6" cy="10.6" r="6.1"/><path d="M15.2 15.2 20 20"/></svg>';

/* ---------------- 状态与提示 ---------------- */
function notice(message, error = false) {
  const box = el('notice');
  box.textContent = message;
  box.classList.toggle('error', error);
  box.hidden = false;            /* 只在有话说时出现，见 index.html 注释 */
}

function setApiStatus(text, tone = 'default') {
  el('apiStatus').textContent = text;
  el('apiStatus').className = 'service-status' + (tone === 'default' ? '' : ' ' + tone);
}

function setModelStatus(health) {
  const ok = health.ready_local;
  const box = el('modelStatus');
  box.className = 'model-status' + (ok ? ' is-ok' : ' is-error');
  box.replaceChildren();
  const text = document.createElement('span');
  text.className = 'model-status-text';
  text.textContent = ok ? `本地处理已就绪（${health.detectors.join(' + ')}）`
    : '本地模型或识别器不可用，请检查模型配置后重启';
  box.append(text);
  if (ok) {
    const badge = document.createElement('span');
    badge.className = 'badge-local';
    badge.textContent = '本地运行';
    box.append(badge);
  }
}

/* 输入框高度随内容自适应（胶囊保持圆润） */
function autoGrow() {
  const ta = el('message');
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 132) + 'px';
}

/* 是否已有可发送内容 */
function syncSendState() {
  const has = el('message').value.trim().length > 0 || files.length > 0;
  el('send').disabled = !ready || !localReady || busy || !has;
}

/* ---------------- 通用：Pull-down 选择器（Apple HIG） ----------------
   为什么不用原生 <select>：原生下拉无法在选择时展示「一句场景示例」，
   而这正是用户判断「该选哪一个」的依据。因此自建 popover：
   · 触发按钮显示当前值与示例，popover 里分组 + 搜索 + 勾选态
   · 键盘：↑↓ 移动、Home/End、Enter/Space 选中、Esc 关闭、输入即搜索
   · popover 是控件层 → 允许玻璃；挂到 body 上以免被侧栏滚动容器裁切
   ------------------------------------------------------------------ */
function createPicker(spec) {
  const trigger = spec.trigger;
  const pop = spec.pop;
  const wrap = spec.wrap;
  let activeIndex = -1;
  let visible = [];              /* 当前渲染出来的可选项，顺序即键盘顺序 */

  document.body.append(pop);     /* 脱离 .config-body 的 overflow 裁切 */

  function place() {
    const r = trigger.getBoundingClientRect();
    const gap = 7, edge = 12;
    const room = Math.min(window.innerWidth - edge * 2, 420);
    const width = Math.max(Math.min(r.width, room), Math.min(272, room));
    pop.style.width = width + 'px';
    pop.style.left = Math.max(edge, Math.min(r.left, window.innerWidth - width - edge)) + 'px';
    const below = window.innerHeight - r.bottom - gap - edge;
    const above = r.top - gap - edge;
    const up = below < 240 && above > below;
    pop.classList.toggle('is-up', up);
    pop.style.maxHeight = Math.max(168, Math.min(up ? above : below, 460)) + 'px';
    if (up) { pop.style.top = 'auto'; pop.style.bottom = (window.innerHeight - r.top + gap) + 'px'; }
    else { pop.style.top = (r.bottom + gap) + 'px'; pop.style.bottom = 'auto'; }
  }

  function optionButton(item) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'picker-option' + (item.value === spec.selected() ? ' is-selected' : '');
    btn.setAttribute('role', 'option');
    btn.setAttribute('aria-selected', String(item.value === spec.selected()));
    btn.dataset.value = item.value;

    const check = document.createElement('span');
    check.className = 'picker-check'; check.innerHTML = CHECK_ICON;

    const text = document.createElement('span'); text.className = 'picker-opt-text';
    const name = document.createElement('span'); name.className = 'picker-opt-name';
    name.textContent = item.label;
    text.append(name);
    if (item.desc) {
      const desc = document.createElement('span'); desc.className = 'picker-opt-desc';
      desc.textContent = item.desc;
      text.append(desc);
    }
    if (item.meta) {
      const meta = document.createElement('span'); meta.className = 'picker-opt-meta';
      meta.textContent = item.meta;
      text.append(meta);
    }
    btn.append(check, text);
    btn.onclick = () => { close(true); spec.onPick(item.value); };
    return btn;
  }

  function renderList() {
    const list = pop.querySelector('.picker-list');
    const empty = pop.querySelector('.picker-empty');
    list.replaceChildren();
    visible = [];
    const query = pop.querySelector('.picker-search input');
    const sections = spec.sections(query ? query.value : '');
    for (const section of sections) {
      if (section.group) {
        const label = document.createElement('div');
        label.className = 'picker-group';
        label.setAttribute('role', 'presentation');
        label.textContent = section.group;
        list.append(label);
      }
      for (const item of section.items) {
        const btn = optionButton(item);
        list.append(btn);
        visible.push(btn);
      }
    }
    const none = !visible.length;
    empty.hidden = !none;
    activeIndex = -1;
    if (!none) {
      const sel = visible.findIndex(b => b.dataset.value === spec.selected());
      setActive(sel >= 0 ? sel : 0, false);
    }
  }

  /* 高亮并（当焦点已在选项之间时）真正移交 DOM 焦点，
     否则会出现「高亮在第 3 项、焦点还在第 1 项、回车选中第 1 项」的不一致。 */
  function setActive(index, scroll = true) {
    if (!visible.length) return;
    activeIndex = (index + visible.length) % visible.length;
    visible.forEach((b, i) => b.classList.toggle('is-active', i === activeIndex));
    if (scroll) visible[activeIndex].scrollIntoView({ block: 'nearest' });
    const focused = document.activeElement;
    if (focused && focused.classList && focused.classList.contains('picker-option')) {
      visible[activeIndex].focus();
    }
  }

  function build() {
    pop.replaceChildren();
    if (spec.search) {
      const box = document.createElement('div');
      box.className = 'picker-search';
      const ico = document.createElement('span');
      ico.className = 'picker-search-ico'; ico.innerHTML = SEARCH_ICON;
      const input = document.createElement('input');
      input.type = 'text';
      input.placeholder = spec.searchPlaceholder || '搜索';
      input.setAttribute('aria-label', spec.searchPlaceholder || '搜索');
      input.autocomplete = 'off';
      input.oninput = () => renderList();
      input.onkeydown = onSearchKey;
      /* 整行都可点：点放大镜图标或行内空白也应聚焦输入框。
         这样有效点按区域是整行（46px ≥ 44），而不只是输入框本身。 */
      box.onclick = () => input.focus();
      box.append(ico, input);
      pop.append(box);
    }
    const list = document.createElement('div');
    list.className = 'picker-list';
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', spec.listLabel);
    list.onkeydown = onListKey;
    const empty = document.createElement('div');
    empty.className = 'picker-empty';
    empty.textContent = spec.emptyText || '没有匹配的选项';
    empty.hidden = true;
    pop.append(list, empty);
  }

  function onListKey(event) {
    const key = event.key;
    if (key === 'ArrowDown') { event.preventDefault(); setActive(activeIndex + 1); }
    else if (key === 'ArrowUp') { event.preventDefault(); setActive(activeIndex - 1); }
    else if (key === 'Home') { event.preventDefault(); setActive(0); }
    else if (key === 'End') { event.preventDefault(); setActive(visible.length - 1); }
    else if (key === 'Escape') { event.preventDefault(); close(true); }
    else if (key === 'Tab') { close(false); }
  }

  function onSearchKey(event) {
    if (event.key === 'ArrowDown') { event.preventDefault(); setActive(0); visible[0] && visible[0].focus(); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); setActive(visible.length - 1); visible[visible.length - 1] && visible[visible.length - 1].focus(); }
    else if (event.key === 'Enter') { event.preventDefault(); if (visible[activeIndex]) visible[activeIndex].click(); }
    else if (event.key === 'Escape') { event.preventDefault(); close(true); }
    else if (event.key === 'Tab') { close(false); }
  }

  /* 选项拿到焦点后，方向键仍由 list 统一处理 */
  function onFocusIn(event) {
    const opt = event.target.closest && event.target.closest('.picker-option');
    if (opt) setActive(visible.indexOf(opt), false);
  }

  function open() {
    if (trigger.disabled) return;
    if (pop.hidden) {
      build();
      pop.hidden = false;
      wrap.classList.add('is-open');
      trigger.setAttribute('aria-expanded', 'true');
      renderList();
      place();
      document.addEventListener('pointerdown', onDocPointer, true);
      document.addEventListener('keydown', onDocKey, true);
      window.addEventListener('resize', place);
      window.addEventListener('scroll', place, true);
      const search = pop.querySelector('.picker-search input');
      if (search) search.focus();
      else if (visible[activeIndex]) visible[activeIndex].focus();
    } else {
      close(true);
    }
  }

  function close(refocus) {
    if (pop.hidden) return;
    pop.hidden = true;
    wrap.classList.remove('is-open');
    trigger.setAttribute('aria-expanded', 'false');
    document.removeEventListener('pointerdown', onDocPointer, true);
    document.removeEventListener('keydown', onDocKey, true);
    window.removeEventListener('resize', place);
    window.removeEventListener('scroll', place, true);
    if (refocus) trigger.focus();
  }

  function onDocPointer(event) {
    if (!pop.contains(event.target) && !trigger.contains(event.target)) close(false);
  }
  function onDocKey(event) {
    if (event.key === 'Escape') { event.preventDefault(); close(true); }
  }

  trigger.onclick = open;
  trigger.onkeydown = event => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); open(); }
  };
  pop.addEventListener('focusin', onFocusIn);

  return { close, refresh: () => { if (!pop.hidden) { renderList(); place(); } } };
}

/* ---------------- 任务意图选择器 ---------------- */
function taskSections(query) {
  const matched = new Set(matchIntents(query).map(item => item.id));
  return intentsByGroup()
    .map(section => ({
      group: section.group,
      items: section.items.filter(item => matched.has(item.id)).map(item => ({
        value: item.id, label: item.label, desc: item.example
      }))
    }))
    .filter(section => section.items.length > 0);
}

function currentIntent() { return intentById(currentIntentId); }

function syncTaskDisplay() {
  const intent = currentIntent();
  el('taskLabel').textContent = intent.label;
  el('taskExample').textContent = intent.example;
  el('description').placeholder = intent.placeholder;
  el('task').setAttribute('aria-label', `任务：${intent.label}。${intent.example}。点击更换`);
  const task = configTasks[intent.task];
  el('headingTask').textContent = task
    ? `${intent.label} · ${task.name}`
    : intent.label;
}

/* ---------------- 身份选择器 ----------------
   选项要回答的是「这几个身份**差在哪**」，不是「这个人是谁」，
   所以第二行用 identities.js 的差别说明，而不是后端那句身份描述。
   右下角的小药丸放一个更短的标签，方便扫读。 */
function identitySections() {
  return [{
    group: '',
    items: Object.entries(configIdentities).map(([key, value]) => {
      const display = identityDisplay(key);
      return {
        value: key,
        label: value.name || key,
        desc: display.diff,
        meta: display.tag
      };
    })
  }];
}

function syncIdentityDisplay() {
  const info = configIdentities[currentIdentity] || {};
  el('identityLabel').textContent = info.name || currentIdentity || '未选择';
  el('identity').setAttribute('aria-label', `身份：${info.name || '未选择'}。点击更换`);
  /* 常驻一行说明当前身份的权限范围 —— 这正是用户说「区别不明确」的地方，
     不需要展开下拉也能看到。 */
  el('identityWhy').textContent = identityDisplay(currentIdentity).diff;
}

/* ---------------- 额外处理要求（一行点开） ---------------- */
function syncReqSummary() {
  const value = el('description').value.trim();
  el('reqCount').textContent = `${el('description').value.length} / 4000`;
  el('reqToggle').classList.toggle('has-value', value.length > 0);
  el('reqSummary').textContent = value
    ? `已填写：${value.length > 24 ? value.slice(0, 24) + '…' : value}`
    : '添加要求（可选）';
  el('reqClear').hidden = value.length === 0;
}

function setReqOpen(open) {
  el('reqBody').hidden = !open;
  el('reqToggle').setAttribute('aria-expanded', String(open));
  el('reqToggle').classList.toggle('is-open', open);
  if (open) el('description').focus();
}

/* ---------------- 二次确认弹窗 ---------------- */
function confirmDialog(title, body, confirmText, onConfirm) {
  const mask = document.createElement('div');
  mask.className = 'modal-mask';
  const box = document.createElement('div');
  box.className = 'modal'; box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true');

  const t = document.createElement('div'); t.className = 'modal-title'; t.textContent = title;
  const b = document.createElement('div'); b.className = 'modal-body'; b.textContent = body;

  const acts = document.createElement('div'); acts.className = 'modal-actions';
  const cancel = document.createElement('button');
  cancel.type = 'button'; cancel.className = 'btn'; cancel.textContent = '取消';
  const ok = document.createElement('button');
  ok.type = 'button'; ok.className = 'btn danger'; ok.textContent = confirmText;

  function close() { mask.remove(); document.removeEventListener('keydown', onKey); }
  function onKey(e) { if (e.key === 'Escape') close(); }
  cancel.onclick = close;
  ok.onclick = () => { close(); onConfirm(); };
  mask.onclick = e => { if (e.target === mask) close(); };
  document.addEventListener('keydown', onKey);

  acts.append(cancel, ok);
  box.append(t, b, acts);
  mask.append(box);
  document.body.append(mask);
  ok.focus();
}

/* ---------------- 文件库（iOS 拨动开关） ---------------- */
function renderFiles() {
  /* 输入框上方的本轮附件标签 */
  const att = el('attachments');
  att.replaceChildren();
  for (const file of files) {
    const chip = document.createElement('div'); chip.className = 'attachment';
    const name = document.createElement('span'); name.textContent = file.title;
    const off = document.createElement('button');
    off.type = 'button'; off.className = 'btn compact';
    off.textContent = '移出'; off.disabled = busy;
    off.onclick = () => { files = files.filter(f => f.id !== file.id); renderFiles(); syncSendState(); };
    chip.append(name, off);
    att.append(chip);
  }

  /* 左侧文件库 */
  const box = el('library');
  box.replaceChildren();
  if (!library.length) {
    const empty = document.createElement('div');
    empty.className = 'material-empty';
    empty.textContent = '还没有文件。点击输入框的「+」上传。';
    box.append(empty);
    return;
  }

  for (const file of library) {
    const on = files.some(f => f.id === file.doc_id);
    const row = document.createElement('div');
    row.className = 'material-row' + (on ? ' is-on' : '');

    const main = document.createElement('div'); main.className = 'mat-main';
    const nm = document.createElement('div'); nm.className = 'mat-name';
    nm.textContent = file.title; nm.title = file.title;
    const st = document.createElement('div'); st.className = 'mat-state';
    st.textContent = on ? '已加入本轮' : '未加入';
    main.append(nm, st);

    /* iOS 拨动开关 */
    const sw = document.createElement('input');
    sw.type = 'checkbox'; sw.className = 'mat-switch';
    sw.checked = on; sw.disabled = busy;
    sw.setAttribute('role', 'switch');
    sw.setAttribute('aria-label', `将「${file.title}」加入本轮`);
    sw.onchange = () => {
      if (sw.checked) {
        if (files.length >= 10) {
          sw.checked = false;
          return notice('每轮最多添加 10 份文件。', true);
        }
        files.push({ id: file.doc_id, title: file.title });
      } else {
        files = files.filter(f => f.id !== file.doc_id);
      }
      renderFiles(); syncSendState();
    };

    const del = document.createElement('button');
    del.type = 'button'; del.className = 'mat-del';
    del.title = '从本机删除该文件'; del.setAttribute('aria-label', `删除「${file.title}」`);
    del.disabled = busy;
    del.onclick = () => {
      confirmDialog('删除本机文件', `「${file.title}」将从本机删除，无法恢复。已发送的对话历史不受影响。`,
        '删除', async () => {
          setBusy(true);
          try {
            await api(`/api/upload/${encodeURIComponent(file.doc_id)}`, { method: 'DELETE' });
            files = files.filter(f => f.id !== file.doc_id);
            await refreshLibrary();
            notice('文件已从本机删除。已发送的对话历史保持原样。');
          } catch (error) { notice(error.message, true); } finally { setBusy(false); }
        });
    };

    row.append(main, sw, del);
    box.append(row);
  }
}

async function refreshLibrary() { library = (await api('/api/materials')).items; renderFiles(); }

function setBusy(value) {
  busy = value;
  ['newChat', 'clearChat', 'file'].forEach(id => { el(id).disabled = value || !ready; });
  const locked = value || !!sessionId;
  ['task', 'identity', 'description'].forEach(id => { el(id).disabled = locked; });
  el('reqToggle').disabled = locked;
  el('reqClear').disabled = locked;
  /* 对话开始后任务与身份会被后端固定（chat.py 在建会话时就锁定），
     控件随之置灰。置灰的控件本身收不到 hover，所以把原因写在
     **外层容器**的 title 上，鼠标停在灰掉的控件上仍能看到为什么。 */
  const why = locked && !value
    ? '本对话的任务和身份在第一次发送后已固定，要更改请点「新对话」'
    : '';
  el('taskPicker').title = why;
  el('identityPicker').title = why;
  el('uploadBtn').classList.toggle('is-disabled', value || !ready);
  el('message').disabled = value;
  renderFiles();
  syncSendState();
}

async function api(url, options = {}) {
  const response = await fetch(url, options), data = await response.json();
  if (!response.ok) {
    const error = new Error(typeof data.detail === 'string' ? data.detail : '请求未通过检查');
    error.status = response.status; throw error;
  }
  return data;
}

/* ---------------- 空态与预设提示词 ---------------- */
function emptyState() {
  const intent = currentIntent();
  const box = document.createElement('div'); box.className = 'empty-conversation';

  const icon = document.createElement('div'); icon.className = 'shield-icon';
  icon.innerHTML = SHIELD_SVG;

  const title = document.createElement('h2'); title.className = 'empty-title';
  title.textContent = '开始一段受保护的对话';

  const sub = document.createElement('p'); sub.className = 'empty-sub';
  sub.textContent = `当前任务：${intent.label} — ${intent.example}。发送前会自动脱敏。`;

  const group = document.createElement('div'); group.className = 'prompt-group';
  const gt = document.createElement('div'); gt.className = 'prompt-group-title';
  gt.textContent = '可以这样问';
  const chips = document.createElement('div'); chips.className = 'prompt-chips';

  for (const text of intent.prompts) {
    const btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'prompt-chip'; btn.disabled = busy || !ready;
    const ico = document.createElement('span'); ico.className = 'chip-ico'; ico.innerHTML = CHIP_ICON;
    const span = document.createElement('span'); span.className = 'chip-text'; span.textContent = text;
    const arrow = document.createElement('span'); arrow.className = 'chip-arrow'; arrow.innerHTML = ARROW_ICON;
    btn.append(ico, span, arrow);
    btn.onclick = () => {
      el('message').value = text;
      autoGrow(); syncSendState(); el('message').focus();
    };
    chips.append(btn);
  }

  group.append(gt, chips);
  box.append(icon, title, sub, group);
  return box;
}

/* ---------------- 消息渲染 ---------------- */
function messageBubble(message) {
  const isUser = message.role === 'user';
  const art = document.createElement('article');
  art.className = 'chat-message ' + (isUser ? 'is-user' : 'is-assistant');

  const avatar = document.createElement('div');
  avatar.className = 'avatar'; avatar.textContent = isUser ? '我' : '盾';

  const bubble = document.createElement('div'); bubble.className = 'bubble';
  const head = document.createElement('div'); head.className = 'bubble-head';
  head.textContent = isUser ? '你 · 发送的内容' : '隐盾';
  const text = document.createElement('div'); text.className = 'bubble-text';
  text.textContent = message.content;
  bubble.append(head, text);
  art.append(avatar, bubble);
  return art;
}

function renderTurns(turns) {
  const n = Math.max(0, Math.min(turns || 0, MAX_TURNS));
  el('turns').textContent = `${n} / ${MAX_TURNS}`;
  el('turnsBar').style.width = `${(n / MAX_TURNS) * 100}%`;
  const wrap = el('turnsWrap');
  wrap.classList.toggle('is-warn', n >= MAX_TURNS * 0.75 && n < MAX_TURNS);
  wrap.classList.toggle('is-full', n >= MAX_TURNS);
}

function render(data) {
  const box = el('messages');
  box.replaceChildren();
  const list = data.messages || [];
  if (!list.length) box.append(emptyState());
  for (const message of list) box.append(messageBubble(message));
  renderTurns(data.turns || 0);
  const scroller = document.querySelector('.chat-scroll');
  if (scroller) scroller.scrollTop = scroller.scrollHeight;
}

function showDecisions(decisions = []) {
  el('decisions').replaceChildren();
  el('processing').hidden = !decisions.length;
  for (const item of decisions) {
    const row = document.createElement('div'); row.className = 'decision';
    const badge = document.createElement('span');
    badge.className = 'decision-badge ' + (item.action || '');
    badge.textContent = actionNames[item.action] || item.action || '处理';
    const reason = document.createElement('span');
    reason.className = 'decision-reason';
    reason.textContent = item.reason || '处理完成';
    row.append(badge, reason);
    el('decisions').append(row);
  }
}

/* ---------------- 会话 ---------------- */
async function clearRemoteSession() {
  if (sessionId) {
    try { await api(`/api/chat/${encodeURIComponent(sessionId)}`, { method: 'DELETE' }); }
    catch (error) { if (error.status !== 404) throw error; }
  }
  sessionId = null;
}

async function createSession() {
  const data = await api('/api/chat/sessions', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      identity: currentIdentity, task: currentIntent().task,
      task_description: el('description').value
    })
  });
  sessionId = data.session_id; render(data);
}

async function resetConversation(message) {
  if (busy || !ready) return;
  closePickers();
  setBusy(true);
  try {
    await clearRemoteSession();
    files = []; el('message').value = ''; autoGrow();
    render({}); showDecisions(); notice(message);
  } catch (error) { notice(error.message, true); } finally { setBusy(false); }
}

el('newChat').onclick = () => resetConversation('新对话已准备好，可以调整任务后直接发送。');

el('clearChat').onclick = () => {
  if (busy || !ready) return;
  confirmDialog('清除本次对话',
    '对话内容和代号映射记录会被删除，无法恢复。本机文件不受影响，需要在左侧单独删除。',
    '确认清除',
    () => resetConversation('对话和代号映射已清除。本机文件可在左侧单独删除。'));
};

/* 收起 / 展开侧栏前先关掉任何打开的弹层。
   弹层是 position:fixed 挂在 body 上，侧栏折叠后它的锚点按钮已被隐藏，
   留着会变成一个「没有归属、位置也错」的浮层。 */
function closePickers() {
  if (taskPicker) taskPicker.close(false);
  if (identityPicker) identityPicker.close(false);
}

/* 侧栏收起 / 展开 */
el('railToggle').onclick = () => {
  closePickers();
  const layout = document.querySelector('.chat-layout');
  const collapsed = layout.classList.toggle('rail-collapsed');
  el('railToggle').setAttribute('aria-expanded', String(!collapsed));
};

/* 收起态图标导航：展开侧栏并滚动到对应区块 */
document.querySelectorAll('.rail-btn').forEach(btn => {
  btn.onclick = () => {
    const layout = document.querySelector('.chat-layout');
    layout.classList.remove('rail-collapsed');
    el('railToggle').setAttribute('aria-expanded', 'true');
    const target = document.getElementById(btn.dataset.target);
    if (target) {
      if (target.tagName === 'DETAILS') target.open = true;
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  };
});

/* 额外处理要求：一行按钮原地展开 */
el('reqToggle').onclick = () => setReqOpen(el('reqBody').hidden);
el('reqClear').onclick = () => {
  el('description').value = '';
  syncReqSummary();
  el('description').focus();
};
el('description').addEventListener('input', syncReqSummary);

/* 输入框：自适应高度 + 回车发送（Shift+Enter 换行） */
el('message').addEventListener('input', () => { autoGrow(); syncSendState(); });
el('message').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    el('composer').requestSubmit();
  }
});

el('file').onchange = async () => {
  const selected = [...el('file').files];
  if (!selected.length || busy || !ready) return;
  if (selected.length + files.length > 10) { el('file').value = ''; return notice('每轮最多添加 10 份文件。', true); }
  setBusy(true);
  try {
    for (const file of selected) {
      const form = new FormData(); form.append('file', file);
      const result = await api('/api/upload', { method: 'POST', body: form });
        files.push({ id: result.doc_id, title: result.title }); await refreshLibrary();
        if (result.worksheets > 1) notice(`已读取 ${result.worksheets} 个工作表。当前选中首表，其余可在资料库中选择。`);
    }
    notice('文件已加入本轮。输入问题后发送，也可以直接发送文件。');
  } catch (error) { notice(error.message, true); } finally { el('file').value = ''; setBusy(false); }
};

el('composer').onsubmit = async event => {
  event.preventDefault();
  if (busy || !ready || !localReady) return;
  if (!el('message').value.trim() && !files.length) return notice('请输入问题或添加文件。', true);
  setBusy(true);
  setApiStatus('正在本机脱敏…', 'busy');
  const waitingStatus = setTimeout(() => setApiStatus('正在检查内容并等待回答…', 'busy'), 800);
  try {
    if (!sessionId) await createSession();
    const result = await api(`/api/chat/${encodeURIComponent(sessionId)}/messages`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: el('message').value, doc_ids: files.map(f => f.id) })
    });
    render(result); showDecisions(result.decisions);
    if (!result.ok) {
      setApiStatus('本轮已暂停', 'warn');
      const reason = result.pause_reason || '本轮未通过安全检查';
      const action = /繁忙/.test(reason) ? '请稍后重试。'
        : /超过|容量|上限/.test(reason) ? '请缩短材料或新建对话。'
        : /模型不可用|识别失败/.test(reason) ? '请检查本地模型配置并重启服务。'
        : /真实模型|HTTP \d+/.test(reason) ? '请检查 DeepSeek 服务状态或稍后重试。'
        : '请检查材料和任务设置后重试。';
      notice(`${reason} ${action}本轮未加入对话历史。`, true);
      return;
    }
    el('message').value = ''; files = []; autoGrow();
    if (result.engine === 'real') {
      setApiStatus('本轮真实 API 调用成功', 'ok');
      notice('已收到真实生成服务的回答。发送内容和回答均已通过复检。' + (result.warning || ''));
    } else if (result.engine === 'local') {
      setApiStatus('本机全表统计完成', 'ok');
      notice('已按完整表格精确统计，本轮未调用外部模型。');
    } else {
      setApiStatus('本轮为离线演示回复', 'warn');
      notice('离线演示完成。发送内容和回答均已通过复检。' + (result.warning || ''));
    }
  } catch (error) {
    setApiStatus('本轮未完成', 'error');
    if (error.status === 404 && sessionId) {
      sessionId = null; render({}); showDecisions();
      notice('服务已重启或会话已过期，已准备新对话。请再次发送当前问题。', true);
    } else notice(error.message, true);
  } finally { clearTimeout(waitingStatus); setBusy(false); }
};

/* ---------------- 初始化 ---------------- */
let taskPicker = null, identityPicker = null;

async function initialize() {
  try {
    const [config, health] = await Promise.all([api('/api/config'), api('/api/health')]);
    configTasks = config.tasks || {};
    configIdentities = config.identities || {};

    /* 身份：默认学生组织负责人（权限最高，能读本组织全部材料） */
    const identityKeys = Object.keys(configIdentities);
    currentIdentity = identityKeys.includes('student_leader') ? 'student_leader' : identityKeys[0];
    currentIntentId = INTENTS[0].id;

    taskPicker = createPicker({
      trigger: el('task'), pop: el('taskPop'), wrap: el('taskPicker'), search: true,
      searchPlaceholder: '搜索任务，例如「纪要」「人数」',
      listLabel: '可选任务', emptyText: '没有匹配的任务，换个词试试',
      sections: taskSections, selected: () => currentIntentId,
      onPick: value => {
        currentIntentId = value;
        syncTaskDisplay();
        if (!sessionId) render({});
      }
    });

    identityPicker = createPicker({
      trigger: el('identity'), pop: el('identityPop'), wrap: el('identityPicker'),
      search: false, listLabel: '可选身份', emptyText: '没有可选身份',
      sections: identitySections, selected: () => currentIdentity,
      onPick: value => {
        currentIdentity = value;
        syncIdentityDisplay();
        if (!sessionId) render({});
      }
    });

    syncTaskDisplay(); syncIdentityDisplay(); syncReqSummary();

    localReady = !!health.ready_to_chat;
    setModelStatus(health);
    const llm = config.models.llm;
    if (llm.mode === 'mock') setApiStatus('离线演示 · 未调用真实 API', 'warn');
    else if (llm.has_key) setApiStatus('API 已配置 · 发送时连接', 'ok');
    else setApiStatus('API 未配置 · 无法生成回答', 'error');
    el('apiHelp').textContent = `生成服务：${llm.provider} / ${llm.model}。真实调用需在本机 .env 配置服务地址、模型和密钥，并将 LLM_MODE 设为 real 后重启。已配置不代表已连接成功。`;
    library = config.materials; ready = true;
    render({}); setBusy(false); autoGrow(); syncSendState();
  } catch (error) { notice('初始化失败，请刷新重试：' + error.message, true); }
}

initialize();
