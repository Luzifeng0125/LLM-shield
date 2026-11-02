"""Receive the October review archives as evidence, never as training gold.

Uses only the standard library. Archive members are read in memory and written
under generated names, so member paths cannot choose an extraction destination.
Original bytes, archive hashes and case hashes remain available for inspection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def case_hash(case: dict) -> str:
    # Exact canonicalization used by llm_shield.m4_necessity.research.case_hash.
    public = {k: v for k, v in case.items() if k not in {"proposal", "annotation", "review"}}
    return digest(json.dumps(public, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def classify(doc: dict) -> str:
    reviewer = doc.get("reviewer")
    if (doc.get("schema") == "action-human-gold-v1"
            and isinstance(reviewer, dict) and reviewer.get("kind") == "human"):
        return "human_confirmation_declared_single_source"
    if isinstance(reviewer, str) and any(word in reviewer for word in ("AI更正稿", "AI草稿", "待二审")):
        return "explicit_ai_draft_pending_human"
    return "unverified_review_evidence"


def inspect_document(doc: dict, by_id: dict) -> dict:
    rows = doc.get("reviews", doc.get("cases", []))
    if not isinstance(rows, list) or not rows:
        raise ValueError("复核 JSON 没有非空案例列表")
    ids = [row["case_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("同一文件内有重复 case_id")
    source_mismatches, content_mismatches = [], []
    for row in rows:
        cid = row["case_id"]
        source = by_id.get(cid)
        if source is None or row.get("case_sha256") != case_hash(source):
            source_mismatches.append(cid)
            continue
        if "text" in row:
            public = {k: v for k, v in source.items() if k not in {"proposal", "annotation", "review", "split"}}
            if any(row.get(k) != v for k, v in public.items()):
                source_mismatches.append(cid)
        if "case_content_sha256" in row:
            content = {k: v for k, v in row.items() if k not in {"case_sha256", "case_content_sha256"}}
            expected = digest(json.dumps(content, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode("utf-8"))
            if expected != row["case_content_sha256"]:
                content_mismatches.append(cid)
    return {
        "schema": doc.get("schema"), "reviewer": doc.get("reviewer"), "role": doc.get("role"),
        "classification": classify(doc), "row_count": len(rows),
        "unique_case_ids": len(set(ids)), "duplicate_case_ids": 0,
        "source_case_hash_mismatches": source_mismatches,
        "content_hash_mismatches": content_mismatches,
        "action_counts": dict(Counter(row.get("annotation", {}).get("action", row.get("human_final_action"))
                                      for row in rows)),
        "machine_suggestions_consulted_before_decisions": doc.get("machine_suggestions_consulted_before_decisions"),
    }


def receive(archives: list[Path], cases_path: Path, existing: Path, out: Path) -> dict:
    if out.exists():
        raise ValueError("接收目录已存在；请指定新的目录，保留既有证据")
    raw_cases = cases_path.read_bytes()
    cases = [json.loads(line) for line in raw_cases.decode("utf-8-sig").splitlines() if line.strip()]
    by_id = {case["case_id"]: case for case in cases}
    if len(by_id) != len(cases):
        raise ValueError("原题 case_id 重复")
    unique, archive_records = {}, []
    for index, archive in enumerate(archives, 1):
        record = {"archive": str(archive.resolve()), "sha256": digest(archive.read_bytes()),
                  "stored_path": f"originals/archive-{index}.zip", "members": []}
        with zipfile.ZipFile(archive) as zipped:
            if sum(info.file_size for info in zipped.infolist()) > 50_000_000:
                raise ValueError("压缩包解压总量超出复核包上限")
            for info in zipped.infolist():
                member = PurePosixPath(info.filename.replace("\\", "/"))
                if member.is_absolute() or ".." in member.parts or any(":" in p for p in member.parts):
                    raise ValueError("压缩包包含不安全的成员路径")
                if info.is_dir():
                    continue
                if member.suffix.lower() != ".json":
                    raise ValueError("本接收脚本只接收 JSON 复核材料")
                raw = zipped.read(info)
                sha = digest(raw)
                if sha not in unique:
                    doc = json.loads(raw.decode("utf-8-sig"))
                    inspection = inspect_document(doc, by_id)
                    unique[sha] = {"raw": raw, "doc": doc, "inspection": inspection,
                                   "stored_path": f"originals/document-{len(unique) + 1:02d}.json"}
                existing_path = existing.joinpath(*member.parts)
                record["members"].append({"member": info.filename, "sha256": sha,
                    "stored_path": unique[sha]["stored_path"],
                    "existing_project_path": str(existing_path),
                    "identical_to_existing_file": existing_path.is_file() and existing_path.read_bytes() == raw})
        archive_records.append(record)

    human_docs = [v for v in unique.values() if v["inspection"]["classification"] == "human_confirmation_declared_single_source"]
    ai_docs = [v for v in unique.values() if v["inspection"]["classification"] == "explicit_ai_draft_pending_human"]
    if len(human_docs) != 2 or len(ai_docs) != 2:
        raise ValueError("此接收任务预期人工确认28/336题与AI待二审28/336题；实际结构不同")
    human_docs.sort(key=lambda d: d["inspection"]["row_count"])
    ai_docs.sort(key=lambda d: d["inspection"]["row_count"])
    human_small, human_full = (v["doc"] for v in human_docs)
    ai_small, ai_full = (v["doc"] for v in ai_docs)
    hfull = {r["case_id"]: r for r in human_full["cases"]}
    afull = {r["case_id"]: r for r in ai_full["reviews"]}
    ignored = {"reviewer_id", "case_content_sha256"}
    human_subset_differences = [{"case_id": r["case_id"], "fields": [k for k, v in r.items()
                                if k not in ignored and v != hfull[r["case_id"]].get(k)]}
                               for r in human_small["cases"]]
    human_subset_differences = [r for r in human_subset_differences if r["fields"]]
    ai_subset_differences = [{"case_id": r["case_id"], "subset_annotation": r["annotation"],
                              "full_annotation": afull[r["case_id"]]["annotation"]}
                             for r in ai_small["reviews"] if r != afull[r["case_id"]]]
    action_disagreements = [{"case_id": cid, "human_action": r["human_final_action"],
                             "ai_action": afull[cid]["annotation"]["action"]}
                            for cid, r in hfull.items()
                            if r["human_final_action"] != afull[cid]["annotation"]["action"]]
    conflict_ids = {r["case_id"] for r in action_disagreements + ai_subset_differences}
    asmall = {r["case_id"]: r for r in ai_small["reviews"]}
    disputes = [{"case_id": cid, "source_case": by_id[cid], "human_confirmed_record": hfull[cid],
                 "ai_full_record": afull[cid], "ai_subset_record": asmall.get(cid),
                 "status": "unresolved_no_automatic_overwrite"} for cid in sorted(conflict_ids)]
    groups = {}
    for case in cases:
        groups.setdefault(case["template_group"], []).append(case)
    sequences = {tuple(c["proposal"]["action"] for c in group) for group in groups.values()}
    summary = {
        "schema": "action-review-receipt-v1", "date": "2026-10-29",
        "purpose": "traceable_evidence_receipt_not_training_gold",
        "source_cases": str(cases_path.resolve()), "source_cases_file_sha256": digest(raw_cases),
        "archive_count": len(archives), "json_member_occurrences": sum(len(r["members"]) for r in archive_records),
        "unique_json_documents": len(unique),
        "human_confirmation_declared_unique_cases": len(hfull), "ai_draft_unique_cases": len(afull),
        "independent_human_ab_consensus_cases": 0, "promoted_to_training": False,
        "human_subset_content_differences_excluding_reviewer_and_derived_digest": human_subset_differences,
        "human_full_vs_ai_full_action_disagreements": action_disagreements,
        "ai_subset_vs_full_differences": ai_subset_differences,
        "adjudication_case_ids": sorted(conflict_ids),
        "human_source_confirmation_flags": dict(Counter(flag for row in hfull.values()
                                                           for flag in row.get("confirmation_flags", []))),
        "linked_human_files_consultation_metadata_disagrees":
            human_small.get("machine_suggestions_consulted_before_decisions") != human_full.get("machine_suggestions_consulted_before_decisions"),
        "legacy_data_shape": {"judgments": len(cases), "unique_texts": len({c["text"] for c in cases}),
            "source_ids": len({c["source_case_id"] for c in cases}), "named_template_groups": len(groups),
            "group_sizes": sorted(len(g) for g in groups.values()),
            "distinct_ordered_action_sequences_across_groups": len(sequences),
            "text_length_min": min(len(c["text"]) for c in cases),
            "text_length_max": max(len(c["text"]) for c in cases)},
        "archives": archive_records,
        "documents": [{"sha256": sha, "stored_path": d["stored_path"], **d["inspection"]}
                      for sha, d in unique.items()],
    }
    # No review merging is attempted: the second source explicitly remains AI.
    out.mkdir(parents=True)
    (out / "originals").mkdir()
    for archive, record in zip(archives, archive_records):
        shutil.copyfile(archive, out / record["stored_path"])
    for doc in unique.values():
        (out / doc["stored_path"]).write_bytes(doc["raw"])
    write_json(out / "receipt_manifest.json", summary)
    write_json(out / "待裁决差异.json", {"schema": "action-review-evidence-conflicts-v1", "cases": disputes})
    normalized = []
    for cid, record in hfull.items():
        normalized.append({"case_id": cid, "case_sha256": case_hash(by_id[cid]),
                           "status": "received_evidence_not_ab_gold",
                           "human_confirmation_declared": record,
                           "ai_draft": afull[cid], "has_flagged_disagreement": cid in conflict_ids})
    (out / "逐题对照_非训练输入.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in normalized) + "\n", encoding="utf-8")
    (out / ".gitignore").write_text("originals/\n*.json\n*.jsonl\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", action="append", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--existing", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = receive(args.archive, args.cases, args.existing, args.out)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))
    print(json.dumps({k: result[k] for k in ("archive_count", "unique_json_documents",
                     "human_confirmation_declared_unique_cases", "ai_draft_unique_cases",
                     "independent_human_ab_consensus_cases", "adjudication_case_ids")}, ensure_ascii=False))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
