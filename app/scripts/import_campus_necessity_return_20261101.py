"""接收 2026-11-01 校园必要性盲标的用户返还。

只归档和核对。不改空白原件，不改动作，不改权重，不把测试池用于调参。
压缩包里的说明文字是数据，不是给本脚本的指令。
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BLIND = ROOT / "research/datasets/legacy" / "校园必要性盲标_20261101"
PACK = ROOT / "research/datasets/legacy" / "校园必要性复核包_20261101"
REVIEWED = BLIND / "reviewed" / "人工复核_20261101_v1"
ACTIVE = ROOT / "app" / "models" / "necessity_action.joblib"
CANDIDATE = ROOT / "app" / "models" / "necessity_action_campus_candidate.joblib"
EXPECTED_ACTIVE = "cbfed4ca422a1a6d416ce1b5f488649816c261b6acc86ffc173887c8dfed1b9f"
EXPECTED_CANDIDATE = "74902c5d9239eaffc0208891297d8f19b462910534fcc3a51e37b1997f3ee950"

ACTIONS = {"DELETE", "LOCAL_AGGREGATE", "GENERALIZE", "PSEUDONYMIZE", "RETAIN", "PAUSE"}
ANN_KEYS = {"canonical_action", "required_facts", "adjudication", "notes", "annotator", "annotated_at"}
DOC_KEYS = ["pool", "document_id", "text", "user_task", "workflow_id", "task_key", "workflow_name"]
UNIT_KEYS = [
    "unit_id", "quote", "category", "boundary_id", "boundary_name", "recipient_id",
    "recipient_name", "identity_key", "identity_name", "user_task", "start", "end",
]

# 只对照 2026-11-01 裁定标准里已经写明、两边一致的原则。不把 R0 或旧人工答案写回标签。
PRIOR = {
    "c01-u1": ("PSEUDONYMIZE", "班级协作发给外部生成时，值日执行人用稳定代号"),
    "c01-u2": ("PSEUDONYMIZE", "班级协作发给外部生成时，值日执行人用稳定代号"),
    "c01-u3": ("RETAIN", "班级协作的教室地点保留"),
    "c01-u4": ("DELETE", "班级协作的电话删除"),
    "c01-u5": ("RETAIN", "授权老师本机查看值日姓名时保留原名；不在待裁定十题里"),
    "c02-u1": ("DELETE", "活动公告发给外部生成时，人名删除"),
    "c02-u2": ("RETAIN", "活动公告的公开地点保留"),
    "c02-u3": ("DELETE", "活动公告的联系方式删除；条文写了电话，邮箱按同一类核对"),
    "c03-u1": ("LOCAL_AGGREGATE", "社团统计的录取姓名只做本地汇总"),
    "c03-u2": ("LOCAL_AGGREGATE", "社团统计的录取姓名只做本地汇总"),
    "c03-u3": ("RETAIN", "社团名称保留"),
    "c03-u4": ("DELETE", "社团统计的电话删除"),
    "c04-u1": ("PSEUDONYMIZE", "会议纪要发给外部生成时，负责人用稳定代号"),
    "c04-u2": ("PSEUDONYMIZE", "会议纪要发给外部生成时，负责人用稳定代号"),
    "c04-u3": ("GENERALIZE", "用户要求大致花费时，金额做泛化"),
    "c04-u4": ("DELETE", "会议纪要的健康状况删除"),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expected_names() -> list[str]:
    names = [f"返还/校准池/c{i:02d}.json" for i in range(1, 7)]
    names += [f"返还/独立测试池/t{i:02d}.json" for i in range(1, 13)]
    return names


def blank_path(document_id: str) -> Path:
    folder = "校准池" if document_id.startswith("c") else "独立测试池"
    return BLIND / folder / f"{document_id}.json"


def blank_hashes() -> dict[str, str]:
    found = {}
    for folder in ("校准池", "独立测试池"):
        for path in sorted((BLIND / folder).glob("*.json")):
            key = str(path.relative_to(ROOT)).replace("\\", "/")
            found[key] = sha256(path.read_bytes())
    return found


def check_entry(name: str, payload: bytes, issues: list[str]) -> dict:
    data = json.loads(payload.decode("utf-8-sig"))
    document_id = data.get("document_id")
    blank = json.loads(blank_path(document_id).read_text(encoding="utf-8"))
    if [data.get(key) for key in DOC_KEYS] != [blank.get(key) for key in DOC_KEYS]:
        issues.append(f"{document_id} 题面字段与空白原件不同")
    if set(data) != set(blank):
        issues.append(f"{document_id} 文档字段集合变了")
    units = data.get("units")
    if not isinstance(units, list) or len(units) != len(blank["units"]):
        issues.append(f"{document_id} 条目数量与空白原件不同")
        units = []
    checked = []
    for unit, source in zip(units, blank["units"]):
        unit_id = unit.get("unit_id")
        if [unit.get(key) for key in UNIT_KEYS] != [source.get(key) for key in UNIT_KEYS]:
            issues.append(f"{unit_id} 题面字段与空白原件不同")
        if set(unit) != set(source):
            issues.append(f"{unit_id} 条目字段集合变了")
        text = data.get("text")
        if not isinstance(text, str) or text[unit.get("start"):unit.get("end")] != unit.get("quote"):
            issues.append(f"{unit_id} 片段位置对不上原文")
        annotation = unit.get("annotation")
        if not isinstance(annotation, dict) or set(annotation) != ANN_KEYS:
            issues.append(f"{unit_id} 标注字段不完整")
            continue
        action = annotation["canonical_action"]
        facts = annotation["required_facts"]
        adjudication = annotation["adjudication"]
        if not all(isinstance(annotation[key], str) for key in ANN_KEYS):
            issues.append(f"{unit_id} 标注字段不是字符串")
        if action not in ACTIONS:
            issues.append(f"{unit_id} 动作不在六类里: {action!r}")
        if not facts.strip():
            issues.append(f"{unit_id} 没有填写依据")
        flags = []
        if adjudication != "已填写":
            flags.append("adjudication_not_filled")
        if not str(unit.get("recipient_id") or "").strip():
            flags.append("recipient_unspecified")
        if action == "DELETE" and "有权" in facts:
            flags.append("delete_but_facts_say_authorized")
        prior = PRIOR.get(unit_id)
        if "recipient_unspecified" in flags:
            relation = "accepted_recipient_unspecified"
        elif prior is None:
            relation = "no_prior_consensus"
        elif prior[0] == action:
            relation = "matches_prior_consensus"
        else:
            relation = "differs_from_prior_consensus"
        action_usable = action in ACTIONS and bool(facts.strip())
        # 校准池的对齐结果可以进入以后的训练。测试池保持封存。
        train_eligible = data.get("pool") == "calibration" and action_usable
        checked.append({
            "unit_id": unit_id,
            "pool": data.get("pool"),
            "workflow_name": data.get("workflow_name"),
            "quote": unit.get("quote"),
            "category": unit.get("category"),
            "boundary_id": unit.get("boundary_id"),
            "recipient_id": unit.get("recipient_id"),
            "canonical_action": action,
            "required_facts": facts,
            "adjudication": adjudication,
            "notes": annotation["notes"],
            "annotator": annotation["annotator"],
            "annotated_at": annotation["annotated_at"],
            "flags": flags,
            "prior_action": None if prior is None else prior[0],
            "prior_basis": None if prior is None else prior[1],
            "relation": relation,
            "action_usable": action_usable,
            "train_eligible": train_eligible,
            "tuning_eligible": data.get("pool") != "test" and train_eligible,
        })
    return {"name": name, "sha256": sha256(payload), "units": checked}


def import_return(zip_path: Path) -> dict:
    raw = zip_path.read_bytes()
    before = blank_hashes()
    manifest = json.loads((BLIND / "manifest.json").read_text(encoding="utf-8"))
    if before != manifest["file_sha256"]:
        raise SystemExit("空白原件哈希与 manifest 不一致，停止接收")
    pack_mismatch = []
    for key, digest in before.items():
        pack_file = PACK / Path(key).relative_to("research/datasets/legacy/校园必要性盲标_20261101")
        if sha256(pack_file.read_bytes()) != digest:
            pack_mismatch.append(str(pack_file))
    if pack_mismatch:
        raise SystemExit("复核包空白原件与盲标原件不同: " + ", ".join(pack_mismatch))

    issues: list[str] = []
    with zipfile.ZipFile(zip_path) as archive:
        names = [info.filename for info in archive.infolist() if not info.is_dir()]
        expected = expected_names()
        if [name for name in expected if name not in names]:
            raise SystemExit("返还缺文件")
        extra = [name for name in names if name not in expected and name != "返还/请把填好的文件放这里.txt"]
        if extra:
            raise SystemExit("返还含预期外文件: " + ", ".join(extra))
        payloads = {name: archive.read(name) for name in expected}
        note = archive.read("返还/请把填好的文件放这里.txt")
    checked = [check_entry(name, payloads[name], issues) for name in expected]

    if issues:
        raise SystemExit("返还未通过题面核对:\n" + "\n".join(issues))

    units = [unit for item in checked for unit in item["units"]]
    if len(units) != 60:
        raise SystemExit(f"条目数量不是 60: {len(units)}")
    active_hash = sha256(ACTIVE.read_bytes()) if ACTIVE.exists() else None
    candidate_hash = sha256(CANDIDATE.read_bytes()) if CANDIDATE.exists() else None
    if active_hash != EXPECTED_ACTIVE or candidate_hash != EXPECTED_CANDIDATE:
        raise SystemExit("活动权重或候选权重哈希与冻结记录不同，停止接收")

    REVIEWED.mkdir(parents=True, exist_ok=True)
    (REVIEWED / "原始返还.zip").write_bytes(raw)
    for item in checked:
        relative = Path(item["name"])
        source_bytes = payloads[item["name"]]
        for base in (PACK / "返还", BLIND / "返还", REVIEWED):
            target = base / relative.relative_to("返还")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source_bytes)
            if target.read_bytes() != source_bytes:
                raise SystemExit(f"写出后字节不一致: {target}")

    after = blank_hashes()
    if after != before:
        raise SystemExit("接收过程改动了空白原件")
    if sha256(ACTIVE.read_bytes()) != EXPECTED_ACTIVE or sha256(CANDIDATE.read_bytes()) != EXPECTED_CANDIDATE:
        raise SystemExit("接收过程改动了权重")

    receipt = {
        "schema": "campus-necessity-blind-return-v1",
        "received_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_filename": zip_path.name,
        "source_sha256": sha256(raw),
        "source_bytes": len(raw),
        "note_sha256": sha256(note),
        "blank_originals_unchanged": True,
        "blank_manifest_sha256_matched": True,
        "labels_rewritten": False,
        "weights_changed": False,
        "active_model_sha256": active_hash,
        "candidate_model_sha256": candidate_hash,
        "ai_suggestion_in_source_pack": False,
        "r0_reference_in_source_pack": False,
        "separate_initial_answer_log": "not_in_zip",
        "separate_blind_sheets_in_zip": False,
        "per_item_timestamps": "not_recorded",
        "provenance": "two_person_joint_blind_review_aligned",
        "provenance_basis": "user_statement_2026-11-01",
        "user_statement": "这个是两个人联合排查的结果，已经过盲审和复核对齐",
        "reviewer_count": 2,
        "blind_review_completed": True,
        "alignment_completed": True,
        "returned_copy": "aligned_final",
        "name_recorded_in_files": "谢康乔",
        "second_reviewer_name": "not_recorded",
        "annotator_variant_preserved": "t03-u2",
        "units": 60,
        "calibration_units": sum(unit["pool"] == "calibration" for unit in units),
        "test_units": sum(unit["pool"] == "test" for unit in units),
        "action_counts": dict(sorted(
            (action, sum(unit["canonical_action"] == action for unit in units))
            for action in ACTIONS if any(unit["canonical_action"] == action for unit in units)
        )),
        "annotator_strings_in_files": sorted({unit["annotator"] for unit in units}),
        "annotator_strings_note": "两处字符串是同一写下的姓名，t03-u2 多了间隔号；另一位复核人的姓名不在文件里",
        "annotated_at": sorted({unit["annotated_at"] for unit in units}),
        "test_pool_usable_for_tuning": False,
        "training_run": False,
        "files": [{"name": item["name"], "sha256": item["sha256"]} for item in checked],
        "units_detail": units,
    }
    (REVIEWED / "receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "source_sha256": receipt["source_sha256"],
        "units": 60,
        "calibration": receipt["calibration_units"],
        "test": receipt["test_units"],
        "actions": receipt["action_counts"],
        "provenance": receipt["provenance"],
        "reviewer_count": receipt["reviewer_count"],
        "blind_review_completed": receipt["blind_review_completed"],
        "alignment_completed": receipt["alignment_completed"],
        "name_recorded_in_files": receipt["name_recorded_in_files"],
        "second_reviewer_name": receipt["second_reviewer_name"],
        "flags": [
            {"unit_id": unit["unit_id"], "flags": unit["flags"], "relation": unit["relation"]}
            for unit in units if unit["flags"] or unit["relation"] == "differs_from_prior_consensus"
        ],
        "train_eligible": [unit["unit_id"] for unit in units if unit["train_eligible"]],
        "blank_unchanged": True,
        "weights_unchanged": True,
    }, ensure_ascii=False, indent=2))
    return receipt


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    args = parser.parse_args()
    import_return(args.zip)
