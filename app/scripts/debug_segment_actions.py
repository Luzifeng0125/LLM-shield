"""Compare segment models on fixed software fixtures; these are not human gold."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from llm_shield.m2_detect.entity_rules import EntityDetector
from llm_shield.m2_detect.regex_rules import RegexDetector
from llm_shield.m2_detect.pipeline import detect_and_segment
from llm_shield.m3_decide.decision import decide_all
from llm_shield.m4_necessity.model import NecessityModel

# Fixed before candidate scoring; cases diagnose compositional coverage only.
FIXTURES = [
    ("meeting_phone", "meeting_minutes", "联系电话13923456789。", ["DELETE"]),
    ("meeting_email", "meeting_minutes", "联系邮箱：committee@example.org。", ["DELETE"]),
    ("separate_name_phone", "meeting_minutes", "姓名：王芳。联系电话13812345678。", ["PSEUDONYMIZE", "DELETE"]),
    ("reported_mixed_request", "meeting_minutes", "负责人张明负责海报，周五交稿；联系电话13923456789。", ["PSEUDONYMIZE", "DELETE"]),
    ("project_budget_phone", "project_intro", "预算金额12800元。联系电话13812345678。", ["DELETE", "DELETE"]),
    ("meeting_grade", "meeting_minutes", "成绩92分。", ["DELETE"]),
    ("meeting_student_id", "meeting_minutes", "学号：2026012345。", ["DELETE"]),
    ("public_organization", "meeting_minutes", "组织名称：计算机学院。", ["RETAIN"]),
    ("meeting_location", "meeting_minutes", "活动地点：行政楼。", ["RETAIN"]),
    ("activity_count", "activity_stats", "姓名：张明。姓名：李晓华。", ["LOCAL_AGGREGATE", "LOCAL_AGGREGATE"]),
    ("project_person", "project_intro", "姓名：李晓华。", ["GENERALIZE"]),
    ("meeting_credential", "meeting_minutes", "口令 api_key=ClubSecret2026。", ["DELETE"]),
]


def evaluate(model, detectors):
    rows = []
    for ident, task, text, expected in FIXTURES:
        _, segments = detect_and_segment(text, detectors=detectors)
        decisions = decide_all(segments, task, "external_model", "student_leader", model.score)
        actual = [decision.action.value for decision in decisions]
        rows.append({"id": ident, "text": text, "task": task, "expected": expected,
                     "actual": actual, "matched": actual == expected,
                     "segments": [{"text": segment.text, "context": segment.context,
                                   "categories": sorted({span.category for span in segment.spans}),
                                   "decision": decision.to_dict()}
                                  for segment, decision in zip(segments, decisions)]})
    return {"matched": sum(row["matched"] for row in rows), "total": len(rows),
            "pause_cases": sum("PAUSE" in row["actual"] for row in rows), "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ner-model", type=Path)
    parser.add_argument("--ner-decoding", choices=("greedy", "bio_viterbi"), default="greedy")
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Use a new report path")
    detectors = [RegexDetector(), EntityDetector()]
    if args.ner_model:
        import torch
        torch.set_num_threads(4)
        from eval.reviewed_ner import ReviewedNERDetector
        ner = ReviewedNERDetector(args.ner_model, device="cuda" if torch.cuda.is_available() else "cpu",
                                   decoding=args.ner_decoding)
        if not ner.available:
            raise RuntimeError(ner.reason)
        detectors.append(ner)
    baseline, candidate = NecessityModel(), NecessityModel(args.candidate)
    if not baseline.available or not candidate.available:
        raise RuntimeError("Both model artifacts must be available")
    results = {"baseline": evaluate(baseline, detectors), "candidate": evaluate(candidate, detectors)}
    report = {"scope": "Predeclared software fixtures, not human gold or general action accuracy",
              "detectors": [detector.name for detector in detectors],
              "ner_decoding": args.ner_decoding,
              "candidate": str(args.candidate.resolve()), "results": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: {key: result[key] for key in ("matched", "total", "pause_cases")}
                      for name, result in results.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
