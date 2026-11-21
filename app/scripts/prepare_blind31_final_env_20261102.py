"""准备 31 条最终裁定的评测环境。

不调用模型预测，不读取 R0，不填写标签，不改权重和规则。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
sys.path.insert(0, str(APP))

BLIND = ROOT / "research/datasets/legacy" / "校园必要性盲标_20261102"
VERSIONS = BLIND / "版本"
OUT = APP / "outputs" / "campus_blind31_final_20261102"
MODELS = {
    "active": APP / "models" / "necessity_action.joblib",
    "task": APP / "models" / "necessity_action_campus_task_20261102.joblib",
    "context": APP / "models" / "necessity_action_campus_context_20261102.joblib",
}
SIDECARS = {
    "task": APP / "models" / "necessity_action_campus_task_20261102.json",
    "context": APP / "models" / "necessity_action_campus_context_20261102.json",
}
EXPECTED_VERSION = {"active": 3, "task": 4, "context": 5}
EXPECTED_TAKES = {
    3: ["_take_structured", "_take_content"],
    4: ["_take_structured", "_take_demand", "_take_content_after_demand"],
    5: ["_take_structured", "_take_raw", "_take_cross", "_take_content_v5"],
}
PROBE = "环境探针甲，费用1元。"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def takes_of(pipeline) -> list[str]:
    union = pipeline.named_steps["features"]
    found = []
    for _name, branch in union.transformer_list:
        take = branch.named_steps["take"]
        func = getattr(take, "func", None)
        found.append(getattr(func, "__name__", type(take).__name__))
    return found


def blank_count() -> dict:
    filled_json = 0
    units = 0
    hashes = {}
    for path in sorted(BLIND.glob("n*.json")):
        hashes[path.name] = sha256(path)
        document = json.loads(path.read_text(encoding="utf-8"))
        if PROBE in document.get("text", ""):
            raise SystemExit("探针句子出现在盲标原文中")
        for unit in document["units"]:
            units += 1
            action = str(unit.get("annotation", {}).get("canonical_action") or "").strip()
            if action:
                filled_json += 1
    sheet = BLIND / "人工盲标表.csv"
    filled_sheet = None
    if sheet.exists():
        import csv
        with sheet.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        filled_sheet = sum(1 for row in rows if str(row.get("动作") or "").strip())
    return {
        "json_units": units,
        "json_actions_filled": filled_json,
        "sheet_actions_filled": filled_sheet,
        "original_sha256": hashes,
    }


def feature_check() -> dict:
    from llm_shield.m4_necessity.model import (
        FEATURE_VERSION,
        FEATURE_VERSION_CONTEXT,
        FEATURE_VERSION_TASK,
        NecessityModel,
        build_feature_text,
        build_feature_text_v4,
        build_feature_text_v5,
    )
    from llm_shield.schema import Segment, Span

    segment = Segment("probe", PROBE, 0, len(PROBE), [Span(0, 2, PROBE[:2], "ORG", 1.0)])
    built = {
        3: build_feature_text(segment, "meeting_minutes", "external_model",
                              task_description="只做接口核对。", identity_key="student_leader"),
        4: build_feature_text_v4(segment, "meeting_minutes", "external_model",
                                task_description="只做接口核对。", identity_key="student_leader"),
        5: build_feature_text_v5(segment, "meeting_minutes", "external_model",
                                task_description="只做接口核对。", identity_key="student_leader"),
    }
    if [item.startswith(f"[SCHEMA]{version} ") for version, item in built.items()] != [True, True, True]:
        raise SystemExit("三个构造函数的版本号不对")
    if built[3] == built[4] or built[4] == built[5]:
        raise SystemExit("三个特征版本生成了相同字符串")
    records = {}
    for name, path in MODELS.items():
        model = NecessityModel(path)
        if not model.available:
            raise SystemExit(f"{name} 无法加载：{model.reason}")
        version = model.metadata.get("feature_version")
        if version != EXPECTED_VERSION[name]:
            raise SystemExit(f"{name} 的特征版本是 {version}，预期 {EXPECTED_VERSION[name]}")
        found = takes_of(model.pipeline)
        if found != EXPECTED_TAKES[version]:
            raise SystemExit(f"{name} 的特征接口是 {found}")
        records[name] = {
            "file": path.name,
            "sha256": sha256(path),
            "feature_version": version,
            "inference": "NecessityModel.score",
            "feature_builder": {3: "build_feature_text", 4: "build_feature_text_v4", 5: "build_feature_text_v5"}[version],
            "pipeline_takes": found,
            "content_weight": model.metadata.get("content_weight"),
            "promoted": False,
        }
    if (FEATURE_VERSION, FEATURE_VERSION_TASK, FEATURE_VERSION_CONTEXT) != (3, 4, 5):
        raise SystemExit("代码里的版本常量已变化")
    for name, sidecar in SIDECARS.items():
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        if meta.get("sha256") != records[name]["sha256"] or meta.get("feature_version") != records[name]["feature_version"]:
            raise SystemExit(f"{sidecar.name} 与权重不一致")
        if meta.get("promoted") is not False:
            raise SystemExit(f"{sidecar.name} 被标成已替换活动权重")
    active_manifest = sha256(APP / "models" / "ACTIVE_MODELS.json")
    return {"models": records, "active_models_json_sha256": active_manifest, "probe_scored": False}


def write_templates() -> None:
    VERSIONS.mkdir(parents=True, exist_ok=True)
    note = VERSIONS / "版本记录说明.md"
    if not note.exists():
        note.write_text("""# 版本记录

