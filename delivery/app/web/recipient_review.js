'use strict';

const byId = (id) => document.getElementById(id);
const form = byId('review-form');
const statusNode = byId('status');
let config;
let revision = 0;
let reviewId = null;

async function post(path, data, download = false) {
  const response = await fetch(path, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(typeof error?.detail === 'string' ? error.detail : '请求失败，请检查所选材料。');
  }
  return download ? response.blob() : response.json();
}

function clearVersions() {
  revision += 1;
  byId('versions').replaceChildren();
  statusNode.textContent = '';
}

function documents(keepSelection = false) {
  const task = byId('task').value;
  const select = byId('document');
  const previous = select.value;
  select.replaceChildren(new Option('不选材料', ''));
  for (const item of config.materials) {
    if (!item.allowed_purposes || item.allowed_purposes.includes(task)) {
      select.add(new Option(item.title, item.doc_id));
    }
  }
  if (keepSelection && Array.from(select.options).some(({value}) => value === previous)) select.value = previous;
}

function card(version, body, id, atRevision) {
  const section = document.createElement('section');
  const title = document.createElement('h3');
  title.textContent = config.recipients[version.recipient].name;
  section.append(title);
  const content = document.createElement(version.allowed ? 'pre' : 'p');
  content.textContent = version.allowed ? version.text : '已暂停：' + version.reason;
  section.append(content);
  if (!version.approval) return section;

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'btn';
  button.textContent = '下载核对后的 Word';
  button.addEventListener('click', async () => {
    button.disabled = true;
    statusNode.textContent = '正在重新检查外发版本…';
    try {
      const blob = await post('/api/recipient-review/export', {
        ...body, recipients: [version.recipient], review_id: id, approval: version.approval,
      }, true);
      if (revision !== atRevision) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = '隐盾外发版本.docx';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      statusNode.textContent = '已生成 Word';
    } catch (error) {
      if (revision === atRevision) statusNode.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
  section.append(button);
  return section;
}

form.addEventListener('input', clearVersions);
byId('task').addEventListener('change', () => documents());
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearVersions();
  if (!byId('ocr-check').hidden && !byId('ocr-verified').checked) {
    statusNode.textContent = '请先对照原件核对 OCR 草稿，再确认。';
    return;
  }
  const input = byId('source-text').value;
  const doc = byId('document').value;
  const recipients = [...form.querySelectorAll('input[name="recipient"]:checked')].map((item) => item.value);
  if ((!doc && !input.trim()) || !recipients.length || recipients.length > 4) {
    statusNode.textContent = '请添加材料或文本，并选择一至四个接收方。';
    return;
  }
  const atRevision = revision;
  const button = byId('review-button');
  button.disabled = true;
  statusNode.textContent = '正在逐个检查接收权限和内容…';
  const body = {
    identity: byId('identity').value, task: byId('task').value,
    doc_ids: doc ? [doc] : [], custom_text: input,
    task_description: byId('task-description').value, recipients, review_id: reviewId,
  };
  try {
    const result = await post('/api/recipient-review', body);
    if (revision !== atRevision) return;
    reviewId = result.review_id;
    byId('versions').replaceChildren(...result.versions.map((v) => card(v, body, reviewId, atRevision)));
    statusNode.textContent = '已检查 ' + result.versions.length + ' 个接收方。';
  } catch (error) {
    if (revision === atRevision) statusNode.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

byId('upload-review').addEventListener('click', async () => {
  const file = byId('review-file').files[0];
  if (!file) {
    statusNode.textContent = '请先选择文件。';
    return;
  }
  clearVersions();
  const uploadRevision = revision;
  const button = byId('upload-review');
  button.disabled = true;
  statusNode.textContent = '正在本机解析材料…';
  const data = new FormData();
  data.set('file', file);
  data.set('task', byId('task').value);
  try {
    const response = await fetch('/api/upload', {method: 'POST', body: data});
    const result = await response.json();
    if (!response.ok) {
      throw new Error(typeof result.detail === 'string' ? result.detail : '材料上传失败。');
    }
    const sources = await fetch('/api/materials', {cache: 'no-store'});
    if (!sources.ok) throw new Error('材料已上传，但无法刷新材料列表。');
    config.materials = (await sources.json()).items;
    documents(true);
    if (uploadRevision === revision) {
      byId('document').value = result.doc_id;
      byId('review-file').value = '';
      statusNode.textContent = '材料已上传。';
    }
  } catch (error) {
    if (uploadRevision === revision) statusNode.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
byId('source-text').addEventListener('input', () => { byId('ocr-verified').checked = false; });
byId('ocr-review').addEventListener('click', async () => {
  const file = byId('review-file').files[0];
  if (!file || !/\.(pdf|png|jpe?g)$/i.test(file.name)) {
    statusNode.textContent = '请选择扫描 PDF、PNG 或 JPEG。';
    return;
  }
  const textField = byId('source-text');
  if (textField.value.trim() && !window.confirm('用识别草稿替换当前文本？')) return;
  clearVersions();
  const atRevision = revision;
  const button = byId('ocr-review');
  button.disabled = true;
  statusNode.textContent = '正在本机识别扫描件…';
  const body = new FormData();
  body.set('file', file);
  try {
    const response = await fetch('/api/ocr', {method: 'POST', body});
    const result = await response.json();
    if (!response.ok) {
      throw new Error(typeof result.detail === 'string' ? result.detail : '扫描识别失败。');
    }
    if (revision !== atRevision) return;
    byId('document').value = '';
    textField.value = result.text;
    const empty = result.pages.filter((page) => !page.lines.length).map((page) => page.page);
    const low = result.pages.reduce((sum, page) => sum + page.low_confidence, 0);
    byId('ocr-note').textContent = '识别 ' + result.pages.length + ' 页，低置信文本行 ' + low + ' 条。' +
      (empty.length ? ' 无识别结果的页面：' + empty.join('、') + '。' : '') + ' 请逐页核对原件。';
    byId('ocr-verified').checked = false;
    byId('ocr-check').hidden = false;
    statusNode.textContent = '识别草稿已填入，可以修订。';
  } catch (error) {
    if (revision === atRevision) statusNode.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
async function init() {
  const response = await fetch('/api/config', {cache: 'no-store'});
  if (!response.ok) throw new Error('无法加载任务与材料。');
  config = await response.json();
  for (const [key, value] of Object.entries(config.identities)) byId('identity').add(new Option(value.name, key));
  for (const [key, value] of Object.entries(config.tasks)) {
    if (key !== 'activity_notice') byId('task').add(new Option(value.name, key));
  }
  if (config.tasks.meeting_minutes) byId('task').value = 'meeting_minutes';
  for (const [key, value] of Object.entries(config.recipients)) {
    if (value.type !== 'VIEWER' && value.type !== 'EGRESS_TOOL') continue;
    const label = document.createElement('label');
    label.className = 'notice-check';
    const check = document.createElement('input');
    check.type = 'checkbox';
    check.name = 'recipient';
    check.value = key;
    check.checked = key === 'viewer_teacher' || key === 'viewer_peer';
    label.append(check, value.name);
    byId('recipients').append(label);
  }
  documents();
  byId('review-button').disabled = false;
  byId('upload-review').disabled = false;
  byId('ocr-review').disabled = false;
}
init().catch((error) => { statusNode.textContent = error.message; });
