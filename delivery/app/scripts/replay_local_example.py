"""Offline user-example replay; raw input stays in ignored outputs, never training."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "scripts"))


def expected_spans(source):
    text = source["text"]
    entities = []
    for category, values in source["expected_entities"].items():
        for value in values:
            if not value or text.count(value) != 1:
                raise ValueError("Expected each explicit field value exactly once")
            start = text.index(value)
            entities.append({"start": start, "end": start + len(value), "category": category})
    return sorted(entities, key=lambda entity: entity["start"])


def detection_metrics(expected, predicted):
    key = lambda item: (item["start"], item["end"], item["category"])
    gold = {key(item) for item in expected}
    actual = {key(item) for item in predicted}
    coverage = [any(p["category"] == item["category"] and p["start"] <= item["start"]
                    and item["end"] <= p["end"] for p in predicted) for item in expected]
    return {"expected": len(gold), "predicted": len(actual), "strict_tp": len(gold & actual),
            "strict_fp": len(actual - gold), "strict_fn": len(gold - actual),
            "fully_covered": sum(coverage),
            "missed_or_wrong_boundary": [item for item in expected if key(item) not in actual],
            "extra_or_wrong_boundary": [item for item in predicted if key(item) not in gold],
            "counts": dict(Counter(item["category"] for item in predicted))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--ner-model", type=Path, required=True)
    parser.add_argument("--action-model", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--decoding", choices=("greedy", "bio_viterbi"), default="greedy")
    args = parser.parse_args()
    local_outputs = (APP / "outputs").resolve()
    if not args.input.resolve().is_relative_to(local_outputs) or not args.out.resolve().is_relative_to(local_outputs):
        raise ValueError("Private input and reports must stay under ignored local outputs")
    if args.out.exists():
        raise ValueError("Use a new report path")
    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    expected = expected_spans(source)
    text = source["text"]
    import torch
    torch.set_num_threads(4)
    from start_reviewed_candidate import preflight
    preflight(args.ner_model.resolve(), "cuda" if torch.cuda.is_available() else "cpu",
              args.action_model, args.decoding)
    from llm_shield.m2_detect.pipeline import build_detectors, detect_all
    from llm_shield.m6_transform.mapping import get_table
    from llm_shield.m7_egress.gateway import EgressGateway
    from llm_shield.m7_egress.llm_client import OpenAICompatLLM
    from llm_shield.pipeline import run_pipeline
    from llm_shield.schema import Material, ShieldRequest
    chain = build_detectors(False, False)
    ner = next(detector for detector in chain if detector.name == "reviewed_ner")
    configurations = {"rules": [detector for detector in chain if detector is not ner],
                      "bert": [ner], "combined": chain}
    scores = {}
    for name, detectors in configurations.items():
        spans = detect_all(text, detectors=detectors)
        # Persist coordinates/category only, not the user's names/contact values.
        predictions = [{"start": span.start, "end": span.end, "category": span.category}
                       for span in spans]
        scores[name] = detection_metrics(expected, predictions)
    tool_send = EgressGateway.send_to_tool
    def without_file(gateway, *positional, **kwargs):
        kwargs["write_file"] = False
        return tool_send(gateway, *positional, **kwargs)
    runs = {}
    with patch.object(OpenAICompatLLM, "chat_messages", side_effect=AssertionError("External model forbidden")) as external:
        with patch.object(EgressGateway, "send_to_tool", without_file):
            for task in ("activity_stats", "meeting_minutes", "project_intro"):
                session = f"private-roster-replay-{task}"
                get_table().clear_session(session)
                result = run_pipeline(ShieldRequest(session, "student_leader", task, "external_model",
                    [Material("private-example", "uploaded", "", text)],
                    user_instruction="核对活动签到、排班、群组通知和紧急联络信息")).to_dict()
                residuals = {field: [item for item in expected
                                    if text[item["start"]:item["end"]] in result[field]]
                             for field in ("sanitized_text", "model_output", "egress_text")}
                runs[task] = {"ok": result["ok"], "paused": result["paused"],
                              "pause_reason": result["pause_reason"], "decisions": result["decisions"],
                              "boundaries": result["boundaries"], "residual_original_fields": residuals,
                              "timings": result["timings"]}
                get_table().clear_session(session)
        assert external.call_count == 0
    report = {"source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
              "characters": len(text), "annotation_origin": source["annotation_origin"],
              "human_reviewed": False, "used_for_training": False, "external_calls": 0,
              "decoding": args.decoding,
              "scope": "One user-example diagnostic; task scenarios are not human-adjudicated action labels",
              "detection": scores, "task_scenarios": runs}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"characters": len(text), "detection": {name: {key: value for key, value in score.items()
                     if key not in {"missed_or_wrong_boundary", "extra_or_wrong_boundary"}} for name, score in scores.items()},
                     "scenarios": {task: {"ok": run["ok"], "paused": run["paused"],
                                          "actions": [decision["action"] for decision in run["decisions"]],
                                          "remaining_original_fields": {key: len(value) for key, value in run["residual_original_fields"].items()}}
                                   for task, run in runs.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
