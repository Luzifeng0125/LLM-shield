"""Evaluate the existing reviewed BERT on field_v1 only; no training or sealed-test access."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "scripts"))

from eval_field_v1 import FIELD_JSONL, cases_from_jsonl, evaluate
from llm_shield.m2_detect.entity_rules import EntityDetector
from llm_shield.m2_detect.regex_rules import RegexDetector
from eval.reviewed_ner import ReviewedNERDetector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--decoding", choices=("greedy", "bio_viterbi"), default="greedy")
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Use a new output path; prior reports are preserved")
    import torch
    torch.set_num_threads(4)
    cases = cases_from_jsonl(FIELD_JSONL)
    model = ReviewedNERDetector(args.model_dir, device=args.device, decoding=args.decoding)
    if not model.available:
        raise RuntimeError(model.reason)
    configurations = {
        "rules_baseline": [RegexDetector(), EntityDetector()],
        "reviewed_bert_only": [model],
        "rules_plus_reviewed_bert": [RegexDetector(), EntityDetector(), model],
    }
    results = {}
    for name, detectors in configurations.items():
        results[name] = evaluate(cases, detectors, name)
        print(json.dumps({"configuration": name,
                          "metrics": {mode: value["overall"]
                                      for mode, value in results[name]["modes"].items()}},
                         ensure_ascii=False), flush=True)
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": "field_v1", "dataset_sha256": hashlib.sha256(FIELD_JSONL.read_bytes()).hexdigest(),
        "documents": len(cases), "entities": sum(len(case["entities"]) for case in cases),
        "model_dir": str(args.model_dir.resolve()), "device": args.device,
        "decoding": args.decoding,
        "model_manifest_sha256": hashlib.sha256(
            (args.model_dir / "artifact_manifest.json").read_bytes()).hexdigest(),
        "training_performed": False, "test_gold_accessed": False,
        "scope": "Existing handwritten benchmark diagnostic; not newly blind or real-user production safety.",
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
