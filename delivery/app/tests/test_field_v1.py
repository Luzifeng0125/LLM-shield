"""field_v1 独立评测集回归测试（独立脚本，可直接运行）。

作用：把「只报旧留出集分数」这种自欺从流程上堵死。任何识别层改动都必须
同时看两把尺子：data/gold_v3（保精度）与 data/field_v1（保独立性）。

默认只跑不加载模型的快速项（纯正则+词典），秒级完成；
设置 SHIELD_TEST_GLINER=1 且权重存在时，追加 GLiNER 相关项（约 1 分钟）。

用法：
    python tests/test_field_v1.py
    SHIELD_TEST_GLINER=1 python tests/test_field_v1.py     # Windows: $env:SHIELD_TEST_GLINER=1
"""
from __future__ import annotations

import collections
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from eval_gold import match, prf                       # noqa: E402  复用同一套匹配口径
from llm_shield.config import category_level           # noqa: E402
from llm_shield.m2_detect.pipeline import build_detectors, detect_all   # noqa: E402

FIELD = ROOT / "data" / "field_v1" / "field_v1.jsonl"
FAIL = []


def check(name, cond, detail=""):
    if not cond:
        FAIL.append(name)
    print("  %s %s%s" % ("OK " if cond else "FAIL", name,
                         ("  [%s]" % detail) if detail else ""))


def load_field():
    rows = []
    for line in FIELD.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows.append({"id": r["id"], "text": r["text"],
                         "entities": r["annotation"]["entities"]})
    return rows


def predict(text, detectors):
    return [{"start": s.start, "end": s.end, "text": text[s.start:s.end],
             "category": s.category, "confidence": s.confidence,
             "detector": s.detector} for s in detect_all(text, detectors=detectors)]


def score(cases, detectors):
    """按粒度无关（cover）口径汇总，返回 (P, R, F1, TP, FP, FN) 与逐类别计数。"""
    per = collections.defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for c in cases:
        gold, pred = c["entities"], predict(c["text"], detectors)
        for cat in {g["category"] for g in gold} | {p["category"] for p in pred}:
            g = [x for x in gold if x["category"] == cat]
            p = [x for x in pred if x["category"] == cat]
            tp, fp, fn, _m, _s = match(g, p, "cover")
            per[cat]["tp"] += tp
            per[cat]["fp"] += fp
            per[cat]["fn"] += fn
    tot = {k: sum(v[k] for v in per.values()) for k in ("tp", "fp", "fn")}
    p_, r_, f_ = prf(tot["tp"], tot["fp"], tot["fn"])
    return (p_, r_, f_, tot["tp"], tot["fp"], tot["fn"]), per


def negatives_with_fp(cases, detectors):
    n = 0
    for c in cases:
        if not c["entities"] and predict(c["text"], detectors):
            n += 1
    return n


def main():
    cases = load_field()
    n_ent = sum(len(c["entities"]) for c in cases)
    n_neg = sum(1 for c in cases if not c["entities"])

    print("=== 1. 数据集完整性 ===")
    check("记录数 87", len(cases) == 87, "实际 %d" % len(cases))
    check("实体数 149", n_ent == 149, "实际 %d" % n_ent)
    check("纯负例 17 条", n_neg == 17, "实际 %d" % n_neg)
    bad = [c["id"] for c in cases for e in c["entities"]
           if c["text"][e["start"]:e["end"]] != e["text"]]
    check("全部实体偏移自洽", not bad, "异常 %s" % bad[:3])
    cats = {e["category"] for c in cases for e in c["entities"]}
    check("覆盖全部 14 个类别", len(cats) == 14, "实际 %d" % len(cats))

    print("=== 2. 带分隔符手机号（修复回归守卫） ===")
    dets = build_detectors(use_gliner=False)
    for raw in ("150 0278 7488", "138-1234-5678", "13812345678"):
        got = [s.text for s in detect_all("联系电话：" + raw, detectors=dets)
               if s.category == "PHONE"]
        check("识别 %r" % raw, raw in got, "实际 %s" % got)
    got5 = [s.text for s in detect_all("校园服务热线12345", detectors=dets)]
    check("5 位热线 12345 不被误报", not got5, "实际 %s" % got5)

    print("=== 3. 基线（纯正则+词典）在 field_v1 上 ===")
    (p_, r_, f_, tp, fp, fn), per = score(cases, dets)
    print("     P=%.4f R=%.4f F1=%.4f (TP %d FP %d FN %d)" % (p_, r_, f_, tp, fp, fn))
    check("cover F1 >= 0.72", f_ >= 0.72, "%.4f" % f_)
    # 高敏类别：基线本来就强，给一个更紧的下限防止被"模型增强"拖垮
    hi = {k: v for k, v in per.items() if category_level(k) >= 3}
    ht = {k: sum(x[k] for x in hi.values()) for k in ("tp", "fp", "fn")}
    hf = prf(ht["tp"], ht["fp"], ht["fn"])[2]
    print("     L3-L4 高敏 F1=%.4f" % hf)
    check("L3-L4 高敏 F1 >= 0.82", hf >= 0.82, "%.4f" % hf)
    # 有校验位的类别必须几乎全召回：漏掉身份证/银行卡是安全事故，不是精度问题
    for cat in ("ID_CARD", "BANK_CARD"):
        v = per.get(cat, {"tp": 0, "fn": 0})
        rec = v["tp"] / (v["tp"] + v["fn"]) if (v["tp"] + v["fn"]) else 0.0
        check("%s 召回 = 1.0（校验位权威判定）" % cat, rec == 1.0, "%.3f" % rec)
    nf = negatives_with_fp(cases, dets)
    check("纯负例误报 <= 5 条", nf <= 5, "%d/%d" % (nf, n_neg))

    if os.getenv("SHIELD_TEST_GLINER", "").strip().lower() in ("1", "true", "yes", "on"):
        print("=== 4. GLiNER（仅语义类）在 field_v1 上 ===")
        from llm_shield.m2_detect.entity_rules import EntityDetector
        from llm_shield.m2_detect.gliner_ner import GLiNERDetector, SEMANTIC_CATEGORIES
        from llm_shield.m2_detect.regex_rules import RegexDetector
        gd = GLiNERDetector(categories=SEMANTIC_CATEGORIES)
        if not gd.available:
            check("GLiNER 权重可用", False, gd.reason)
        else:
            gdets = [RegexDetector(), EntityDetector(detect_org_location=False), gd]
            (gp, gr, gf, gtp, gfp, gfn), _gper = score(cases, gdets)
            print("     P=%.4f R=%.4f F1=%.4f (TP %d FP %d FN %d)"
                  % (gp, gr, gf, gtp, gfp, gfn))
            check("GLiNER 语义类 cover F1 >= 0.85", gf >= 0.85, "%.4f" % gf)
            check("GLiNER 语义类召回 > 基线召回", gr > r_, "%.4f vs %.4f" % (gr, r_))
            gnf = negatives_with_fp(cases, gdets)
            check("纯负例误报 <= 12 条", gnf <= 12, "%d/%d" % (gnf, n_neg))
    else:
        print("=== 4. GLiNER 项已跳过（设 SHIELD_TEST_GLINER=1 启用） ===")

    print()
    if FAIL:
        print("失败 %d 项: %s" % (len(FAIL), FAIL))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
