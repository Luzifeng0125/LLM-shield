'use strict';

const byId = (id) => document.getElementById(id);
const conditionList = byId('conditions');
let main = null;
let joined = null;
let current = null;
let previous = null;
let sourceRequest = 0;
let revision = 0;

async function request(path, body, raw = false) {
  const init = {cache: 'no-store'};
  if (body !== undefined) {
    init.method = 'POST';
    if (body instanceof FormData) {
      init.body = body;
    } else {
      init.headers = {'Content-Type': 'application/json'};
      init.body = JSON.stringify(body);
    }
  }
  const response = await fetch(path, init);
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === 'string' ? data.detail : '请求失败，请检查材料和统计条件。');
  }
  return raw ? response.blob() : response.json();
}

function options(select, values, blankLabel) {
  const old = select.value;
  select.replaceChildren();
  if (blankLabel) select.add(new Option(blankLabel, ''));
  for (const [value, label] of values) select.add(new Option(label, value));
  if ([...select.options].some((option) => option.value === old)) select.value = old;
}

const choices = (columns) => columns.map((column) => [column, column]);
const columns = () => [...(main?.columns || []), ...(joined?.columns || []).map((col) => '关联表 · ' + col)];

function invalidate() {
  revision += 1;
  byId('result').hidden = true;
  byId('status').textContent = '';
}

function renderFields() {
  options(byId('left-key'), choices(main?.columns || []), '选择字段');
  options(byId('right-key'), choices(joined?.columns || []), '选择字段');
  options(byId('group'), choices(columns()), '不分组');
  options(byId('distinct'), choices(columns()), '按记录计数');
  for (const row of conditionList.children) options(row.firstElementChild, choices(columns()), '选择字段');
  byId('run').disabled = !main;
}

function addCondition(data = {}) {
  if (conditionList.children.length >= 12) return;
  const row = document.createElement('div');
  row.className = 'workbench-condition';
  const column = document.createElement('select');
  column.setAttribute('aria-label', '筛选字段');
  column.required = true;
  options(column, choices(columns()), '选择字段');
  column.value = data.column || '';
  const op = document.createElement('select');
  op.setAttribute('aria-label', '匹配方式');
  options(op, [['eq', '等于'], ['ne', '不等于']]);
  op.value = data.op || 'eq';
  const value = document.createElement('input');
  value.setAttribute('aria-label', '匹配值');
  value.placeholder = '空白表示空值';
  value.maxLength = 512;
  value.value = data.value || '';
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'btn';
  remove.textContent = '移除';
  remove.addEventListener('click', () => { row.remove(); invalidate(); });
  row.append(column, op, value, remove);
  conditionList.append(row);
}

async function refreshSources(selected = []) {
  const {items} = await request('/api/materials');
  const tables = items.filter((item) => item.n_rows > 0 &&
    (!item.allowed_purposes || item.allowed_purposes.includes('activity_stats')));
  const entries = tables.map((item) => [item.doc_id, item.title]);
  options(byId('main-source'), entries, '选择主表');
  options(byId('join-source'), entries, '不关联');
  if (selected[0]) byId('main-source').value = selected[0];
  if (selected[1]) {
    byId('join-source').value = selected[1];
    byId('join-source').closest('details').open = true;
  }
  await loadSources();
}

async function loadSources() {
  invalidate();
  const generation = ++sourceRequest;
  main = joined = null;
  byId('run').disabled = true;
  const identity = byId('identity').value;
  const load = async (doc_id) => {
    if (!doc_id) return null;
    const data = await request('/api/workbench/source', {identity, source: {doc_id}});
    return {...data, doc_id};
  };
  try {
    const [primary, secondary] = await Promise.all([
      load(byId('main-source').value), load(byId('join-source').value),
    ]);
    if (generation !== sourceRequest) return;
    main = primary;
    joined = secondary;
    renderFields();
    byId('status').textContent = main ? '已读取表头，可以设定口径。' : '选择已上传的表格，或上传活动统计表。';
  } catch (error) {
    if (generation !== sourceRequest) return;
    renderFields();
    byId('status').textContent = error.message;
  }
}

function plan() {
  if (!main) throw new Error('请先选择主表。');
  const query = {
    identity: byId('identity').value,
    source: {doc_id: main.doc_id, version: main.version},
    conditions: Array.from(conditionList.children, ({children}) =>
      ({column: children[0].value, op: children[1].value, value: children[2].value})),
    logic: byId('logic').value,
    group_by: byId('group').value || null,
    distinct_by: byId('distinct').value || null,
  };
  if (joined) {
    const left_column = byId('left-key').value;
    const right_column = byId('right-key').value;
    if (!left_column || !right_column) throw new Error('请选择两张表的关联键。');
    query.join = {source: {doc_id: joined.doc_id, version: joined.version}, left_column, right_column};
  }
  return query;
}

