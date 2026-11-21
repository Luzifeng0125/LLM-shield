"""对校准首批只跑 R0 的已知目标轨道，并写出不能当作验收的报告。

不训练 B0，不读取标注来选择动作，不替换活动模型。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))

from llm_shield.campus_v11.boundary import RULE_VERSION as CAMPUS_RULE_VERSION
from llm_shield.campus_v11.pack import load_document
from llm_shield.campus_v11.r0 import RULE_VERSION, decide
from llm_shield.campus_v11.score import score_actions, score_pause_tasks

PACK = ROOT / "research/datasets/legacy" / "校园最小披露_校准首批_20261031"
OUT = APP / "outputs" / "campus_r0_20261031_v1"
MODEL_HASHES = {
    "app/models/necessity_action.joblib":
        "cbfed4ca422a1a6d416ce1b5f488649816c261b6acc86ffc173887c8dfed1b9f",
    "app/models/ACTIVE_MODELS.json":
        "f7e27ea6060bc51e70429d967c5afb27a86726c9586f0b8dd03c7138da1af6c8",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    rows = []
    details = []
    for folder in sorted((PACK / "documents").iterdir()):
        loaded = load_document(folder)
        labels = {item["information_unit_id"]: item for item in loaded["document"]["annotation"]["units"]}
        for runtime_unit in loaded["runtime_units"]:
            prediction = decide(runtime_unit)
            unit_id = str(runtime_unit["unit_id"]).split(":", 1)[1]
            label = labels[unit_id]
            detail = {
                "unit_id": runtime_unit["unit_id"],
                "task_key": runtime_unit.get("task_key"),
                "category": runtime_unit.get("category"),
                "boundary_id": runtime_unit.get("boundary_id"),
                "r0_final": prediction["final_action"],
                "r0_proposed": prediction["proposed_action"],
                "r0_reason": prediction["reason_code"],
                "r0_coverage": prediction["coverage"],
                "boundary_conditioned": prediction.get("boundary_conditioned") is True,
                "draft_action": label.get("canonical_action"),
                "representational_gap": label.get("representational_gap") is True,
                "counts_as_primary": label.get("counts_as_primary") is not False,
                "counterfactual": label.get("counterfactual") is True,
                "matched_draft": prediction["final_action"] == label.get("canonical_action"),
            }
            details.append(detail)
            rows.append({
                "distribution": "calibration",
                "task_id": folder.name,
                "canonical_action": label.get("canonical_action"),
                "pred_action": prediction["final_action"],
                "pred_pause_kind": prediction.get("pause_kind"),
                "pause_kind": label.get("pause_kind"),
                "pause_group_id": label.get("pause_group_id"),
                "acceptable_actions": label.get("acceptable_actions") or [],
                "representational_gap": label.get("representational_gap") is True,
                "counts_as_primary": label.get("counts_as_primary") is not False,
                "question": None,
            })
    action_score = score_actions(rows)
    pause_score = score_pause_tasks(rows)
    hashes = {}
    for relative, expected in MODEL_HASHES.items():
        actual = sha256(ROOT / relative)
        hashes[relative] = {"sha256": actual, "unchanged": actual == expected}
        if actual != expected:
            raise SystemExit(f"活动模型哈希变化，停止: {relative}")
    primary = [item for item in details if item["counts_as_primary"] and not item["representational_gap"]]
    report = {
        "schema": "campus-r0-baseline-report-v1.1",
        "rule_version": RULE_VERSION,
        "campus_rule_version": CAMPUS_RULE_VERSION,
        "boundary_conditioned_units": sum(item["boundary_conditioned"] for item in details),
        "comparison_target": "ai_draft_not_human_label",
        "formal_accuracy_claim": False,
        "stage80_applicable": False,
        "l1_only": True,
        "l2_not_run": "未恢复匹配的 GLiNER 权重，不用人工位置补识别",
        "l3_not_run": True,
        "b0_trained": False,
        "release_gate": "not_run",
        "activity_model_hashes": hashes,
        "action_score_against_ai_draft": action_score,
        "pause_score_against_ai_draft": pause_score,
        "primary_units": len(primary),
        "primary_draft_matches": sum(item["matched_draft"] for item in primary),
        "out_of_table": sum(item["r0_coverage"] == "out_of_table" for item in details),
        "gaps": [item["unit_id"] for item in details if item["representational_gap"]],
        "counterfactual_not_in_primary_score": [
            item for item in details if item["counterfactual"]
        ],
        "details": details,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scored_units = action_score["scored_units"]
    scored_correct = action_score["strict_correct"]
    (OUT / "结果说明.md").write_text(
        f"""# 工作包：校园 R0 首批对照

状态：部分完成

工作包目标：用共享规则核心和三条边界策略对照 8 篇 AI 草稿。不把对照结果写成人工准确率或 80% 验收，也不把新规则写成已经提高准确率。

输入版本：校园协议 v1.1；无工作流时仍用 `{RULE_VERSION}`；带工作流时用 `{CAMPUS_RULE_VERSION}`。`tasks.yaml` 未改。材料是 AI 草稿，标签哈希不能当作人工标签哈希。

实际修改：八类校园工作共用识别、任务必要性和硬权限约束，按模型输入、结果展示、工具外发分别选动作并分别记分。活动模型未替换。

运行模式：L1 已知类别。活动动作模型未加载。GLiNER 未用于本报告。

结果：暂停分组后的主计分单元 {scored_units} 个，其中 {scored_correct} 个与当前 AI 草稿的首选动作一致。这只是和草稿的差异，不是人工准确率，也不能说明新规则提升了准确率。本批没有再把印刷费标成能力缺口。

证据文件：`{OUT.relative_to(ROOT).as_posix()}/report.json` 与校准材料目录。

不在本次证明范围内：本轮新草稿的人工复核、B0 训练、自动识别、整链路输出、发布门槛、正式 N/D/C。

上一份人工辅助返还对应的是更早一版指令，见 `D:/challenge_AI/LLM-Shield/research/datasets/legacy/校园最小披露_校准首批_20261031/returns/calibration-return.json`。那一版不作为当前草稿的标签。当前不把敏感字段的原文恢复当作验收条件。老师查看对照不进入主计分分母。

下一包前置条件：至少有一批你按新文段返还的校准标签之后，才可以用人工标签重跑对照。B0 在那之前只保留仲裁代码，不训练。
""",
        encoding="utf-8",
    )
    print(json.dumps({
        "scored_units": scored_units,
        "scored_matches_against_ai_draft": scored_correct,
        "strict_accuracy_against_ai_draft": action_score["strict_accuracy"],
        "formal_accuracy_claim": False,
        "out_of_table_rows": report["out_of_table"],
        "output": str(OUT),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