三个文件分开存放。评测只读，不覆盖 `n01.json` 到 `n12.json`，也不覆盖本说明。

| 文件 | 内容 |
| --- | --- |
| `原始人工标注.json` | 第一次人工填写 |
| `辅助意见.json` | 后来参考过的意见。没有就不要造 |
| `最终裁定.json` | 冻结后用于评测的动作 |
| `冻结标记.json` | 只在裁定完成时由人工写入 |

最终裁定的格式：

```json
{
  "role": "final_adjudication",
  "items": [
    {"unit_id": "题目编号", "canonical_action": "", "required_facts": "", "notes": ""}
  ]
}
```

冻结标记的全文必须是：

```json
{"frozen": true, "statement": "人工裁定已完成并冻结"}
```

动作只使用 `DELETE`、`LOCAL_AGGREGATE`、`GENERALIZE`、`PSEUDONYMIZE`、`RETAIN`、`PAUSE`。拿不准的条目不要提前交给评测。
""", encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "报告格式.md").write_text("""# 31 条独立评测报告格式

评测未运行。下面是冻结后一次性写出的文件。

## 结果表 `results.csv`

每一行是一条人工最终裁定。列：

`unit_id`，`category`，`task_key`，`boundary_id`，`recipient_id`，`identity_key`，`final_action`，然后每个模型各两列：`active_argmax`，`active_pipeline`，`task_argmax`，`task_pipeline`，`context_argmax`，`context_pipeline`，以及 `error_class_active`，`error_class_task`，`error_class_context`。

`argmax` 是模型六个概率里的最高项。`pipeline` 是同一选择经过现有硬约束之后的动作。硬约束只放行或暂停。

## 混淆矩阵 `confusion.json`

每个模型分开两张矩阵，行是最终裁定，列是模型动作。六行六列的顺序固定为：

`DELETE`，`LOCAL_AGGREGATE`，`GENERALIZE`，`PSEUDONYMIZE`，`RETAIN`，`PAUSE`。

同时给出正确条数、正确率、六类 macro-F1。正确率是与最终裁定的一致率，不是事先承诺的校园准确率。

## 错误分类 `errors.json`

按硬约束之后的动作分类：

| 类别 | 含义 |
| --- | --- |
| `match` | 与最终裁定相同 |
| `unnecessary_disclosure` | 裁定不披露原值，模型结果仍会带出该类别 |
| `necessary_information_deleted` | 裁定保留、代号、泛化或汇总，模型删掉 |
| `incorrect_pause` | 裁定不是暂停，模型结果是暂停 |
| `pause_replaced_by_delete` | 裁定是暂停，模型改成删除 |
| `action_mismatch_other` | 其余不一致 |

原始人工标注和辅助意见如果存在，只比较它们与最终裁定是否相同，不作为模型分数。
""", encoding="utf-8")


def main() -> None:
    blanks = blank_count()
    if blanks["json_units"] != 31:
        raise SystemExit(f"原件不是 31 条: {blanks['json_units']}")
    features = feature_check()
    write_templates()
    payload = {
        "status": "environment_ready_waiting_for_frozen_adjudication",
        "predictions_run_on_31": False,
        "r0_loaded": False,
        "labels_written_by_script": False,
        "weights_modified": False,
        "rules_modified": False,
        "local_completion_implemented": False,
        "one_shot_command": "app/scripts/eval_blind31_once_20261102.py",
        "one_shot_blocked_until": "版本/冻结标记.json 的 statement 为人工裁定已完成并冻结",
        "blanks": blanks,
        "features": features,
    }
    (OUT / "environment.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "units": blanks["json_units"],
        "json_actions_filled": blanks["json_actions_filled"],
        "sheet_actions_filled": blanks["sheet_actions_filled"],
        "predictions_run_on_31": False,
        "models": {name: item["feature_version"] for name, item in features["models"].items()},
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
