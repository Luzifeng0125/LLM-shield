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
from pathlib import Path
from typing import List

from ..config import DATA_DIR, category_level, recipients, tasks
from ..schema import Action
from .model import MODEL_PATH, NecessityModel, build_feature_text

GEN_DIR = DATA_DIR / "generated"


def load_synthetic() -> List[dict]:
    """离线规则教师仅用于启动标签，在线决策不调用此函数。"""
    from ..m2_detect.pipeline import detect_and_segment
    from ..m3_decide.constraints import action_applicable, check_hard

    path = GEN_DIR / "cases_dev.jsonl"
    if not path.exists():
        raise FileNotFoundError("请先运行 python -m llm_shield.m9_data.synthesize 生成开发案例")
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    samples = []
    for case in cases:
        task_key = case["task"]
        task_cfg = tasks().get(task_key, {})
        prefer = task_cfg.get("prefer", {})
        identity_key = case.get("identity", "student_leader")
        _, segments = detect_and_segment(case["text"], case.get("columns"), case.get("rows"))
        for segment in segments:
            if not segment.spans:
                continue
            cats = {s.category for s in segment.spans}
            # 以人物任务为主的句段需保持整段一致的处理，其他类别取最高敏感级别。
            # 这是离线弱标签假设；人工标签应在 --samples 中替换它。
            main_category = ("PERSON_NAME" if "PERSON_NAME" in cats
                             else max(sorted(cats), key=category_level))
            action = Action(prefer.get(main_category, "DELETE"))
            for recipient_key, recipient_cfg in recipients().items():
                if not isinstance(recipient_cfg, dict):
                    continue
                selected = action
                if (not action_applicable(selected, segment, task_key)
                        or not all(check.passed for check in check_hard(
                            selected, segment, task_key, recipient_key, identity_key))):
                    # 项目公开介绍无需个人身份。混合“姓名+预算+电话”不能整体泛化，
                    # 但删除实体值仍保留模块等公开事实。该标签只在离线训练时生成，
                    # 不能把“首选动作不安全”一概误标成“请求无法处理”。
                    selected = (Action.DELETE if task_key == "project_intro"
                                and all(check.passed for check in check_hard(
                                    Action.DELETE, segment, task_key, recipient_key, identity_key))
                                else Action.PAUSE)
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
