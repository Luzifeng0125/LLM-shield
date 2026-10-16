"""生成「实体级人工 gold 标注」任务文件。

背景：现有识别指标（F1 0.9652）使用的 gold 由合成数据生成器自产，
用它自评必然虚高。本脚本抽取待标注文本，产出人工标注任务，
由人标注实体边界与类别后，再用 eval_gold.py 计算真实准确率。

用法：
    python scripts/build_gold_task.py
    python scripts/build_gold_task.py --extra 我的材料.txt   # 追加自定义材料
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

INSTRUCTION = (
    "请逐条阅读文本，标出其中所有应当受保护的敏感信息片段，并指定类别。\n"
    "标注要点：\n"
    "1. 只标「敏感信息」本身，不要连带标签名（例如「预算：35000元」只标「35000元」）；\n"
    "2. 边界取完整片段，不要截断（手机号 11 位要标全）；\n"
    "3. 同一片段只归一个最贴切的类别；\n"
    "4. 不确定的标为「存疑」并在备注说明，不要凭猜测硬标；\n"
    "5. 机构名、地点等低敏感类别同样需要标注，用于评估误报。"
)


def load_categories() -> dict:
    """从 config/rules.yaml 读取类别名，保证与系统一致。"""
    import yaml
    rules = yaml.safe_load((APP / 'config/rules.yaml').read_text(encoding='utf-8'))
    cats = rules.get('categories', {})
    return {k: v.get('name', k) for k, v in cats.items()}


def collect_cases() -> list:
    """抽取待标注文本：内置示例材料 + 合成试标单元。"""
    cases: list = []
    # 内置示例材料（虚构但贴近真实校园材料）
    for p in sorted((APP / 'data/fixtures').glob('*.json')):
        d = json.loads(p.read_text(encoding='utf-8'))
        text = (d.get('text') or '').strip()
        if text:
            cases.append({
                'id': f"fixture:{d.get('doc_id') or p.stem}",
                'source': p.name,
                'text': text,
            })
    # 合成试标单元（每个对话轮次作为一个标注单元）
    tp = APP / 'data/review/trial_cases.json'
    if tp.exists():
        for c in json.loads(tp.read_text(encoding='utf-8')):
            for i, turn in enumerate(c.get('turns', []), 1):
                turn = (turn or '').strip()
                if turn:
                    cases.append({
                        'id': f"trial:{c['id']}-t{i}",
                        'source': 'trial_cases.json',
                        'text': turn,
                    })
    return cases


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--extra', type=Path, default=None,
                    help='追加自定义材料（.txt 按空行分段，或每行为一段）')
    ap.add_argument('--out', type=Path, default=APP / 'data/gold/gold_task.json')
    args = ap.parse_args()

    cases = collect_cases()

    if args.extra:
        if not args.extra.exists():
            print(f'[错误] 找不到文件：{args.extra}')
            return 1
        raw = args.extra.read_text(encoding='utf-8')
        blocks = [b.strip() for b in raw.split('\n\n') if b.strip()]
        for i, b in enumerate(blocks, 1):
            cases.append({'id': f"extra:{args.extra.stem}-{i}",
                          'source': args.extra.name, 'text': b})

    if not cases:
        print('[错误] 没有抽取到任何待标注文本')
        return 1

    task = {
        'schema': 1,
        'type': 'human_gold_entity_annotation',
        'created': date.today().isoformat(),
        'instruction': INSTRUCTION,
        'categories': load_categories(),
        'cases': cases,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding='utf-8')

    corpus = '\n'.join(c['text'] for c in cases)
    print('=' * 62)
    print('  实体级人工 gold 标注任务已生成')
    print(f'  输出：{args.out}')
    print(f'  待标注单元：{len(cases)} 条')
    print(f'  总字符数：{len(corpus)}')
    print(f'  类别数：{len(task["categories"])}')
    print(f'  语料指纹 sha256：{hashlib.sha256(corpus.encode("utf-8")).hexdigest()[:16]}')
    print('  下一步：用浏览器打开 scripts/gold_annotate.html 载入本文件开始标注')
    print('=' * 62)
    return 0


if __name__ == '__main__':
    sys.exit(main())
