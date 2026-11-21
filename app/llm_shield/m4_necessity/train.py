#!/usr/bin/env python
"""训练模型决策权重。

默认从 cases_dev.jsonl 生成与运行时分段一致的规则启动基线，按原案例
分组留出验证。--samples 可替换为人工标注的新版特征 JSONL。
旧版 --weak / --self-train 使用不兼容特征与评测流程，已移除。
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import List

from ..config import DATA_DIR, category_level, recipients, tasks
from ..schema import Action, Segment
from .model import MODEL_PATH, NecessityModel, build_feature_text

GEN_DIR = DATA_DIR / "generated"


def project_categories(segment: Segment, cats) -> Segment:
    """保留指定类别、沿用原片段原文的子片段，用于按「类别组合」补齐训练覆盖。

    真实文本会产生大量合成案例里没有的类别组合（如 ``{BUDGET, ORG}``、
    ``{GRADE, ORG, STUDENT_ID}``）。若训练语料只有「整段全部类别」这一种组合，
    模型对这些新组合只能从最接近的已知组合外推，实测会外推成 RETAIN —— 而
    RETAIN 是披露原文的动作，方向不安全。

    ``[TEXT]``/``[CONTEXT]`` 沿用原片段不动，只有 ``[CAT]`` 与 ``[N]`` 随组合变化：
    同一片段的所有投影共享同一段原文，等于强制模型用类别信号而不是「这段文字
    像什么」来区分动作。
    """
    keep = tuple(sorted(cats))
    return Segment(
        seg_id=f"{segment.seg_id}#{'+'.join(keep)}",
        text=segment.text,
        start=segment.start,
        end=segment.end,
        spans=[s for s in segment.spans if s.category in keep],
        column=segment.column,
        row_index=segment.row_index,
        context=segment.context,
    )


# 组合投影最多枚举到几元组。二元覆盖了绝大多数真实片段；再往上组合数增长很快，
# 收益递减，而训练时间线性上升。
MAX_COMBO = 2


def expand_segments(segments: List[Segment]) -> List[Segment]:
    """原始片段 + 其类别组合的全部投影（1 ~ MAX_COMBO 元，不含原集合本身）。"""
    expanded: List[Segment] = list(segments)
    for segment in segments:
        cats = sorted({s.category for s in segment.spans})
        if len(cats) < 2:
            continue                      # 单类别片段已经是它自己的投影
        for size in range(1, min(MAX_COMBO, len(cats) - 1) + 1):
            for combo in combinations(cats, size):
                expanded.append(project_categories(segment, combo))
    return expanded


def synthetic_label(segment, task_key: str, recipient_key: str, identity_key: str) -> Action:
    """Offline weak teacher; online action selection always uses the classifier."""
    from ..m3_decide.constraints import action_applicable, check_hard
    cats = {span.category for span in segment.spans}
    main = 'PERSON_NAME' if 'PERSON_NAME' in cats else max(sorted(cats), key=category_level)
    selected = Action(tasks().get(task_key, {}).get('prefer', {}).get(main, 'DELETE'))
    if (not action_applicable(selected, segment, task_key)
            or not all(check.passed for check in check_hard(
                selected, segment, task_key, recipient_key, identity_key))):
        selected = (Action.DELETE if task_key == 'project_intro' and all(check.passed for check in check_hard(
            Action.DELETE, segment, task_key, recipient_key, identity_key)) else Action.PAUSE)
    return selected


def load_synthetic(*, detectors=None) -> List[dict]:
    """离线规则教师仅用于启动标签，在线决策不调用此函数。"""
    from ..m2_detect.pipeline import detect_and_segment
    path = GEN_DIR / "cases_dev.jsonl"
    if not path.exists():
        raise FileNotFoundError("请先运行 python -m llm_shield.m9_data.synthesize 生成开发案例")
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    samples = []
    for case in cases:
        task_key = case["task"]
        task_cfg = tasks().get(task_key, {})
        identity_key = case.get("identity", "student_leader")
        _, segments = detect_and_segment(case["text"], case.get("columns"), case.get("rows"), detectors=detectors)
        for segment in expand_segments([s for s in segments if s.spans]):
            for recipient_key, recipient_cfg in recipients().items():
                if not isinstance(recipient_cfg, dict):
                    continue
                selected = synthetic_label(segment, task_key, recipient_key, identity_key)
                description = case.get("user_instruction", "") or task_cfg.get("desc", "")
                samples.append({
                    "feature": build_feature_text(
                        segment, task_key, recipient_key,
                        task_description=description, identity_key=identity_key),
                    "label": selected.value,
                    "source_case_id": case["case_id"],
                    "source": "synthetic_rule_baseline",
                    "task": task_key,
                    "recipient": recipient_key,
                })
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description="训练模型直接决策基线（规则标签不等于人工金标）")
    parser.add_argument("--samples", type=Path, help="人工标注或审核后的新版特征 JSONL；含来源案例 ID")
    parser.add_argument("--out", type=Path, default=MODEL_PATH, help="新版动作模型权重路径")
    args = parser.parse_args()
    try:
        if args.samples:
            samples = [json.loads(line) for line in args.samples.read_text(encoding="utf-8").splitlines()
                       if line.strip()]
        else:
            samples = load_synthetic()
            print("注意：本次使用规则生成的启动标签，不代表人工评估的决策质量。")
    except (OSError, ValueError, KeyError) as exc:
        print(f"读取训练数据失败: {exc}")
        return 1
    print(f"训练样本: {len(samples)} 条")
    print("标签分布:", dict(Counter(s.get("label", "missing") for s in samples)))
    model = NecessityModel(model_path=args.out)
    result = model.train(samples, out_path=args.out)
    if not result.get("ok"):
        print(result.get("reason"))
        return 1
    validation = result["validation"]
    print(f"按源案例分组留出验证准确率: {validation['accuracy']}")
    print(f"Macro-F1: {validation['macro_f1']}；组重叠: {validation['group_overlap']}")
    print(f"模型保存至: {result['model_path']}")
    print(result["report"])
    print("未使用 cases_test；仍需人工金标、跨模板和真实下游任务验证。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
