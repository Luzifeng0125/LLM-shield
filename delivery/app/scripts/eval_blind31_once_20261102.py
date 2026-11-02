"""31 条最终裁定的一次性评测。裁定未冻结时立即退出，不加载模型。

不训练，不改权重，不改原件，不读 R0，不补写人工标签。
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parents[1]
sys.path.insert(0, str(APP))

BLIND = ROOT / "03_数据与人工复核" / "校园必要性盲标_20261102"
VERSIONS = BLIND / "版本"
FREEZE = VERSIONS / "冻结标记.json"
FINAL = VERSIONS / "最终裁定.json"
ORIGINAL = VERSIONS / "原始人工标注.json"
AUXILIARY = VERSIONS / "辅助意见.json"
ENV = APP / "outputs" / "campus_blind31_final_20261102" / "environment.json"
OUT = APP / "outputs" / "campus_blind31_final_20261102"
MODELS = {
    "active": APP / "models" / "necessity_action.joblib",
    "task": APP / "models" / "necessity_action_campus_task_20261102.joblib",
    "context": APP / "models" / "necessity_action_campus_context_20261102.joblib",
}
ACTIONS = ["DELETE", "LOCAL_AGGREGATE", "GENERALIZE", "PSEUDONYMIZE", "RETAIN", "PAUSE"]
STATEMENT = "人工裁定已完成并冻结"
IMMUTABLE = (
    "text", "quote", "category", "task_key", "recipient_id", "identity_key",
    "boundary_id", "start", "end", "user_task",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stop(message: str) -> None:
    raise SystemExit(message)


def read_role(path: Path, role: str) -> dict[str, dict] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("role") != role:
        stop(f"{path.name} 的 role 不是 {role}")
    items = payload.get("items")
    if not isinstance(items, list):
        stop(f"{path.name} 没有 items")
    found = {}
    for item in items:
        unit_id = item.get("unit_id")
        action = str(item.get("canonical_action") or "").strip()
        if not isinstance(unit_id, str) or unit_id in found:
            stop(f"{path.name} 的编号重复或缺失")
        if action and action not in ACTIONS:
            stop(f"{path.name} 含有六类以外的动作")
        found[unit_id] = {
            "canonical_action": action,
            "required_facts": item.get("required_facts") or "",
            "notes": item.get("notes") or "",
        }
    return found


def source_units() -> list[dict]:
    rows = []
    for path in sorted(BLIND.glob("n*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for unit in document["units"]:
            rows.append({
                "unit_id": unit["unit_id"],
                "text": document["text"],
                "quote": unit["quote"],
                "category": unit["category"],
                "task_key": document["task_key"],
                "recipient_id": unit["recipient_id"],
                "identity_key": unit["identity_key"],
                "boundary_id": unit["boundary_id"],
                "start": unit["start"],
                "end": unit["end"],
                "user_task": unit["user_task"],
            })
            if document["text"][unit["start"]:unit["end"]] != unit["quote"]:
                stop(f"{unit['unit_id']} 的片段位置和原文不一致")
    if len(rows) != 31 or len({row["unit_id"] for row in rows}) != 31:
        stop(f"原件不是 31 条: {len(rows)}")
    return rows


def load_frozen_units() -> tuple[list[dict], dict]:
    if not FREEZE.exists():
        stop("尚未发现版本/冻结标记.json。不加载模型。")
    marker = json.loads(FREEZE.read_text(encoding="utf-8"))
    if marker.get("frozen") is not True or marker.get("statement") != STATEMENT:
        stop("冻结语句不匹配。不加载模型。")
    if not ENV.exists():
        stop("缺少评测环境记录。先运行 prepare_blind31_final_env_20261102.py。")
    final = read_role(FINAL, "final_adjudication")
    if final is None:
        stop("缺少版本/最终裁定.json。不加载模型。")
    original = read_role(ORIGINAL, "original_human")
    auxiliary = read_role(AUXILIARY, "auxiliary_opinion")
    rows = []
    for source in source_units():
        label = final.get(source["unit_id"])
        if label is None or label["canonical_action"] not in ACTIONS:
            stop(f"{source['unit_id']} 没有冻结的最终裁定。不加载模型。")
        source["human"] = label["canonical_action"]
        source["required_facts"] = label["required_facts"]
        rows.append(source)
    versions = {
        "original_human": None if original is None else sha256(ORIGINAL),
        "auxiliary_opinion": None if auxiliary is None else sha256(AUXILIARY),
        "final_adjudication": sha256(FINAL),
        "original_differs_from_final": None if original is None else [
            unit_id for unit_id, item in original.items()
            if final.get(unit_id, {}).get("canonical_action") != item["canonical_action"]
        ],
        "auxiliary_differs_from_final": None if auxiliary is None else [
            unit_id for unit_id, item in auxiliary.items()
            if final.get(unit_id, {}).get("canonical_action") != item["canonical_action"]
        ],
    }
    return rows, versions


def discloses(action: str, category: str) -> bool:
    from llm_shield.m3_decide.constraints import disclosed_categories
    from llm_shield.schema import Action, Segment, Span
    if action in {"DELETE", "LOCAL_AGGREGATE", "PAUSE"}:
        return False
    return category in disclosed_categories(Action(action), Segment(
        "d", category, 0, len(category), [Span(0, len(category), category, category)]))


def error_class(human: str, final: str, category: str) -> str:
    if human == final:
        return "match"
    if discloses(final, category) and not discloses(human, category):
        return "unnecessary_disclosure"
    if human in {"RETAIN", "PSEUDONYMIZE", "GENERALIZE", "LOCAL_AGGREGATE"} and final == "DELETE":
        return "necessary_information_deleted"
    if human != "PAUSE" and final == "PAUSE":
        return "incorrect_pause"
    if human == "PAUSE" and final == "DELETE":
        return "pause_replaced_by_delete"
    return "action_mismatch_other"


def confusion(gold: list[str], pred: list[str]) -> dict:
    matrix = {label: {other: 0 for other in ACTIONS} for label in ACTIONS}
    for left, right in zip(gold, pred):
        matrix[left][right] += 1
    return matrix


def metrics(gold: list[str], pred: list[str]) -> dict:
    from sklearn.metrics import accuracy_score, f1_score
    return {
        "accuracy": round(float(accuracy_score(gold, pred)), 4),
        "correct": sum(left == right for left, right in zip(gold, pred)),
        "n": len(gold),
        "macro_f1_six_actions": round(float(f1_score(gold, pred, labels=ACTIONS, average="macro", zero_division=0)), 4),
        "support": {label: gold.count(label) for label in ACTIONS},
        "predicted": {label: pred.count(label) for label in ACTIONS},
        "confusion_gold_rows_pred_cols": confusion(gold, pred),
    }


def score_all(rows: list[dict]) -> list[dict]:
    from llm_shield.m2_detect.pipeline import attach_spans, segmentize
    from llm_shield.m3_decide.decision import decide_segment
    from llm_shield.m4_necessity.model import NecessityModel
    from llm_shield.schema import Action, Span

    environment = json.loads(ENV.read_text(encoding="utf-8"))
    loaded = {}
    before = {}
    for name, path in MODELS.items():
        digest = sha256(path)
        recorded = environment["features"]["models"][name]["sha256"]
        if digest != recorded:
            stop(f"{name} 的权重哈希与环境准备时不一致，停止评测。")
        before[name] = digest
        model = NecessityModel(path)
        if model.metadata.get("feature_version") != environment["features"]["models"][name]["feature_version"]:
            stop(f"{name} 的特征版本与环境准备时不一致。")
        if not model.available:
            stop(f"{name} 无法加载：{model.reason}")
        loaded[name] = model
    scored = []
    for row in rows:
        span = Span(row["start"], row["end"], row["text"][row["start"]:row["end"]], row["category"], 1.0,
                    detector="frozen_human", rule_id="blind31_final")
        segments = segmentize(row["text"], [span])
        attach_spans(segments, [span], row["text"])
        host = next(item for item in segments if item.start <= row["start"] and row["end"] <= item.end)
        host.spans = [span]
        item = {
            "unit_id": row["unit_id"],
            "category": row["category"],
            "task_key": row["task_key"],
            "boundary_id": row["boundary_id"],
            "recipient_id": row["recipient_id"],
            "identity_key": row["identity_key"],
            "final_action": row["human"],
        }
        for name, model in loaded.items():
            decision = decide_segment(
                host, row["task_key"], row["recipient_id"], row["identity_key"],
                necessity_scorer=model.score, task_description=row["user_task"])
            scores = {action.value: float(decision.necessity_scores.get(action.value, 0.0)) for action in Action}
            item[f"{name}_argmax"] = max(scores, key=scores.get)
            item[f"{name}_pipeline"] = decision.action.value
            item[f"error_class_{name}"] = error_class(row["human"], decision.action.value, row["category"])
        scored.append(item)
    if {name: sha256(path) for name, path in MODELS.items()} != before:
        stop("评测过程中权重发生变化，不保留结果。")
    return scored


def situation_flags(human: str, pred: str, category: str) -> list[str]:
    """四类情况可同时成立，不替代互斥错误类。"""
    flags = []
    if discloses(pred, category) and not discloses(human, category):
        flags.append("unnecessary_disclosure")
    if human in {"RETAIN", "PSEUDONYMIZE", "GENERALIZE", "LOCAL_AGGREGATE"} and pred == "DELETE":
        flags.append("necessary_information_deleted")
    if human != "PAUSE" and pred == "PAUSE":
        flags.append("incorrect_pause")
    if human == "PAUSE" and pred != "PAUSE":
        flags.append("should_pause_but_continued")
    return flags


def write_reports(rows: list[dict], versions: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "unit_id", "category", "task_key", "boundary_id", "recipient_id", "identity_key", "final_action",
        "active_argmax", "active_pipeline", "task_argmax", "task_pipeline",
        "context_argmax", "context_pipeline",
        "error_class_active", "error_class_task", "error_class_context",
    ]
    with (OUT / "results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    environment = json.loads(ENV.read_text(encoding="utf-8"))
    summary = {
        "versions": versions,
        "models": {},
        "single_pass": True,
        "r0_used_as_gold": False,
        "gold": "final_adjudication",
    }
    errors = {}
    for name in MODELS:
        gold = [row["final_action"] for row in rows]
        summary["models"][name] = {
            "argmax": metrics(gold, [row[f"{name}_argmax"] for row in rows]),
            "pipeline": metrics(gold, [row[f"{name}_pipeline"] for row in rows]),
            "sha256": sha256(MODELS[name]),
            "feature_version": environment["features"]["models"][name]["feature_version"],
        }
        errors[name] = {}
        for kind in ("match", "unnecessary_disclosure", "necessary_information_deleted",
                     "incorrect_pause", "pause_replaced_by_delete", "action_mismatch_other"):
            errors[name][kind] = [row["unit_id"] for row in rows if row[f"error_class_{name}"] == kind]
        errors[name]["listed_after_hard_checks"] = {
            kind: [row["unit_id"] for row in rows if kind in situation_flags(row["final_action"], row[f"{name}_pipeline"], row["category"])]
            for kind in ("unnecessary_disclosure", "necessary_information_deleted", "incorrect_pause", "should_pause_but_continued")
        }
        errors[name]["listed_before_hard_checks"] = {
            kind: [row["unit_id"] for row in rows if kind in situation_flags(row["final_action"], row[f"{name}_argmax"], row["category"])]
            for kind in ("unnecessary_disclosure", "necessary_information_deleted", "incorrect_pause", "should_pause_but_continued")
        }
    final_payload = json.loads(FINAL.read_text(encoding="utf-8"))
    experiment = {
        "date": "2026-11-02",
        "command": "delivery/app/scripts/eval_blind31_once_20261102.py",
        "single_pass": True,
        "labels_modified": False,
        "weights_modified": False,
        "rules_modified": False,
        "retrained": False,
        "r0_used_as_gold": False,
        "freeze": json.loads(FREEZE.read_text(encoding="utf-8")),
        "data": {
            "gold_file": "03_数据与人工复核/校园必要性盲标_20261102/版本/最终裁定.json",
            "gold_sha256": versions["final_adjudication"],
            "source": final_payload.get("source"),
            "source_sha256": final_payload.get("source_sha256"),
            "composition": "3人复核加1人审核后的合并裁定",
            "individual_reviewer_files_present": False,
            "traceable_independent_annotation_process": False,
            "units": len(rows),
            "original_documents": "03_数据与人工复核/校园必要性盲标_20261102/n01.json–n12.json",
            "original_sha256": environment["blanks"]["original_sha256"],
        },
        "models": {
            name: {
                "file": path.name,
                "sha256": sha256(path),
                "feature_version": environment["features"]["models"][name]["feature_version"],
                "feature_builder": environment["features"]["models"][name]["feature_builder"],
                "inference": "NecessityModel.score",
                "pipeline": "decide_segment",
            }
            for name, path in MODELS.items()
        },
        "active_models_json_sha256": environment["features"]["active_models_json_sha256"],
        "inputs": "同一原文、片段、类别、任务键、用户原话、接收方和身份；各模型按自身特征版本构造。",
    }
    (OUT / "confusion.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "errors.json").write_text(json.dumps(errors, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "experiment.json").write_text(json.dumps(experiment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    environment["status"] = "one_shot_completed"
    environment["predictions_run_on_31"] = True
    environment["one_shot"] = {
        "completed": True,
        "results": "delivery/app/outputs/campus_blind31_final_20261102/results.csv",
        "weights_modified": False,
    }
    ENV.write_text(json.dumps(environment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    rows, versions = load_frozen_units()
    write_reports(score_all(rows), versions)
    print("once", len(rows))


if __name__ == "__main__":
    main()
