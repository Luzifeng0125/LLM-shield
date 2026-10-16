"""在「独立手写评测集 field_v1」上评测识别层，并与旧模板留出集对照。

为什么需要这个脚本
------------------
``scripts/eval_gold.py`` 评的是 data/gold_v3 —— 那 312 条与训练语料同源生成：
实测 80 条 test 中有 63 条与训练集存在 8-gram 重合（78.8%），实体取值几乎不重复
（PERSON_NAME 112 次命中 112 个不同取值、LOCATION 32 次命中仅 20 个取值），
身份证一律 999999 开头、邮箱一律 @example.invalid。
在它上面得到的 F1 衡量的是「是否背下模板」，不是「是否理解上下文」。

field_v1 是 87 条手写场景文本（班群通知/会议纪要/邮件/报销单/档案登记/聊天），
刻意打破上述全部捷径：真实地区码、真实 BIN+Luhn、真实域名、真实号段、
复姓与少数民族姓名、以及大量数值诱饵（日期/教室号/人数/票数/阈值/热线）
与姓名假阳性诱饵（张罗、王者荣耀）。与训练语料的 8-gram 重合率仅 2.4%。

用法：:

    python scripts/eval_field_v1.py                 # 两个数据集 × 两种配置
    python scripts/eval_field_v1.py --dataset field # 只评 field_v1
    python scripts/eval_field_v1.py --no-compare    # 不评旧的 gold_v3 test

产物：data/field_v1/eval_report.json 与 data/field_v1/eval_report.md
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from datetime import datetime
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "scripts"))

from eval_gold import LEVEL_GROUPS, match, prf          # noqa: E402  复用同一套匹配口径
from llm_shield.config import category_level            # noqa: E402
from llm_shield.m2_detect.entity_rules import EntityDetector            # noqa: E402
from llm_shield.m2_detect.gliner_ner import (                           # noqa: E402
    GLiNERDetector, SEMANTIC_CATEGORIES)
from llm_shield.m2_detect.pipeline import build_detectors, detect_all   # noqa: E402
from llm_shield.m2_detect.regex_rules import RegexDetector              # noqa: E402

CONFIGS = [
    ("配置 1｜纯正则 + 词典（基线）", "base"),
    ("配置 2｜+ GLiNER v3（默认 13 类）", "gliner_all"),
    ("配置 3｜+ GLiNER v3（仅 5 个语义类）", "gliner_semantic"),
]


def make_detectors(kind: str):
    """按配置构建识别器链；返回 (detectors, 说明)。"""
    if kind == "base":
        return build_detectors(use_gliner=False), ""
    if kind == "gliner_all":
        dets = build_detectors(use_gliner=True)
    else:
        # 只让 GLiNER 负责语义类，格式类（电话/邮箱/学号/证件/银行卡/密钥/
        # 微信/预算/成绩）交回正则底座——这些类别正则有校验位与边界断言，
        # 精度高于概率模型。GLiNER 的增量价值应集中在人名/机构/地点/宿舍/
        # 敏感属性上，而不是覆盖正则已经做对的部分。
        dets = [RegexDetector(), EntityDetector(detect_org_location=False),
                GLiNERDetector(categories=SEMANTIC_CATEGORIES)]
    gl = next((d for d in dets if isinstance(d, GLiNERDetector)), None)
    return dets, (gl.reason if gl else "")

FIELD_JSONL = APP / "data" / "field_v1" / "field_v1.jsonl"
OLD_GOLD_DIR = APP / "data" / "gold_v3" / "gold"
OUT_DIR = APP / "data" / "field_v1"
MODES = ("cover", "overlap", "strict")
MODE_LABEL = {"cover": "粒度无关（推荐）", "overlap": "区间相交", "strict": "边界严格一致"}

_buf: list = []


def w(line: str = "") -> None:
    _buf.append(line)


# ------------------------------------------------------------------ 数据装载


def cases_from_jsonl(path: Path) -> list:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        out.append({"id": r["id"], "text": r["text"],
                    "scenario": r.get("scenario", ""),
                    "entities": r["annotation"]["entities"]})
    return out


def cases_from_gold(path: Path) -> list:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if not r.get("text"):
            continue
        out.append({"id": r["id"], "text": r["text"], "scenario": "",
                    "entities": r["annotation"]["entities"]})
    return out


# ------------------------------------------------------------------ 评测


def predict(case: dict, detectors) -> list:
    spans = detect_all(case["text"], detectors=detectors)
    return [{"start": s.start, "end": s.end, "text": case["text"][s.start:s.end],
             "category": s.category, "confidence": round(s.confidence, 3),
             "detector": s.detector} for s in spans]


def evaluate(cases: list, detectors, label: str) -> dict:
    """按 3 种口径评测；同时记录误报结构。"""
    preds_by_case = {}
    t0 = time.time()
    for c in cases:
        preds_by_case[c["id"]] = predict(c, detectors)
    elapsed = (time.time() - t0) * 1000

    res = {"label": label, "n_cases": len(cases), "total_ms": round(elapsed, 1),
           "modes": {}}
    gold_cats_all = {e["category"] for c in cases for e in c["entities"]}

    for mode in MODES:
        per_cat = collections.defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
        details = collections.defaultdict(lambda: {"missed": [], "spurious": []})
        neg_total = neg_hit = 0
        for c in cases:
            gold = c["entities"]
            pred = preds_by_case[c["id"]]
            if not gold:
                # gold 为空的记录上，任何预测都是误报
                neg_total += 1
                if pred:
                    neg_hit += 1
            for cat in {g["category"] for g in gold} | {p["category"] for p in pred}:
                g = [x for x in gold if x["category"] == cat]
                p = [x for x in pred if x["category"] == cat]
                tp, fp, fn, missed, spurious = match(g, p, mode)
                per_cat[cat]["tp"] += tp
                per_cat[cat]["fp"] += fp
                per_cat[cat]["fn"] += fn
                details[cat]["missed"] += [
                    {"case": c["id"], "scenario": c["scenario"], "text": m.get("text"),
                     "context": c["text"]} for m in missed]
                details[cat]["spurious"] += [
                    {"case": c["id"], "scenario": c["scenario"], "text": s["text"],
                     "detector": s.get("detector", ""), "confidence": s.get("confidence"),
                     "context": c["text"]} for s in spurious]
        tot = {k: sum(v[k] for v in per_cat.values()) for k in ("tp", "fp", "fn")}
        p_, r_, f_ = prf(tot["tp"], tot["fp"], tot["fn"])
        cats = {}
        for cat, v in sorted(per_cat.items()):
            cp, cr, cf = prf(v["tp"], v["fp"], v["fn"])
            cats[cat] = {"precision": round(cp, 4), "recall": round(cr, 4),
                         "f1": round(cf, 4), "tp": v["tp"], "fp": v["fp"], "fn": v["fn"],
                         "in_gold": cat in gold_cats_all,
                         "missed": details[cat]["missed"][:6],
                         "spurious": details[cat]["spurious"][:6]}
        scored = [v["f1"] for k, v in cats.items() if k in gold_cats_all]
        by_level = {}
        for lname, levels in LEVEL_GROUPS:
            agg = {"tp": 0, "fp": 0, "fn": 0}
            lv_cats = []
            for cat, v in cats.items():
                if category_level(cat) in levels:
                    for k in agg:
                        agg[k] += v[k]
                    lv_cats.append(cat)
            lp, lr, lf = prf(agg["tp"], agg["fp"], agg["fn"])
            by_level[lname] = {"precision": round(lp, 4), "recall": round(lr, 4),
                               "f1": round(lf, 4), **agg, "categories": sorted(lv_cats)}
        res["modes"][mode] = {
            "overall": {"precision": round(p_, 4), "recall": round(r_, 4),
                        "f1": round(f_, 4), **tot},
            "macro_f1": round(sum(scored) / len(scored), 4) if scored else 0.0,
            "per_category": cats, "by_level": by_level,
            "negative_total": neg_total, "negative_with_fp": neg_hit,
        }
    return res


def diagnose(cases: list, preds: dict) -> dict:
    """把预测拆成：严格正确 / 仅边界错 / 类别串扰 / 完全虚构。"""
    out = {"strict": 0, "boundary": 0, "cross": 0, "hallu": 0,
           "cross_pairs": collections.Counter(), "hallu_items": collections.Counter(),
           "fp_by_detector": collections.Counter(), "cross_items": []}
    for c in cases:
        gold, pred = c["entities"], preds[c["id"]]
        _t, _f, _n, _m, _s = match(gold, pred, "strict")
        out["strict"] += _t
        r_tp, _rf, _rn, _rm, spurious = match(gold, pred, "overlap")
        out["boundary"] += r_tp - _t
        for p in spurious:
            hit = [g for g in gold if g["start"] < p["end"] and p["start"] < g["end"]]
            if hit:
                out["cross"] += 1
                out["cross_pairs"]["%s→%s" % (hit[0]["category"], p["category"])] += 1
                out["cross_items"].append({"case": c["id"], "gold": hit[0]["text"],
                                           "gold_cat": hit[0]["category"],
                                           "pred": p["text"], "pred_cat": p["category"],
                                           "context": c["text"]})
            else:
                out["hallu"] += 1
                out["hallu_items"]["%s|%s" % (p["category"], p["text"])] += 1
            out["fp_by_detector"][p["detector"]] += 1
    return out


# ------------------------------------------------------------------ 报告


def emit(evaluated: dict, diagnoses: dict, args) -> None:
    w("=" * 74)
    w("隐盾 v3 识别层 —— 独立手写评测集 field_v1 评测报告")
    w("=" * 74)
    w()
    w("生成时间：%s" % datetime.now().isoformat(timespec="seconds"))
    w()
    for name, data in evaluated.items():
        w("- **%s**：%d 条 / %d 个实体 / 纯负例 %d 条"
          % (name, len(data["cases"]), sum(len(c["entities"]) for c in data["cases"]),
             sum(1 for c in data["cases"] if not c["entities"])))
    w()

    for dsname, data in evaluated.items():
        w("#" * 74)
        w("# 数据集 %s" % dsname)
        w("#" * 74)
        w()
        if data.get("independence"):
            w("独立性：%s" % data["independence"])
            w()
        for cfgname, res in data["results"].items():
            w("## %s" % cfgname)
            w()
            w("| 口径 | P | R | F1 | TP | FP | FN | 纯负例误报 |")
            w("|---|---|---|---|---|---|---|---|")
            for mode in MODES:
                m = res["modes"][mode]
                o = m["overall"]
                w("| %s | %.4f | %.4f | **%.4f** | %d | %d | %d | %d/%d 条 |"
                  % (MODE_LABEL[mode], o["precision"], o["recall"], o["f1"],
                     o["tp"], o["fp"], o["fn"], m["negative_with_fp"], m["negative_total"]))
            w()
            w("宏平均 F1：%s"
              % " / ".join("%s %.4f" % (MODE_LABEL[m], res["modes"][m]["macro_f1"])
                           for m in MODES))
            w()
            cov = res["modes"]["cover"]
            w("逐类别（粒度无关口径）：")
            w()
            w("| 类别 | P | R | F1 | TP | FP | FN |")
            w("|---|---|---|---|---|---|---|")
            for cat, v in sorted(cov["per_category"].items(), key=lambda x: x[1]["f1"]):
                w("| %s | %.3f | %.3f | %.3f | %d | %d | %d |"
                  % (cat, v["precision"], v["recall"], v["f1"], v["tp"], v["fp"], v["fn"]))
            w()
            w("按敏感级别分层（粒度无关口径）：")
            w()
            w("| 级别 | P | R | F1 | TP | FP | FN | 类别 |")
            w("|---|---|---|---|---|---|---|---|")
            for lname, v in cov["by_level"].items():
                w("| %s | %.3f | %.3f | %.3f | %d | %d | %d | %s |"
                  % (lname, v["precision"], v["recall"], v["f1"], v["tp"], v["fp"],
                     v["fn"], ",".join(v["categories"]) or "—"))
            w()
            w("耗时 %.0fms / %d 条 = %.1fms 每条"
              % (res["total_ms"], res["n_cases"], res["total_ms"] / max(1, res["n_cases"])))
            w()

        dg = diagnoses.get(dsname)
        if dg:
            w("## 误报结构诊断（+GLiNER）")
            w()
            w("| 类型 | 数量 | 含义 |")
            w("|---|---|---|")
            w("| 严格正确 | %d | 位置与类别完全一致 |" % dg["strict"])
            w("| 仅边界错 | %d | 类别对、压住了实体，但起止范围不对 |" % dg["boundary"])
            w("| 类别串扰 | %d | 压住了实体，但打成了别的类别 |" % dg["cross"])
            w("| 完全虚构 | %d | 附近没有任何 gold 实体 |" % dg["hallu"])
            w()
            w("误报来源检测器：%s" % dict(dg["fp_by_detector"]))
            w()
            w("类别串扰明细：")
            for k, v in dg["cross_pairs"].most_common(15):
                w("   %-30s x%d" % (k, v))
            w()
            w("完全虚构的误报（按出现次数，前 40）：")
            for k, v in dg["hallu_items"].most_common(40):
                w("   %-44s x%d" % (k, v))
            w()

    # 汇总
    w("#" * 74)
    w("# 汇总")
    w("#" * 74)
    w()
    w("| 数据集 | 配置 | 粒度无关 F1 | 区间相交 F1 | 边界严格 F1 |")
    w("|---|---|---|---|---|")
    for dsname, data in evaluated.items():
        for cfgname, res in data["results"].items():
            w("| %s | %s | **%.4f** | %.4f | %.4f |"
              % (dsname, cfgname, res["modes"]["cover"]["overall"]["f1"],
                 res["modes"]["overlap"]["overall"]["f1"],
                 res["modes"]["strict"]["overall"]["f1"]))
    w()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", choices=("both", "field", "old"), default="both")
    ap.add_argument("--no-compare", action="store_true", help="不评旧的 gold_v3 test")
    args = ap.parse_args()

    sets = {}
    if args.dataset in ("both", "field"):
        sets["field_v1（独立手写集）"] = cases_from_jsonl(FIELD_JSONL)
    if args.dataset in ("both", "old") and not args.no_compare:
        # 只取 test split：train/validation 是训练数据，评它没有意义
        old = cases_from_gold(OLD_GOLD_DIR / "test_gold.jsonl")
        sets["gold_v3 test（旧留出集，与训练同源）"] = old

    evaluated = {}
    diagnoses = {}
    for dsname, cases in sets.items():
        # 独立性说明
        indep = ""
        if dsname.startswith("field_v1"):
            indep = ("与训练语料字符 8-gram 重合率 2.4%（对照：旧 gold_v3 test 为 78.8%）；"
                     "完整校验见 data/field_v1/integrity_report.md（脚本 scripts/field_v1_check.py）")
        else:
            indep = "与训练语料同源生成，与训练集 8-gram 重合率 78.8%（脚本 scripts/field_v1_check.py 可复核）"
        results = {}
        preds_for_diag = None
        for cfgname, kind in CONFIGS:
            t0 = time.time()
            dets, info = make_detectors(kind)
            build_s = time.time() - t0
            sys.stderr.write("[%s] %s 构建 %.1fs %s\n" % (dsname, cfgname, build_s, info))
            res = evaluate(cases, dets, cfgname)
            results[cfgname] = res
            if kind == "gliner_all":
                preds_for_diag = {c["id"]: predict(c, dets) for c in cases}
        evaluated[dsname] = {"cases": cases, "results": results, "independence": indep}
        if preds_for_diag is not None:
            diagnoses[dsname] = diagnose(cases, preds_for_diag)

    emit(evaluated, diagnoses, args)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    md = OUT_DIR / "eval_report.md"
    md.write_text("\n".join(_buf) + "\n", encoding="utf-8")

    # JSON：去掉不可序列化的 Counter，并精简上下文原文
    def jsonable(ds):
        out = {"independence": ds["independence"], "n_cases": len(ds["cases"]),
               "results": {}}
        for cfg, res in ds["results"].items():
            out["results"][cfg] = {m: {"overall": res["modes"][m]["overall"],
                                       "macro_f1": res["modes"][m]["macro_f1"],
                                       "negative_total": res["modes"][m]["negative_total"],
                                       "negative_with_fp": res["modes"][m]["negative_with_fp"],
                                       "by_level": res["modes"][m]["by_level"],
                                       "per_category": {k: {kk: vv for kk, vv in v.items()
                                                            if kk not in ("missed", "spurious")}
                                                        for k, v in res["modes"][m]["per_category"].items()}}
                                   for m in MODES}
            out["results"][cfg]["total_ms"] = res["total_ms"]
        return out

    payload = {"schema": 1, "generated_at": datetime.now().isoformat(),
               "datasets": {k: jsonable(v) for k, v in evaluated.items()},
               "diagnosis": {k: {"strict": v["strict"], "boundary": v["boundary"],
                                 "cross": v["cross"], "hallu": v["hallu"],
                                 "fp_by_detector": dict(v["fp_by_detector"]),
                                 "cross_pairs": dict(v["cross_pairs"]),
                                 "hallu_items": dict(v["hallu_items"])}
                             for k, v in diagnoses.items()}}
    (OUT_DIR / "eval_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    sys.stdout.write("markdown -> %s\njson     -> %s\n"
                     % (md, OUT_DIR / "eval_report.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
