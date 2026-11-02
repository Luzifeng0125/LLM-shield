"""Synchronize navigation and verify the concrete 2026-10-31 research handoff."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'delivery/app/outputs/context_model_comparison_20261031'


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    comparison = json.loads((OUT / 'comparison.json').read_text(encoding='utf-8'))
    assert comparison['related_tests_passed'] == 52 and not comparison['production_promoted']
    nav = ROOT / '00_文件导航.html'
    text = nav.read_text(encoding='utf-8')
    replacements = {
        '当前使用自然文档 v3；旧模板与复核结果保留追溯。': '当前为长材料 v4.1，共27篇122处；旧138题人工结果保留。',
        '03_数据与人工复核/任务必要性复核_自然文档_v3_20261029/开始这里.md': '03_数据与人工复核/上下文长材料_v4_1_20261030/开始这里.md',
        'delivery/app/scripts/action_review.html': '03_数据与人工复核/上下文长材料_v4_1_20261030/打开复核.html',
        '03_数据与人工复核/任务必要性复核_自然文档_v3_20261029/review-first-batch.json': '03_数据与人工复核/上下文长材料_v4_1_20261030/review-task.json',
        '首批完整材料复核文件': '最新完整材料复核文件',
        '自然文档生成与质量筛选已更新；新样本仍待人工复核。': '长材料隐私判断已修订；新增122题仍为AI草稿。',
        '当前修改数据与复核流程，尚未训练或替换活动模型。': '已完成4份BERT候选微调与重载核验，未替换活动模型。<br><a href="04_技术文档/上下文语义微调_20261031.md">查看本轮微调结果</a> · <a href="进度.md">持续进度</a>',
    }
    for before, after in replacements.items():
        assert before in text or after in text, before
        text = text.replace(before, after)
    nav.write_text(text, encoding='utf-8')
    state_path = ROOT / '04_技术文档/执行状态.json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    state['latest_context_research'] = {
        'at': '2026-10-31', 'report': '04_技术文档/上下文语义微调_20261031.md',
        'review_entry': '03_数据与人工复核/上下文长材料_v4_1_20261030/开始这里.md',
        'documents': 27, 'privacy_decisions': 122, 'new_label_provenance': 'machine_draft',
        'actually_finetuned_bert_checkpoints': 4, 'checkpoints_reloaded_and_predictions_identical': 4,
        'related_tests_passed': 52, 'related_tests_scope': 'offline_data_review_chunk_encoding_contrast_boundaries',
        'review_ui_cases': 122, 'review_ui_verified': True,
        'preferred_offline_by_validation': comparison['preferred_offline_by_validation'],
        'active_models_changed': False, 'candidate_promoted': False,
        'remaining': ['隐私追问召回0/2', '医疗用途反转两边都正确0/2', '独立数据及真实业务验收',
                      '给定目标动作评测以外的敏感信息检测与最终改写验收'],
        'historical_sections': 'Other dated validation and optimization entries retain their original scope; they are not this run.',
    }
    write(state_path, state)
    protected = {
        'delivery/app/models/necessity_action.joblib': 'cbfed4ca422a1a6d416ce1b5f488649816c261b6acc86ffc173887c8dfed1b9f',
        'delivery/app/models/ACTIVE_MODELS.json': 'f7e27ea6060bc51e70429d967c5afb27a86726c9586f0b8dd03c7138da1af6c8',
    }
    for name, expected in protected.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    docs = [ROOT / p for p in [
        '04_技术文档/上下文语义微调_20261031.md', 'README.md',
        '03_数据与人工复核/上下文长材料_v4_1_20261030/开始这里.md',
        'delivery/app/outputs/context_bert_experiment_20261030_v1/开始这里.md',
        'delivery/app/outputs/context_bert_experiment_20261030_v2_contrast/开始这里.md',
        'delivery/app/outputs/context_model_comparison_20261031/开始这里.md',
    ]]
    checked = []
    for doc in docs:
        for ref in re.findall(r'\]\(([^)]+)\)', doc.read_text(encoding='utf-8')):
            if re.match(r'https?://|#', ref):
                continue
            target = (doc.parent / unquote(ref.split('#')[0])).resolve()
            assert target.exists(), f'{doc}: missing {ref}'
            checked.append(str(target.relative_to(ROOT)))
    for ref in re.findall(r'href="([^"]+)"', nav.read_text(encoding='utf-8')):
        if not re.match(r'https?://|#', ref):
            assert (ROOT / unquote(ref)).exists(), ref
    result = {'passed': True, 'date': '2026-10-31', 'local_document_links_checked': len(checked),
              'navigation_links_exist': True, 'active_models_unchanged': True,
              'source_reports_untouched': all(hashlib.sha256((ROOT / row['report_path']).read_bytes()).hexdigest() == comparison['reports_sha256'][row['experiment']] for row in comparison['rows'])}
    assert result['source_reports_untouched']
    write(OUT / 'handoff_verification.json', result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
