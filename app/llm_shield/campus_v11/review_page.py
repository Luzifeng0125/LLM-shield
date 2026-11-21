"""生成离线复核页。

校准页可以直接显示 AI 建议。试测和正式测试的首答页不写入建议正文；
建议留在独立文件，初答导出之后才能生成对照页。页面不使用长期浏览器存储。
"""
from __future__ import annotations

import html
import json
from typing import Any, Dict, Mapping, Sequence

from ..schema import Action

ACTIONS = [action.value for action in Action]
ACTION_LABELS = {
    "DELETE": "删除（DELETE）",
    "LOCAL_AGGREGATE": "本地汇总（LOCAL_AGGREGATE）",
    "GENERALIZE": "泛化（GENERALIZE）",
    "PSEUDONYMIZE": "稳定代号（PSEUDONYMIZE）",
    "RETAIN": "原文保留（RETAIN）",
    "PAUSE": "暂停（PAUSE）",
}
WORKFLOW_TITLES = {
    "class_coordination": "班级协作",
    "coursework_grades": "课程沟通",
    "teacher_counselor_handoff": "师生交接",
    "club_membership": "社团统计",
    "student_events": "活动宣传",
    "awards_financial_aid": "奖助公开说明",
    "campus_services": "校园报修",
    "minutes_reports_statistics": "会议纪要",
}


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _options(selected: str = "") -> str:
    parts = ["<option value=''>请选择</option>"]
    for action in ACTIONS:
        mark = " selected" if action == selected else ""
        parts.append(f"<option value='{_esc(action)}'{mark}>{_esc(ACTION_LABELS.get(action, action))}</option>")
    return "".join(parts)


def _heading(document: Mapping[str, Any]) -> str:
    audit = document.get("audit_metadata") if isinstance(document.get("audit_metadata"), Mapping) else {}
    workflow = audit.get("workflow") if isinstance(audit, Mapping) else None
    name = WORKFLOW_TITLES.get(workflow) if isinstance(workflow, str) else None
    document_id = str(document["document_id"])
    return f"{document_id}　{name}" if name else document_id


def _units(document: Mapping[str, Any], show_suggestions: bool, show_targets: bool) -> str:
    blocks = []
    for unit in document["annotation"]["units"]:
        key = f"{document['document_id']}:{unit['information_unit_id']}"
        target = f"<p>片段：{_esc(unit.get('quote'))}</p>" if show_targets else ""
        suggestion = ""
        if show_suggestions:
            if unit.get("representational_gap") is True:
                suggestion = "<p class='hint'>AI 初审：现有六类动作表达不了这个要求，这是能力缺口，不要改成暂停来凑数。</p>"
            else:
                suggestion = (
                    f"<p class='hint'>AI 建议动作：{_esc(ACTION_LABELS.get(str(unit.get('canonical_action')), unit.get('canonical_action')))}。"
                    f"必要事实：{_esc(unit.get('required_facts'))}</p>"
                )
        blocks.append(f"""
        <section class='unit'>
          <h3>{_esc(unit['information_unit_id'])}</h3>
          {target}
          <p>边界：{_esc(unit.get('boundary_id'))}；接收方：{_esc(unit.get('recipient_id'))}</p>
          {suggestion}
          <label>最终动作 <select name='action:{_esc(key)}'>{_options()}</select></label>
          <label>必要事实 <textarea name='facts:{_esc(key)}'></textarea></label>
        </section>""")
    return "".join(blocks)


