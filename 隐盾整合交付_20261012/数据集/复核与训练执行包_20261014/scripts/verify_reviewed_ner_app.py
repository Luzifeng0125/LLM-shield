"""Replay validation through the saved model and actual application detector chain."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_gold_ner as evaluation


def verify(args):
    app = args.app.resolve()
    out = args.out.resolve()
    if out.exists():
        raise ValueError("Use a new output directory")
    _, rows = evaluation.load_gold(args.data)
    sys.path.insert(0, str(app))
    import torch
    torch.set_num_threads(4)
    os.environ["SHIELD_REVIEWED_NER_MODEL_DIR"] = str(args.model.resolve())
    os.environ["SHIELD_REVIEWED_NER_DEVICE"] = args.device
    from llm_shield.m2_detect.pipeline import build_detectors, detect_all
    started = time.perf_counter()
    chain = build_detectors(use_campus_ner=False)
    candidate = next(detector for detector in chain if detector.name == "reviewed_ner")
    load_seconds = time.perf_counter() - started
    if not candidate.available:
        raise RuntimeError(candidate.reason)
    out.mkdir(parents=True)
    scores = {}
    for name, detectors in (("model_only", [candidate]), ("application_combined", chain)):
        predictions, timings = {}, []
        for row in rows:
            started = time.perf_counter()
            result = detect_all(row["text"], detectors=detectors)
            timings.append((time.perf_counter() - started) * 1000)
            predictions[row["id"]] = evaluation.validate_entities(
                row["text"], [span.to_dict() for span in result], prediction=True)
        report, prediction_rows, errors = evaluation.score(rows, predictions)
        report["latency_ms"] = {"median": statistics.median(timings),
                                "p95": sorted(timings)[int(0.95 * (len(timings) - 1))]}
        scores[name] = report
        for suffix, values in (("predictions", prediction_rows), ("errors", errors)):
            (out / f"{name}_{suffix}.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in values), encoding="utf-8")
    # Exercise real tokenizer overflow and Unicode offsets beyond one model window.
    long_text = ("🙂会议材料：张三负责登记，联系电话13800138000。\n" * 160).strip()
    long_result = detect_all(long_text, detectors=chain)
    assert long_result and max(span.end for span in long_result) > len(long_text) - 100
    assert all(span.text == long_text[span.start:span.end] for span in long_result)
    assert all(left.end <= right.start for left, right in zip(long_result, long_result[1:]))
    manifest = candidate.manifest
    report = {"split": "validation", "documents": len(rows), "test_evaluated": False,
              "model_dir": str(args.model.resolve()), "device": args.device,
              "data_sha256": evaluation.sha256(args.data),
              "detectors": [type(detector).__name__ for detector in chain],
              "model_load_seconds": load_seconds, "scores": scores,
              "long_text_smoke": {"characters": len(long_text), "entities": len(long_result),
                                  "offsets_and_nonoverlap_passed": True},
              "training_code_still_matches": {
                  name: Path(name).is_file() and hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest
                  for name, digest in manifest["code_sha256"].items()},
              "app_source_sha256": {str(path.relative_to(app)): evaluation.sha256(path)
                                    for path in sorted((app / "llm_shield").rglob("*.py"))},
              "scope": "Validation NER and local detector integration; not full egress safety."}
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    verify(parser.parse_args())
