"""Fixed software probes for public places versus residential locations.

These development probes are not human gold, blind tests, or training data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

# Defined before the lower-learning-rate candidate was evaluated.
PROBES = [
    ("public_admin", "活动地点：行政楼。", "行政楼", "LOCATION"),
    ("public_teaching", "活动地点：教学楼。", "教学楼", "LOCATION"),
    ("public_laboratory", "活动地点：实验楼。", "实验楼", "LOCATION"),
    ("public_library", "活动地点：图书馆。", "图书馆", "LOCATION"),
    ("public_gym", "活动地点：体育馆。", "体育馆", "LOCATION"),
    ("public_admin_narrative", "请到行政楼集合，随后进行培训。", "行政楼", "LOCATION"),
    ("public_room", "会议地点：教学楼301室。", "教学楼301室", "LOCATION"),
    ("public_admin_room", "培训在行政楼201会议室进行。", "行政楼201会议室", "LOCATION"),
    ("public_named_building", "集合地点为明德楼。", "明德楼", "LOCATION"),
    ("public_near_dorm_word", "宿舍检查结束后，请到行政楼集合。", "行政楼", "LOCATION"),
    ("dorm_numeric", "宿舍：3号楼402室。", "3号楼402室", "DORM"),
    ("dorm_building", "寝室在2栋305。", "2栋305", "DORM"),
    ("dorm_alpha", "住宿位置：A座312。", "A座312", "DORM"),
    ("dorm_narrative", "活动结束后返回宿舍7楼601室。", "7楼601室", "DORM"),
    ("dorm_near_event", "活动地点待定，住宿安排为B座409。", "B座409", "DORM"),
    ("dorm_chinese_room", "寝室位置为沁园二号楼三零二室。", "沁园二号楼三零二室", "DORM"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Use a new report path")
    import torch
    torch.set_num_threads(4)
    from llm_shield.m2_detect.reviewed_ner import ReviewedNERDetector
    from llm_shield.m2_detect.entity_rules import EntityDetector
    from llm_shield.m2_detect.regex_rules import RegexDetector
    from llm_shield.m2_detect.pipeline import detect_all
    ner = ReviewedNERDetector(args.model_dir, "cuda" if torch.cuda.is_available() else "cpu", decoding="bio_viterbi")
    if not ner.available:
        raise RuntimeError(ner.reason)
    reports = {}
    for name, detectors in (("bert", [ner]), ("combined", [RegexDetector(), EntityDetector(), ner])):
        cases = []
        for ident, text, value, category in PROBES:
            start, end = text.index(value), text.index(value) + len(value)
            spans = detect_all(text, detectors=detectors)
            target = [span for span in spans if span.start < end and start < span.end]
            cases.append({"id": ident, "text": text, "expected_category": category,
                          "target": {"start": start, "end": end},
                          "covered": any(span.category == category and span.start <= start and end <= span.end for span in target),
                          "public_misclassified_as_dorm": category == "LOCATION" and any(span.category == "DORM" for span in target),
                          "residential_misclassified_as_public": category == "DORM" and any(span.category in {"LOCATION", "ORG"} for span in target),
                          "predictions": [span.to_dict() for span in spans]})
        reports[name] = {"total": len(cases), "target_covered": sum(c["covered"] for c in cases),
                         "public_as_dorm": sum(c["public_misclassified_as_dorm"] for c in cases),
                         "residential_as_public": sum(c["residential_misclassified_as_public"] for c in cases),
                         "cases": cases}
    report = {"scope": "Handwritten development software probes; no human review and no training",
              "model_dir": str(args.model_dir.resolve()), "ner_decoding": "bio_viterbi", "results": reports}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: {key: value for key, value in result.items() if key != "cases"}
                      for name, result in reports.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