def _page(title: str, intro: str, documents: Sequence[Mapping[str, Any]], show_suggestions: bool, show_targets: bool) -> str:
    cards = []
    total = len(documents)
    for index, document in enumerate(documents):
        runtime = document["runtime_input"]
        active = " is-active" if index == 0 else ""
        cards.append(f"""
        <article class='doc{active}' data-index='{index}'>
          <header class='doc-head'>
            <p class='intro'>{_esc(intro)}</p>
            <h1>{_esc(_heading(document))}</h1>
            <p class='need'><span>需求</span>{_esc(runtime.get('user_task'))}</p>
            <pre class='passage'>{_esc(runtime.get('text'))}</pre>
          </header>
          <div class='doc-units'>
            {_units(document, show_suggestions, show_targets)}
          </div>
        </article>""")
    role = "calibration" if show_suggestions else "pilot"
    return f"""<!DOCTYPE html>
<html lang='zh-CN'>
<head>
  <meta charset='utf-8'>
  <title>{_esc(title)}</title>
  <style>
    html, body {{ height: 100%; }}
    body {{ margin: 0; overflow: hidden; font: 16px/1.5 "Segoe UI", sans-serif; color: #1c1c1c; background: #f7f7f7; }}
    .shell {{ height: 100vh; height: 100dvh; display: flex; flex-direction: column; min-height: 0; overflow: hidden; }}
    form.shell {{ height: 100%; }}
    .doc {{ display: none; min-height: 0; background: #fff; }}
    .doc.is-active {{ display: flex; flex: 1 1 auto; flex-direction: column; min-height: 0; overflow: hidden; }}
    .doc-head {{ flex: 0 1 auto; min-height: 0; display: flex; flex-direction: column; overflow: hidden; padding: 0.85rem 1.4rem 0.75rem; background: #fff; border-bottom: 1px solid #ddd; }}
    .intro {{ margin: 0 0 0.35rem; color: #555; font-size: 0.92rem; flex: 0 0 auto; }}
    .doc-head h1 {{ margin: 0; font-size: 1.9rem; line-height: 1.25; flex: 0 0 auto; }}
    .need {{ margin: 0.45rem 0 0.55rem; flex: 0 0 auto; }}
    .need span {{ display: inline-block; margin-right: 0.45rem; font-weight: 700; }}
    .passage {{ margin: 0; flex: 1 1 auto; min-height: 0; white-space: pre-wrap; background: #f4f4f4; padding: 0.65rem 0.8rem; overflow: auto; font: 15px/1.45 "Segoe UI", sans-serif; }}
    .doc-units {{ flex: 1 0 11rem; min-height: 11rem; overflow-y: auto; padding: 0.35rem 1.4rem 1rem; }}
    .unit {{ border-top: 1px solid #ddd; padding-top: 0.75rem; margin-top: 0.75rem; }}
    .unit h3 {{ margin: 0 0 0.35rem; font-size: 1.15rem; }}
    label {{ display: block; margin: 0.5rem 0; }}
    textarea, select {{ width: 100%; max-width: 46rem; box-sizing: border-box; }}
    textarea {{ min-height: 4.5rem; }}
    .bar {{ flex: 0 0 auto; display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; padding: 0.6rem 1.4rem; border-top: 1px solid #ddd; background: #fff; }}
    .bar p {{ margin: 0; }}
    button {{ font: inherit; padding: 0.35rem 0.8rem; }}
    @media (max-width: 390px) {{
      .doc-head, .doc-units, .bar {{ padding-left: 0.75rem; padding-right: 0.75rem; }}
      .doc-head h1 {{ font-size: 1.35rem; }}
    }}
  </style>
</head>
<body>
<div class='shell'>
  <form id='review' class='shell'>
    {''.join(cards)}
    <div class='bar'>
      <button type='button' id='prev'>上一篇</button>
      <span id='pos'>1 / {total}</span>
      <button type='button' id='next'>下一篇</button>
      <button type='button' id='export'>导出当前答案</button>
      <p id='status'>尚未导出。</p>
    </div>
  </form>
</div>
<script>
const ROLE = {json.dumps(role)};
const pages = Array.from(document.querySelectorAll('.doc'));
let index = 0;
function show(next) {{
  index = Math.max(0, Math.min(pages.length - 1, next));
  pages.forEach((page, number) => page.classList.toggle('is-active', number === index));
  document.getElementById('pos').textContent = (index + 1) + ' / ' + pages.length;
  document.getElementById('prev').disabled = index === 0;
  document.getElementById('next').disabled = index === pages.length - 1;
  const units = pages[index].querySelector('.doc-units');
  if (units) units.scrollTop = 0;
}}
document.getElementById('prev').addEventListener('click', () => show(index - 1));
document.getElementById('next').addEventListener('click', () => show(index + 1));
show(0);
document.getElementById('export').addEventListener('click', () => {{
  const data = new FormData(document.getElementById('review'));
  const items = [];
  for (const [name, value] of data.entries()) {{
    if (!name.startsWith('action:')) continue;
    const key = name.slice(7);
    const facts = data.get('facts:' + key) || '';
    if (!value || !String(facts).trim()) {{
      document.getElementById('status').textContent = '还有题目没有动作或必要事实，未导出。';
      return;
    }}
    items.push({{
      decision_key: key,
      initial_answer: ROLE === 'pilot' ? {{canonical_action: value, required_facts: facts}} : null,
      final_answer: {{canonical_action: value, required_facts: facts}},
      ai_suggestion_seen: ROLE !== 'pilot'
    }});
  }}
  const payload = {{
    schema: 'campus-review-return-v1.1',
    policy_version: 'campus-min-disclosure-v1.1',
    pack_role: ROLE,
    items
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{type: 'application/json'}});
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = ROLE + '-return.json';
  link.click();
  URL.revokeObjectURL(link.href);
  document.getElementById('status').textContent = '已导出。页面没有把答案写入浏览器长期存储。';
}});
</script>
</body>
</html>
"""


