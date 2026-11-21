"""用「人工标注 gold」评估识别器真实准确率。

与 eval/run_eval.py 的区别：后者用合成数据的自产 gold（会虚高），
本脚本用人工标注的 gold，得到可信的精确率 / 召回率 / F1。

用法：
    python scripts/eval_gold.py --gold data/gold/我的标注.json
    python scripts/eval_gold.py --gold data/gold/我的标注.json --show 20   # 显示更多错例
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

#  按敏感级别分层汇报：机构名（ORG）是 L1 最低档，它的标注缺口不该淹没
#  证件/密钥/金额这些真正高敏类别的表现。
LEVEL_GROUPS = [("L1 低", {1}), ("L2 中", {2}), ("L3-L4 高", {3, 4})]

from llm_shield.config import category_level  # noqa: E402  (需先 sys.path 注入)


def load_system_spans(text: str) -> list:
    """调用线上识别链路，返回系统判定的敏感片段。"""
    from llm_shield.m2_detect.pipeline import detect_all
    spans = detect_all(text)
    return [{'start': s.start, 'end': s.end, 'text': s.text,
             'category': s.category, 'confidence': getattr(s, 'confidence', 1.0),
             'detector': getattr(s, 'detector', '')} for s in spans]


def match(gold: list, pred: list, mode: str) -> tuple:
    """在指定口径下匹配，返回 (TP, FP, FN) 与错例明细。

    strict  : 类别相同且边界完全一致
    overlap : 类别相同且区间相交（与项目评测修复后的口径一致）
    cover   : 粒度无关口径。人工标注常把并列实体标成一整段
              （「李晓华、王芳、赵磊、陈静」是一个 PERSON_NAME 区间），
              而系统会逐个人名分别标注。overlap 口径下一个 gold 只能认领一个 pred，
              于是系统找对的另外 3 个人名被算成误报——这是标注粒度差异，不是识别错误。
              本口径允许一个 gold 区间吸收所有**完整落在其中**的同类别 pred，
              一个 gold 仍只记 1 次 TP（召回率不会超过 1）。
    """
    used = [False] * len(pred)
    tp = 0
    missed, spurious = [], []

    def same_cat(p, g):
        return p['category'] == g['category']

    for g in gold:
        if mode == 'cover':
            # ① 完整落在 gold 内的 pred 全部认领
            inside = [i for i, p in enumerate(pred)
                      if not used[i] and same_cat(p, g)
                      and g['start'] <= p['start'] and p['end'] <= g['end']]
            if inside:
                for i in inside:
                    used[i] = True
                tp += 1
                continue
        hit = -1
        for i, p in enumerate(pred):
            if used[i] or not same_cat(p, g):
                continue
            if mode == 'strict':
                ok = (p['start'] == g['start'] and p['end'] == g['end'])
            else:
                ok = (p['start'] < g['end'] and g['start'] < p['end'])
            if ok:
                hit = i
                break
        if hit >= 0:
            used[hit] = True
            tp += 1
        else:
            missed.append(g)
    for i, p in enumerate(pred):
        if not used[i]:
            spurious.append(p)
    return tp, len(spurious), len(missed), missed, spurious


def prf(tp: int, fp: int, fn: int) -> tuple:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--gold', type=Path, required=True, help='人工标注导出的 JSON')
    ap.add_argument('--out', type=Path, default=APP / 'data/gold/gold_eval_report.json')
    ap.add_argument('--show', type=int, default=8, help='每类显示的错例条数')
    ap.add_argument('--all-cases', action='store_true',
                    help='把「未标注」单元也纳入评测（其 gold 为空，系统检出全部记为误报）')
    args = ap.parse_args()

    if not args.gold.exists():
        print(f'[错误] 找不到 gold 文件：{args.gold}')
        return 1

    data = json.loads(args.gold.read_text(encoding='utf-8'))
    cases = data.get('cases') or []
    if not cases:
        print('[错误] gold 文件中没有 cases')
        return 1

    # 「人没标」不等于「没有实体」：未标注单元 gold 为空，纳入会把系统检出全记成误报，
    # 人为拉低精确率。默认只评已标注单元，未标注的单独统计。
    annotated = [c for c in cases if (c.get('entities') or [])]
    skipped = len(cases) - len(annotated)
    if not args.all_cases:
        cases = annotated

    report = {
        'schema': 1,
        'evaluated_at': datetime.now().isoformat(),
        'gold_file': str(args.gold),
        'annotator': data.get('annotator', ''),
        'cases': len(cases),
        'skipped_unannotated': skipped,
        'modes': {},
    }

    if not cases:
        print('[错误] 没有任何已标注的单元可供评测（未标注单元已跳过）')
        return 1

    # gold 中实际出现过的类别（用于 macro 平均，见下方 macro_f1 说明）
    gold_categories = {g['category'] for c in cases for g in (c.get('entities') or [])}

    for mode in ('cover', 'overlap', 'strict'):
        per_cat = defaultdict(lambda: {'tp': 0, 'fp': 0, 'fn': 0})
        details = defaultdict(lambda: {'missed': [], 'spurious': []})
        tot = {'tp': 0, 'fp': 0, 'fn': 0}

        for case in cases:
            text = case.get('text', '')
            gold_spans = case.get('entities') or []
            sys_spans = load_system_spans(text)
            cats = {g['category'] for g in gold_spans} | {p['category'] for p in sys_spans}
            for c in cats:
                g = [x for x in gold_spans if x['category'] == c]
                p = [x for x in sys_spans if x['category'] == c]
                tp, fp, fn, missed, spurious = match(g, p, mode)
                per_cat[c]['tp'] += tp
                per_cat[c]['fp'] += fp
                per_cat[c]['fn'] += fn
                tot['tp'] += tp
                tot['fp'] += fp
                tot['fn'] += fn
                details[c]['missed'] += [
                    {'case': case.get('id'), 'text': m.get('text')} for m in missed]
                details[c]['spurious'] += [
                    {'case': case.get('id'), 'text': s['text'],
                     'detector': s.get('detector', '')} for s in spurious]

        p, r, f = prf(tot['tp'], tot['fp'], tot['fn'])
        cats_summary = {}
        for c, v in sorted(per_cat.items()):
            cp, cr, cf = prf(v['tp'], v['fp'], v['fn'])
            cats_summary[c] = {'precision': round(cp, 4), 'recall': round(cr, 4),
                               'f1': round(cf, 4), 'tp': v['tp'], 'fp': v['fp'], 'fn': v['fn'],
                               'in_gold': c in gold_categories,
                               'missed': details[c]['missed'][:args.show],
                               'spurious': details[c]['spurious'][:args.show]}
        # macro-F1 只对「gold 里出现过的类别」求平均。
        # gold 从未标注的类别（本次为 ORG）召回率在数学上无定义：
        # 把它按 F1=0 计入，惩罚的是标注覆盖不全，而不是识别能力。
        scored = [v['f1'] for c, v in cats_summary.items() if c in gold_categories]
        macro_f1 = sum(scored) / len(scored) if scored else 0.0

        # 按敏感级别分层汇总
        by_level = {}
        for label, levels in LEVEL_GROUPS:
            agg = {'tp': 0, 'fp': 0, 'fn': 0}
            cats = []
            for c, v in cats_summary.items():
                if category_level(c) in levels:
                    agg['tp'] += v['tp']
                    agg['fp'] += v['fp']
                    agg['fn'] += v['fn']
                    cats.append(c)
            lp, lr, lf = prf(agg['tp'], agg['fp'], agg['fn'])
            by_level[label] = {
                'precision': round(lp, 4), 'recall': round(lr, 4), 'f1': round(lf, 4),
                'tp': agg['tp'], 'fp': agg['fp'], 'fn': agg['fn'],
                'categories': sorted(cats),
            }

        report['modes'][mode] = {
            'overall': {'precision': round(p, 4), 'recall': round(r, 4), 'f1': round(f, 4),
                        'tp': tot['tp'], 'fp': tot['fp'], 'fn': tot['fn']},
            'macro_f1': round(macro_f1, 4),
            'macro_f1_basis': sorted(gold_categories),
            'categories_without_gold': sorted(c for c in cats_summary
                                              if c not in gold_categories),
            'per_category': cats_summary,
            'by_level': by_level,
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    # ---- 控制台输出 ----
    print('=' * 68)
    print(f'  人工 gold 评测：{args.gold.name}   参评单元 {len(cases)} 条')
    print(f'  标注者：{report["annotator"] or "（未填写）"}')
    if report['skipped_unannotated']:
        print(f'  跳过未标注单元：{report["skipped_unannotated"]} 条'
              f'（加 --all-cases 可纳入，但会高估误报）')
    print('=' * 68)
    labels = {'cover': '粒度无关（推荐）', 'overlap': '区间相交', 'strict': '边界严格一致'}
    for mode in ('cover', 'overlap', 'strict'):
        m = report['modes'][mode]
        o = m['overall']
        print(f'\n  【{labels[mode]}口径】整体 P={o["precision"]:.4f}  '
              f'R={o["recall"]:.4f}  F1={o["f1"]:.4f}   '
              f'(TP={o["tp"]} FP={o["fp"]} FN={o["fn"]})')
        print(f'  macro-F1={m["macro_f1"]:.4f}（仅对 gold 出现过的 '
              f'{len(m["macro_f1_basis"])} 类求平均）')
        if m['categories_without_gold']:
            print(f'  ⚠ gold 未标注类别：{", ".join(m["categories_without_gold"])}'
                  f' —— 其检出全部计为误报，且不计入 macro-F1')
        print(f'  {'类别':<16}{'P':>8}{'R':>8}{'F1':>8}{'TP':>6}{'FP':>6}{'FN':>6}')
        print('  ' + '-' * 58)
        for c, v in sorted(m['per_category'].items(), key=lambda x: -x[1]['f1']):
            flag = '' if v['in_gold'] else '  (gold 未标注)'
            print(f'  {c:<16}{v["precision"]:>8.3f}{v["recall"]:>8.3f}'
                  f'{v["f1"]:>8.3f}{v["tp"]:>6}{v["fp"]:>6}{v["fn"]:>6}{flag}')
        print(f'\n  按敏感级别分层：')
        for label, lv in m['by_level'].items():
            print(f'    {label:<8} P={lv["precision"]:.3f}  R={lv["recall"]:.3f}  '
                  f'F1={lv["f1"]:.3f}   (TP={lv["tp"]} FP={lv["fp"]} FN={lv["fn"]})  '
                  f'{",".join(lv["categories"]) or "—"}')
    print('\n  报告已写入：' + str(args.out))
    print('  提示：FN=漏检（人标了系统没找到），FP=误报（系统多标）')
    print('=' * 68)
    return 0


if __name__ == '__main__':
    sys.exit(main())
