'use strict';
const field = (id) => document.getElementById(id);
let diagnosticRevision = 0;
let toolRevision = 0;
let approval = null;
let pending = null;
let eventId = null;

async function api(path, data, token) {
  const headers = {};
  if (data !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = 'Bearer ' + token;
  const response = await fetch(path, {
    method: data === undefined ? 'GET' : 'POST', headers, cache: 'no-store',
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) {
    const detail = result.detail;
    throw new Error(typeof detail === 'string' ? detail : detail?.reason || '请求失败，请检查输入。');
  }
  return result;
}

field('diagnose').addEventListener('input', () => {
  diagnosticRevision += 1;
  field('entities').hidden = true;
  field('decisions').textContent = '';
  field('status').textContent = '';
});
field('diagnose').addEventListener('submit', async (event) => {
  event.preventDefault();
  const revision = ++diagnosticRevision;
  const button = field('diagnose-button');
  button.disabled = true;
  field('entities').hidden = true;
  field('decisions').textContent = '';
  field('status').textContent = '正在本机核对…';
  try {
    const result = await api('/api/integrations/diagnose', {
      identity: field('identity').value, task: field('task').value,
      recipient: field('recipient').value, text: field('text').value,
      task_description: field('description').value,
    });
    if (revision !== diagnosticRevision) return;
    field('entities').querySelector('tbody').replaceChildren(...result.entities.map((span) => {
      const row = document.createElement('tr');
      for (const value of [span.text, span.category, span.detector + ' / ' + span.rule_id, span.confidence]) {
        row.insertCell().textContent = value;
      }
      return row;
    }));
    field('entities').hidden = !result.entities.length;
    field('decisions').textContent = result.segments.map((segment) =>
      '原文位置 ' + segment.start + '–' + segment.end + '\n' + segment.action + '\n' +
      segment.reason + '\n' + segment.hard_checks.map((check) =>
        (check.passed ? '通过 ' : '暂停 ') + check.rule + ' ' + check.detail).join('\n')).join('\n\n');
    field('status').textContent = result.paused ? '需要修订后重新核对。' + result.reason : '本机核对完成，可查看各片段的动作依据。';
  } catch (error) {
    if (revision === diagnosticRevision) field('status').textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

field('tool').addEventListener('input', () => {
  toolRevision += 1;
  approval = pending = null;
  eventId = null;
  field('preview').textContent = '';
  field('execute').hidden = true;
  field('tool-status').textContent = '';
});
field('tool').addEventListener('submit', async (event) => {
  event.preventDefault();
  const revision = ++toolRevision;
  const button = field('preview-button');
  button.disabled = true;
  approval = null;
  field('execute').hidden = true;
  field('preview').textContent = '';
  try {
    eventId ||= crypto.randomUUID();
    const body = {tool_id: field('tool-id').value, text: field('tool-text').value, event_id: eventId};
    const result = await api('/api/integrations/tools/preview', body, field('admin').value);
    if (revision !== toolRevision) return;
    pending = body;
    approval = result;
    field('preview').textContent = '接收地址 ' + result.endpoint + '\n接收方 ' +
      result.recipient + '\n\n' + result.text;
    field('execute').hidden = false;
    field('tool-status').textContent = '请核对地址及正文。确认有效期为两分钟。';
  } catch (error) {
    if (revision === toolRevision) field('tool-status').textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
field('execute').addEventListener('click', async () => {
  if (!approval || !pending || field('execute').disabled) return;
  const revision = toolRevision;
  field('execute').disabled = true;
  try {
    await api('/api/integrations/tools/execute', {
      ...pending, expires_at: approval.expires_at, approval: approval.approval,
    }, field('admin').value);
    if (revision !== toolRevision) return;
    field('tool-status').textContent = '接收端已返回通过检查的结果。';
    field('execute').hidden = true;
    approval = null;
  } catch (error) {
    if (revision === toolRevision) field('tool-status').textContent = error.message;
  } finally {
    field('execute').disabled = false;
  }
});

async function init() {
  const [config, status] = await Promise.all([api('/api/config'), api('/api/integrations')]);
  for (const [id, values] of [['identity', config.identities], ['task', config.tasks], ['recipient', config.recipients]]) {
    for (const [key, value] of Object.entries(values)) field(id).add(new Option(value.name, key));
  }
  field('task').value = 'meeting_minutes';
  const labels = {recognition: '隐盾识别规则', policies: '隐盾边界策略', litellm: '可选代理连接', lakera: '可选外部检查'};
  field('components').replaceChildren(...Object.entries(labels).map(([key, name]) => {
    const p = document.createElement('p');
    p.textContent = name + (status[key] ? ' · 已配置启用' : ' · 未启用');
    return p;
  }));
  const knowledge = document.createElement('p');
  knowledge.textContent = '获准知识源绑定 ' + status.knowledge_sources + ' 个';
  field('components').append(knowledge);
  const boundaries = document.createElement('p');
  boundaries.textContent = '独立策略边界 ' + (status.policy_boundaries.join('、') || '使用全局规则');
  field('components').append(boundaries);
  field('diagnose-button').disabled = false;
}
init().catch((error) => { field('status').textContent = error.message; });
