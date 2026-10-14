"""对照实验与消融实验（模块 ⑨ 评测层）。

对照配置：
  none        无防护：原文直发
  uniform     统一脱敏：所有识别到的敏感片段统一替换为 ***
  fixed       固定类别规则：按类别固定动作，不考虑任务与接收方
  full        本地模型选动作 + 硬约束校验 + 转换 + 外发检查

消融（在 full 基础上分别关闭模块）：
  full_no_necessity   模型不可用故障实验：暂停，不回退规则
  full_no_utility     关闭 ⑤ 效用估计
  full_no_egress      关闭 ⑦ 外发前检查

运行：python eval/run_eval.py --split test --limit 60
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# 允许以 `python eval/run_eval.py` 直接运行：把项目根加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm_shield.config import OUTPUT_DIR, ROOT, category_level
from llm_shield.m2_detect.pipeline import detect_and_segment
from llm_shield.m3_decide.decision import decide_all
from llm_shield.m4_necessity.model import necessity_scorer
from llm_shield.m5_utility.estimator import estimate
from llm_shield.m6_transform.anonymizer import apply_decisions
from llm_shield.m6_transform.mapping import get_table
from llm_shield.m7_egress.gateway import EgressGateway
from llm_shield.m8_audit.audit import get_auditor
from llm_shield.schema import Action, Material, ShieldRequest
from eval.metrics import aggregate_metrics, completion_of, leakage_of, relation_correctness

DATA_DIR = ROOT / "data" / "generated"

# 固定类别规则（不考虑任务与接收方的基线）
FIXED_RULE = {
    "PHONE": Action.DELETE, "EMAIL": Action.DELETE, "WECHAT": Action.DELETE,
    "ID_CARD": Action.DELETE, "BANK_CARD": Action.DELETE, "API_KEY": Action.DELETE,
    "STUDENT_ID": Action.DELETE, "DORM": Action.DELETE, "GRADE": Action.DELETE,
    "SENSITIVE_ATTR": Action.DELETE,
    "PERSON_NAME": Action.PSEUDONYMIZE,
    "ORG": Action.RETAIN, "LOCATION": Action.RETAIN, "BUDGET": Action.GENERALIZE,
}


def load_cases(split: str, limit: Optional[int] = None) -> List[dict]:
    path = DATA_DIR / f"cases_{split}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"评测数据不存在，请先运行：python -m llm_shield.m9_data.synthesize\n({path})")
    cases = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return cases[:limit] if limit else cases


# ---------------------------------------------------------------- 各配置实现


def _sanitize_uniform(text: str, spans) -> str:
    """统一脱敏基线：所有识别到的敏感片段一律替换为 ***。"""
    out = text
    for s in sorted(spans, key=lambda x: -x.start):
        out = out[:s.start] + "***" + out[s.end:]
    return out


def _sanitize_fixed(text: str, segments, session_id: str, mapping) -> tuple:
    """固定类别规则基线：按类别查表决定动作，不看任务与接收方。"""
    from llm_shield.schema import Decision
    decisions: List[Decision] = []
    for seg in segments:
        if not seg.spans:
            decisions.append(Decision(seg.seg_id, Action.RETAIN, [], reason="无敏感片段"))
            continue
        top = max(seg.spans, key=lambda s: category_level(s.category))
        action = FIXED_RULE.get(top.category, Action.GENERALIZE)
        decisions.append(Decision(seg.seg_id, action,
                                  sorted({s.category for s in seg.spans}),
                                  reason=f"固定规则: {top.category} -> {action.value}"))
    applied = apply_decisions(text, segments, decisions, session_id, mapping)
    return applied["sanitized_text"], applied["aggregates"]


def run_case(case: dict, config: str) -> dict:
    """对单个案例跑一种配置，返回一条评测记录。"""
    t0 = time.perf_counter()
    text = case["text"]
    task = case["task"]
    recipient = case.get("recipient", "external_model")
    identity = case.get("identity", "student_leader")
    session_id = f"eval_{case['case_id']}_{config}"

    mapping = get_table()
    mapping.clear_session(session_id)
    gold_spans = case["gold_spans"]

    blocked = False
    block_reason = ""
    aggregates: dict = {}

    if config == "none":
        sanitized = text

    elif config == "uniform":
        _, segments = detect_and_segment(text, case.get("columns"), case.get("rows"))
        spans = [s for seg in segments for s in seg.spans]
        sanitized = _sanitize_uniform(text, spans)

    elif config == "fixed":
        _, segments = detect_and_segment(text, case.get("columns"), case.get("rows"))
        sanitized, aggregates = _sanitize_fixed(text, segments, session_id, mapping)

    else:
        # ---- full 及其消融 ----
        use_necessity = "no_necessity" not in config
        use_utility = "no_utility" not in config
        use_egress = "no_egress" not in config

        _, segments = detect_and_segment(text, case.get("columns"), case.get("rows"))
        scorer = necessity_scorer if use_necessity else None
        decisions = decide_all(segments, task, recipient, identity, necessity_scorer=scorer,
                               task_description=case.get("task_description", ""))
        applied = apply_decisions(text, segments, decisions, session_id, mapping)
        sanitized = applied["sanitized_text"]
        aggregates = applied["aggregates"]
        if applied["paused"]:
            blocked = True
            block_reason = applied["pause_reason"]

        if use_utility:
            estimate(sanitized, task, aggregates, decisions)

        if use_egress and not blocked:
            gw = EgressGateway(get_auditor())
            spans = [s for seg in segments for s in seg.spans]
            retained = {s.text for seg, dec in zip(segments, decisions)
                        if dec.action == Action.RETAIN for s in seg.spans}
            pre = gw.precheck(recipient, identity, sanitized, spans, retained, task_key=task)
            if not pre["allowed"]:
                blocked = True
                block_reason = str(pre["reason"])

    latency = (time.perf_counter() - t0) * 1000
    mapping.clear_session(session_id)
    sent_text = "" if blocked else sanitized
    completion = completion_of(sent_text, task, {} if blocked else aggregates)
    if blocked:
        completion = {"completed": False, "reasons": [block_reason]}

    return {
        "case_id": case["case_id"],
        "task": task,
        "config": config,
        "recipient": recipient,
        "leakage": leakage_of(sent_text, gold_spans, task, recipient),
        "candidate_leakage": leakage_of(sanitized, gold_spans, task, recipient),
        "completion": completion,
        "relation": relation_correctness(sent_text, task),
        "expected_allowed": case.get("expected_allowed"),
        "blocked": blocked,
        "block_reason": block_reason,
        "latency_ms": latency,
    }


# ---------------------------------------------------------------- 主流程

CONFIGS = ["none", "uniform", "fixed", "full",
           "full_no_necessity", "full_no_utility", "full_no_egress"]


def main():
    ap = argparse.ArgumentParser(description="隐盾 对照与消融实验")
    ap.add_argument("--split", default="test", choices=["dev", "test"])
    ap.add_argument("--limit", type=int, default=None, help="每个任务限制案例数")
    ap.add_argument("--configs", default=",".join(CONFIGS))
    ap.add_argument("--out", default=str(OUTPUT_DIR / "eval_result.json"))
    args = ap.parse_args()

    cases = load_cases(args.split, args.limit)
    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    print(f"评测集: {args.split} 共 {len(cases)} 例；配置: {configs}\n")

    results: Dict[str, List[dict]] = {}
    summary: Dict[str, dict] = {}

    for cfg in configs:
        records = [run_case(c, cfg) for c in cases]
        results[cfg] = records
        m = aggregate_metrics(records)
        summary[cfg] = m
        print(f"[{cfg:18s}] 泄露事件率={m['leak_event_rate']:.3f}  "
              f"泄露值率={m['leak_value_rate']:.3f}  "
              f"任务完成率={m['task_completion_rate']:.3f}  "
              f"拦截率={m['block_rate']:.3f}  "
              f"误拦率={m['overblock_rate']}  "
              f"关系要素保留率={m['relation_presence_rate']}  "
              f"P95={m['latency_p95_ms']:.1f}ms")

    # 按任务拆解（完整方案）
    print("\n--- 完整方案 按任务拆解 ---")
    for task in sorted({c["task"] for c in cases}):
        sub = [r for r in results.get("full", []) if r["task"] == task]
        if not sub:
            continue
        m = aggregate_metrics(sub)
        print(f"  {task:18s} 完成率={m['task_completion_rate']:.3f}  "
              f"泄露事件率={m['leak_event_rate']:.3f}  "
              f"关系要素保留={m['relation_presence_rate']}  P95={m['latency_p95_ms']:.1f}ms")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "records": results,
                               "notes": ["合成数据启动基线，不代表生产精度",
                                         "完成率和关系要素保留率均为启发式指标",
                                         "未标注expected_allowed时不报告误拦率",
                                         "full_no_necessity验证模型故障时暂停，不能用于证明模型质量"],
                               "split": args.split,
                               "n_cases": len(cases)},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已保存: {out}")


if __name__ == "__main__":
    main()
