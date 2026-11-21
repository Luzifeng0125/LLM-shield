"""核对 31 条盲标仍是空白，并写出不含答案的人工表。

不加载必要性模型，不对这 31 条做预测。
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
BLIND = ROOT / "research/datasets/legacy" / "校园必要性盲标_20261102"
OUT = APP / "outputs" / "campus_blind31_acceptance_20261102"
SHEET = BLIND / "人工盲标表.csv"
MODELS = {
    "active": APP / "models" / "necessity_action.joblib",
    "task": APP / "models" / "necessity_action_campus_task_20261102.joblib",
    "context": APP / "models" / "necessity_action_campus_context_20261102.joblib",
}
TRAIN_SCRIPTS = [
    APP / "scripts" / "train_campus_necessity_aligned_20261101.py",
    APP / "scripts" / "train_campus_necessity_task_20261102.py",
    APP / "scripts" / "train_campus_context_20261102.py",
    APP / "scripts" / "train_campus_necessity_candidate.py",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = json.loads((BLIND / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("actions_filled") is not False or manifest.get("model_screened") is not False:
        raise SystemExit("清单显示材料已被填写或经过模型筛选")
    units = []
    file_hashes = {}
    for item in manifest["files"]:
        path = BLIND / item["file"]
        digest = sha256(path)
        file_hashes[item["file"]] = digest
        if digest != item["sha256"]:
            raise SystemExit(f"{item['file']} 已偏离空白清单")
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("model_screened") is not False or document.get("label_status") != "unlabeled":
            raise SystemExit(f"{item['file']} 不是未标注状态")
        for unit in document["units"]:
            action = unit["annotation"]["canonical_action"]
            if action or any(unit["annotation"][key] for key in ("required_facts", "notes", "annotator", "annotated_at")):
                raise SystemExit(f"{unit['unit_id']} 已经有人工或参考内容")
            if document["text"].find(unit["quote"]) != unit["start"]:
                raise SystemExit(f"{unit['unit_id']} 片段位置和原文不一致")
            units.append({
                "unit_id": unit["unit_id"],
                "document_id": document["document_id"],
                "text": document["text"],
                "quote": unit["quote"],
                "category": unit["category"],
                "boundary_name": unit["boundary_name"],
                "recipient_name": unit["recipient_name"],
                "identity_name": unit["identity_name"],
                "user_task": unit["user_task"],
                "task_key": document["task_key"],
                "recipient_id": unit["recipient_id"],
                "identity_key": unit["identity_key"],
                "boundary_id": unit["boundary_id"],
                "start": unit["start"],
                "end": unit["end"],
            })
    if len(units) != 31 or len({row["unit_id"] for row in units}) != 31:
        raise SystemExit(f"条目不是 31: {len(units)}")
    for script in TRAIN_SCRIPTS:
        source = script.read_text(encoding="utf-8")
        if "校园必要性盲标_20261102" in source and "CALIBRATION" in source and "20261102" in source.split("CALIBRATION", 1)[-1][:200]:
            raise SystemExit(f"{script.name} 的训练入口指向了这 31 条")
        if any(row["unit_id"] in source for row in units):
            raise SystemExit(f"{script.name} 写入了盲标编号")
    model_hashes = {}
    for name, path in MODELS.items():
        if not path.exists():
            raise SystemExit(f"缺少模型 {path.name}")
        model_hashes[name] = {"file": path.name, "sha256": sha256(path)}
    SHEET.parent.mkdir(parents=True, exist_ok=True)
    with SHEET.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "编号", "原文", "片段", "类别", "边界", "接收方", "身份", "用户任务", "动作", "必要事实", "备注",
        ])
        writer.writeheader()
        for row in units:
            writer.writerow({
                "编号": row["unit_id"],
                "原文": row["text"],
                "片段": row["quote"],
                "类别": row["category"],
                "边界": row["boundary_name"],
                "接收方": row["recipient_name"],
                "身份": row["identity_name"],
                "用户任务": row["user_task"],
                "动作": "",
                "必要事实": "",
                "备注": "",
            })
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "awaiting_frozen_human_labels",
        "predictions_run": False,
        "reference_answers_written": False,
        "weights_modified": False,
        "rules_modified": False,
        "unit_count": 31,
        "actions_filled": 0,
        "blank_file_sha256": file_hashes,
        "models": model_hashes,
        "development_diagnostic": "2026-11-01 的 40 条，不能与这 31 条混为同一次独立测试",
        "independent_test": "2026-11-02 的 31 条，标签冻结前不评测",
        "immutable_units": units,
    }
    (OUT / "readiness.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "units": 31,
        "actions_filled": 0,
        "predictions_run": False,
        "sheet": str(SHEET),
        "models": {name: item["sha256"] for name, item in model_hashes.items()},
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