function render(result, query) {
  const metrics = [
    [result.mode === 'distinct' ? '全局不同键数' : '记录合计', result.total],
    ['主表记录', result.source_rows], ['命中记录', result.matched_rows],
  ];
  if (query.join) metrics.push(['关联后记录', result.joined_rows], ['未关联记录', result.unmatched_rows]);
  if (query.distinct_by) metrics.push(['空去重键记录', result.missing_keys]);
  byId('metrics').replaceChildren(...metrics.map(([label, value]) => {
    const card = document.createElement('div');
    const name = document.createElement('dt');
    const number = document.createElement('dd');
    name.textContent = label;
    number.textContent = value;
    card.append(name, number);
    return card;
  }));
  const criteria = ['主表 ' + main.title];
  if (query.join) criteria.push('关联表 ' + joined.title + '（' + query.join.left_column + ' ↔ ' + query.join.right_column + '）');
  if (query.conditions.length) {
    const conditions = query.conditions.map((c) => c.column + (c.op === 'eq' ? ' 等于 ' : ' 不等于 ') + (c.value || '空值'));
    criteria.push((query.logic === 'all' ? '全部满足 ' : '任一满足 ') + conditions.join('、'));
  }
  criteria.push(query.distinct_by ? '按「' + query.distinct_by + '」去重，空键不计入。' : '按记录计数，涉及人数时请指定唯一身份键。');
  if (query.group_by) criteria.push('按「' + query.group_by + '」分组。' +
    (query.distinct_by ? '同一键可出现在不同分组。各组之和可能大于全局合计。' : ''));
  byId('criteria').replaceChildren(...criteria.map((line) => {
    const p = document.createElement('p');
    p.textContent = line;
    return p;
  }));
  byId('result-rows').replaceChildren(...result.groups.map((group) => {
    const row = document.createElement('tr');
    row.insertCell().textContent = group.value || '（空值）';
    row.insertCell().textContent = group.count;
    return row;
  }));
  byId('result-table').hidden = !result.groups.length;
  byId('result').hidden = false;
}

for (const id of ['identity', 'main-source', 'join-source']) byId(id).addEventListener('change', loadSources);
byId('query').addEventListener('input', invalidate);
byId('add-condition').addEventListener('click', () => { addCondition(); invalidate(); });

byId('upload').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  invalidate();
  byId('status').textContent = '正在解析表格…';
  try {
    const file = byId('file').files[0];
    const form = new FormData();
    form.set('file', file);
    form.set('task', 'activity_stats');
    const data = await request('/api/upload', form);
    await refreshSources(data.documents.filter((item) => item.n_rows).map((item) => item.doc_id).slice(0, 1));
    byId('file').value = '';
  } catch (error) {
    byId('status').textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

byId('query').addEventListener('submit', async (event) => {
  event.preventDefault();
  invalidate();
  const runRevision = revision;
  byId('status').textContent = '正在本机计算…';
  try {
    const query = plan();
    const result = await request('/api/workbench/query', query);
    if (runRevision !== revision) return;
    previous = current;
    current = query;
    byId('undo').disabled = !previous;
    render(result, query);
    byId('status').textContent = '本机计算完成';
  } catch (error) {
    if (runRevision === revision) byId('status').textContent = error.message;
  }
});

byId('undo').addEventListener('click', async () => {
  if (!previous) return;
  const query = previous;
  byId('identity').value = query.identity;
  byId('main-source').value = query.source.doc_id;
  byId('join-source').value = query.join?.source.doc_id || '';
  byId('join-source').closest('details').open = Boolean(query.join);
  await loadSources();
  if (main?.version !== query.source.version || joined?.version !== query.join?.source.version) {
    byId('status').textContent = '来源已变化，无法恢复旧条件。';
    return;
  }
  byId('left-key').value = query.join?.left_column || '';
  byId('right-key').value = query.join?.right_column || '';
  byId('group').value = query.group_by || '';
  byId('distinct').value = query.distinct_by || '';
  byId('logic').value = query.logic;
  conditionList.replaceChildren();
  query.conditions.forEach(addCondition);
  byId('query').requestSubmit();
});

byId('export').addEventListener('click', async () => {
  if (!current || byId('result').hidden) return;
  const runRevision = revision;
  const button = byId('export');
  button.disabled = true;
  try {
    const blob = await request('/api/workbench/export', current, true);
    if (runRevision !== revision) return;
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = '隐盾本机统计汇总.csv';
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    if (runRevision === revision) {
      invalidate();
      byId('status').textContent = error.message;
    }
  } finally {
    button.disabled = false;
  }
});

async function init() {
  const {identities} = await request('/api/config');
  options(byId('identity'), Object.entries(identities).map(([key, value]) => [key, value.name]));
  await refreshSources();
}
init().catch((error) => { byId('status').textContent = error.message; });
