'use strict';

const field = (id) => document.getElementById(id);
const statusNode = field('management-status');
const project = field('project');
let selection = 0;
let checkEvent;

async function api(path, token, data, method = data === undefined ? 'GET' : 'POST') {
  if (!token) throw new Error('请输入对应凭证。');
  const headers = {Authorization: 'Bearer ' + token};
  if (data !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch('/api/workflows' + path, {
    method, headers, cache: 'no-store', body: data === undefined ? undefined : JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(typeof error?.detail === 'string' ? error.detail : '操作失败，请核对输入和项目权限。');
  }
  return response.json();
}

function clearProject() {
  selection += 1;
  field('project-sections').hidden = !project.value;
  for (const id of ['assignment-result', 'supplier-result', 'pass-result', 'count', 'benchmark-result']) {
    field(id).textContent = '';
  }
  field('supplier').value = '';
  field('benchmark').value = '';
  statusNode.textContent = '';
}

field('admin').addEventListener('input', () => {
  project.replaceChildren(new Option('请选择', ''));
  clearProject();
});
project.addEventListener('change', clearProject);

function admin(id, eventName, handler, needsProject = true) {
  field(id).addEventListener(eventName, async (event) => {
    event.preventDefault();
    const token = field('admin').value.trim();
    const current = project.value;
    const generation = selection;
    const active = () => selection === generation;
    const button = event.submitter || (eventName === 'submit' ? field(id).querySelector('button') : field(id));
    if (button.disabled) return;
    button.disabled = true;
    statusNode.textContent = '';
    try {
      if (needsProject && !current) throw new Error('请先选择项目。');
      await handler({
        request: (path = '', data, method) => api('/projects' + (needsProject ? '/' + current : '') + path,
          token, data, method),
        active,
      });
    } catch (error) {
      if (active()) statusNode.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
}

function projects(items, value) {
  project.replaceChildren(new Option('请选择', ''), ...items.map((id) => new Option(id, id)));
  if (items.includes(value)) project.value = value;
  clearProject();
}

admin('load', 'click', async ({request, active}) => {
  const current = project.value;
  const result = await request();
  if (active()) projects(result.projects, current);
}, false);
admin('create', 'click', async ({request, active}) => {
  const result = await request('', {}, 'POST');
  const list = await request();
  if (active()) projects(list.projects, result.project_id);
}, false);

const rows = (id) => field(id).value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  .map((line) => line.split(/[,，]/).map((cell) => cell.trim()));

admin('assignment', 'submit', async ({request, active}) => {
  field('assignment-result').textContent = '';
  const resourceRows = rows('resources');
  const subjectRows = rows('subjects');
  if (resourceRows.some((row) => row.length !== 2 || !row[0] || !/^\d+$/.test(row[1])) ||
      subjectRows.some((row) => row.length < 2 || row.some((cell) => !cell))) {
    throw new Error('请按示例填写资源、容量及参与者的可用资源。');
  }
  const resources = resourceRows.map(([label, capacity]) => ({label, capacity: Number(capacity)}));
  const assignments = subjectRows.map(([subject, ...labels]) => ({
    subject, eligible: labels.map((label) => resources.findIndex((resource) => resource.label === label)),
  }));
  if (assignments.some((entry) => entry.eligible.includes(-1))) {
    throw new Error('可用资源中包含未登记的资源。');
  }
  const result = await request('/assignments', {resources, assignments});
  const verified = await request('/assignments/' + result.assignment_id + '/verify', result.local_solution);
  if (active()) field('assignment-result').textContent = verified.placements
    .map(({subject, resource}) => subject + ' → ' + resource).join('\n');
});

admin('supplier-create', 'click', async ({request, active}) => {
  field('supplier-result').textContent = '';
  const supplier = await request('/suppliers', {});
  if (!active()) return;
  field('supplier').value = supplier.supplier_id;
  field('supplier-result').textContent = '供应商编号 ' + supplier.supplier_id +
    '\n供应商凭证仅本次显示，请通过私下渠道交付\n' + supplier.supplier_token;
});
admin('pass', 'submit', async ({request, active}) => {
  field('pass-result').textContent = '';
  const supplier = field('supplier').value.trim();
  const result = await request('/suppliers/' + encodeURIComponent(supplier) + '/passes', {
    subject_key: field('subject').value.trim(), ttl_seconds: Number(field('ttl').value) * 60,
  });
  if (active()) field('pass-result').textContent = '一次性签到凭证\n' + result.pass_token;
});
admin('summary', 'click', async ({request, active}) => {
  const result = await request('/check-ins/summary');
  if (active()) field('count').textContent = '已签到 ' + result.checked_in_count + ' 人次';
});
admin('revoke-supplier', 'click', async ({request, active}) => {
  const supplier = field('supplier').value.trim();
  if (!/^[a-f0-9]{32}$/.test(supplier)) throw new Error('请先填写供应商编号。');
  if (!window.confirm('撤销该供应商及其未核销凭证？')) return;
  await request('/suppliers/' + supplier, undefined, 'DELETE');
  if (!active()) return;
  field('supplier').value = '';
  field('supplier-result').textContent = '';
  field('pass-result').textContent = '';
  statusNode.textContent = '供应商已撤销';
});

async function jsonFile(id) {
  const file = field(id).files[0];
  if (!file || file.size > 1024 * 1024) throw new Error('请选择不超过 1 MB 的 JSON 文件。');
  try {
    return JSON.parse(await file.text());
  } catch {
    throw new Error('文件不是有效的 JSON。');
  }
}

admin('suite', 'submit', async ({request, active}) => {
  const result = await request('/benchmarks', await jsonFile('suite-file'));
  if (!active()) return;
  field('benchmark').value = result.benchmark_id;
  field('benchmark-result').textContent = '已封存 ' + result.case_count + ' 个用例';
});

function benchmarkPath() {
  const value = field('benchmark').value.trim();
  if (!/^[a-f0-9]{32}$/.test(value)) throw new Error('请填写验收编号。');
  return '/benchmarks/' + value;
}

function report(reports) {
  field('benchmark-result').textContent = reports.map((entry) => {
    const quote = entry.quoted_cents_per_task;
    return entry.name + ' ' + entry.version + '\n正确 ' + entry.passed + '/' + entry.total +
      '，耗时 ' + entry.execution_ms + ' 毫秒，报价 ' + (quote == null ? '未填写' : quote + ' 分/任务');
  }).join('\n\n') || '当前还没有候选方案。';
}

admin('candidate', 'submit', async ({request, active}) => {
  const path = benchmarkPath();
  const result = await request(path + '/candidates', await jsonFile('candidate-file'));
  if (active()) report([result]);
});
admin('benchmark-report', 'click', async ({request, active}) => {
  const result = await request(benchmarkPath() + '/report');
  if (active()) report(result.reports);
});

field('checkin').addEventListener('submit', async (event) => {
  event.preventDefault();
  const supplier = field('supplier-token').value.trim();
  const pass = field('pass-token').value.trim();
  const result = field('checkin-result');
  const button = event.submitter || field('checkin').querySelector('button');
  if (button.disabled) return;
  button.disabled = true;
  try {
    if (!checkEvent || checkEvent.supplier !== supplier || checkEvent.pass !== pass) {
      checkEvent = {supplier, pass, id: crypto.randomUUID()};
    }
    await api('/check-ins', supplier, {pass_token: pass, event_id: checkEvent.id});
    result.textContent = '签到已核销';
  } catch (error) {
    result.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