def build_calibration_page(documents: Sequence[Mapping[str, Any]]) -> str:
    return _page(
        "校园校准复核",
        "这是 AI 初审草稿。校准材料可以直接看建议；导出的答案要由你返还后才按人工审核接收。下拉框里的「稳定代号」只记录动作名称，不会生成编号。系统里已有的代号只用于姓名和机构，形式是「人员甲」「组织甲」，而且要等在线处理真正选择该动作才会分配。电话、邮箱、宿舍目前不会变成可逆编号。",
        documents,
        True,
        True,
    )


def build_hidden_initial_page(documents: Sequence[Mapping[str, Any]], *, show_targets: bool = True) -> str:
    page = _page(
        "校园测试首答",
        "请先独立填写。本页不含 AI 建议；导出初答后，才能用单独的建议文件做对照。",
        documents,
        False,
        show_targets,
    )
    if "AI 建议动作" in page or "能力缺口" in page:
        raise ValueError("首答页写入了 AI 建议")
    return page


def suggestion_file(documents: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    suggestions = []
    for document in documents:
        for unit in document["annotation"]["units"]:
            suggestions.append({
                "decision_key": f"{document['document_id']}:{unit['information_unit_id']}",
                "canonical_action": unit.get("canonical_action"),
                "required_facts": unit.get("required_facts"),
                "representational_gap": unit.get("representational_gap") is True,
            })
    return {"schema": "campus-ai-suggestions-v1.1", "items": suggestions}


def build_reveal_page(initial_export: Mapping[str, Any], suggestions: Mapping[str, Any]) -> str:
    """初答里的每个题目都有动作之后，才允许把建议和初答并排显示。"""
    items = initial_export.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("没有初答，不能展示建议")
    for item in items:
        initial = item.get("initial_answer") if isinstance(item, Mapping) else None
        if not isinstance(initial, Mapping) or initial.get("canonical_action") not in ACTIONS:
            raise ValueError("初答不完整，不能展示建议")
    return "<!DOCTYPE html><html lang='zh-CN'><meta charset='utf-8'><title>初答后的建议对照</title><pre>" + _esc(
        json.dumps({"initial": initial_export, "suggestions": suggestions}, ensure_ascii=False, indent=2)
    ) + "</pre></html>"
