"""Measure each local stage on frozen diagnostics; never train or call a cloud LLM."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import sys
import time

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parents[1]
sys.path[:0] = [str(APP), str(APP / "scripts")]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def parser_checks():
    from llm_shield.m1_access.file_loader import parse_upload
    from docx import Document
    from openpyxl import Workbook
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    marker = "stage-20261102"
    payloads = [("txt", marker.encode()), ("md", ("# " + marker).encode()),
                ("csv", f"item,value\n{marker},1\n".encode()),
                ("json", json.dumps({"text": marker}).encode())]
    document = Document()
    document.add_paragraph(marker)
    output = io.BytesIO()
    document.save(output)
    payloads.append(("docx", output.getvalue()))
    book = Workbook()
    book.active.append(["item", "value"])
    book.active.append([marker, 1])
    output = io.BytesIO()
    book.save(output)
    payloads.append(("xlsx", output.getvalue()))
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 50 750 Td ({marker}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    payloads.append(("pdf", output.getvalue()))
    results = []
    for suffix, data in payloads:
        try:
            material = parse_upload(data, "probe." + suffix, persist=False)
            passed = marker in material.text or marker in json.dumps(material.rows)
            results.append({"format": suffix, "passed": passed})
        except Exception as exc:
            results.append({"format": suffix, "passed": False, "error_type": type(exc).__name__})
    return {"passed": sum(row["passed"] for row in results), "total": len(results),
            "checks": results, "scope": "Each format has one synthetic smoke fixture; scanned PDFs/OCR are not tested."}


def ner_evaluation(detector):
    from eval_field_v1 import cases_from_jsonl, FIELD_JSONL, evaluate
    from llm_shield.m2_detect.pipeline import detect_all, segmentize, attach_spans
    from llm_shield.m2_detect.regex_rules import RegexDetector
    from llm_shield.m2_detect.entity_rules import EntityDetector
    from llm_shield.m2_detect.gliner_ner import SEMANTIC_CATEGORIES
    from llm_shield.schema import Span
    cases = cases_from_jsonl(FIELD_JSONL)
    semantic = set(SEMANTIC_CATEGORIES)
    groups = {
        "format_regex": ([RegexDetector()], "format_categories_only"),
        "rules_baseline": ([RegexDetector(), EntityDetector()], "all_categories"),
        "gliner_semantic": ([detector], "five_semantic_categories_only"),
        "fused": ([RegexDetector(), EntityDetector(detect_org_location=False), detector], "all_categories"),
    }
    results, fused = {}, {}
    for name, (detectors, scope) in groups.items():
        cache, latencies = {}, []
        for case in cases:
            started = time.perf_counter()
            cache[case["text"]] = detect_all(case["text"], detectors=detectors)
            latencies.append((time.perf_counter() - started) * 1000)
        class CachedDetector:
            def detect(self, text, columns=None, rows=None):
                return deepcopy(cache[text])
        scoped = deepcopy(cases)
        if scope != "all_categories":
            for case in scoped:
                case["entities"] = [e for e in case["entities"]
                                    if (e["category"] in semantic) == (name == "gliner_semantic")]
        measured = evaluate(scoped, [CachedDetector()], name)
        measured["total_ms"] = round(sum(latencies), 2)
        ordered = sorted(latencies)
        measured["latency"] = {"p50_ms": round(ordered[len(ordered)//2], 2),
                               "p95_ms": round(ordered[min(len(ordered)-1, int(len(ordered)*0.95))], 2),
                               "scope": "Sequential single-document inference after warmup; includes merge."}
        measured["scope"] = scope
        results[name] = measured
        print(f"NER {name}: strict F1={measured['modes']['strict']['overall']['f1']}", flush=True)
        if name == "fused":
            fused = cache
    assignment = []
    for case in cases:
        spans = fused[case["text"]]
        segments = segmentize(case["text"], spans)
        attach_spans(segments, spans, text=case["text"])
        valid = all(case["text"][s.start:s.end] == s.text and
                    sum(seg.start <= s.start and s.end <= seg.end for seg in segments) == 1
                    for s in spans)
        assignment.append(valid)
    return {"dataset": "field_v1", "sha256": digest(FIELD_JSONL), "documents": len(cases),
            "gold_entities": sum(len(c["entities"]) for c in cases),
            "scope": "Existing hand-authored development benchmark, not a new blind test.",
            "configurations": results,
            "segmentation": {"passed": sum(assignment), "total": len(assignment),
                             "metric": "Predicted span coordinates and unique segment assignment"}}


def policy_evaluation(detectors, output):
    from sklearn.metrics import f1_score
    from llm_shield.schema import Action, Span, Segment
    from llm_shield.m2_detect.pipeline import detect_and_segment, segmentize, attach_spans
    from llm_shield.m3_decide.decision import decide_segment
    from llm_shield.m4_necessity.model import NecessityModel
    from llm_shield.m6_transform.anonymizer import apply_decisions
    from llm_shield.m6_transform.mapping import MappingTable
    source = APP / "data/stage_diagnostics_20261102/cases.json"
    corpus = json.loads(source.read_text(encoding="utf-8"))
    rows = corpus["cases"]
    release = json.loads((APP / "models/MODEL_RELEASE.json").read_text(encoding="utf-8"))
    predictions, summary, detected = [], [], {}
    for row in rows:
        detected[row["id"]] = detect_and_segment(row["text"], detectors=detectors)
    labels = [a.value for a in Action]
    for spec in release["models"]:
        path = ROOT / spec["path"]
        before = digest(path)
        started = time.perf_counter()
        model = NecessityModel(path)
        if not model.available:
            raise RuntimeError(f"Cannot load {spec['id']}: {model.reason}")
        load_ms = (time.perf_counter() - started) * 1000
        raw, final, whole = [], [], []
        latencies, rewritten = [], 0
        for row in rows:
            text, quote = row["text"], row["quote"]
            start = text.index(quote)
            span = Span(start, start + len(quote), quote, row["category"], detector="diagnostic_gold")
            segments = segmentize(text, [span])
            attach_spans(segments, [span], text=text)
            host = next(seg for seg in segments if span in seg.spans)
            args = (row.get("task", "meeting_minutes"), row["recipient"], row.get("identity", "student_leader"))
            began = time.perf_counter()
            decision = decide_segment(host, *args, necessity_scorer=model.score, task_description=row["ask"])
            latencies.append((time.perf_counter() - began) * 1000)
            raw_action = max(decision.necessity_scores, key=decision.necessity_scores.get)
            raw.append(raw_action)
            final.append(decision.action.value)
            rewritten += raw_action != decision.action.value
            spans, runtime_segments = detected[row["id"]]
            matched = next((s for s in spans if s.category == row["category"] and
                            s.start < span.end and span.start < s.end), None)
            runtime = None
            if matched:
                runtime_host = next(seg for seg in runtime_segments if matched in seg.spans)
                runtime = decide_segment(runtime_host, *args, necessity_scorer=model.score, task_description=row["ask"])
            chain_action = runtime.action.value if runtime else "MISSED_ENTITY"
            whole.append(chain_action == row["expected"])
            output_text = ""
            if runtime and runtime.action != Action.PAUSE:
                # Transform only the matched runtime segment; no cloud generation.
                output_text = apply_decisions(runtime_host.text, [Segment(runtime_host.seg_id, runtime_host.text, 0, len(runtime_host.text),
                    [Span(s.start-runtime_host.start, s.end-runtime_host.start, s.text, s.category) for s in runtime_host.spans])],
                    [runtime], f"diagnostic-{spec['id']}-{row['id']}", MappingTable())["sanitized_text"]
            predictions.append({"model": spec["id"], "case_id": row["id"], "category": row["category"],
                                "expected": row["expected"], "gold_span_argmax": raw_action,
                                "gold_span_after_constraints": decision.action.value,
                                "detected_span_after_constraints": chain_action,
                                "quote_detected": matched is not None,
                                "synthetic_transformed_text": output_text})
        expected = [r["expected"] for r in rows]
        assert digest(path) == before, "Model weights changed during evaluation"
        summary.append({"id": spec["id"], "feature_version": model.metadata["feature_version"],
                        "sha256": before, "load_ms": round(load_ms, 2), "n": len(rows),
                        "raw_correct": sum(a == b for a, b in zip(raw, expected)),
                        "constrained_correct": sum(a == b for a, b in zip(final, expected)),
                        "macro_f1_six_actions": round(float(f1_score(expected, final, labels=labels, average="macro", zero_division=0)), 4),
                        "constraint_rewrites": rewritten, "detected_chain_correct": sum(whole),
                        "mean_decision_ms": round(sum(latencies) / len(latencies), 2)})
    write(output / "diagnostic_predictions.json", predictions)
    return {"dataset": corpus["dataset"], "sha256": digest(source), "provenance": corpus["provenance"],
            "training_performed": False, "models": summary,
            "target_detected": sum(any(p["case_id"] == row["id"] and p["quote_detected"] for p in predictions) for row in rows),
            "n": len(rows)}


def safeguard_checks(detectors):
    from llm_shield.schema import Action, Span, Segment
    from llm_shield.m3_decide.decision import decide_segment
    from llm_shield.m6_transform.anonymizer import apply_decisions
    from llm_shield.m6_transform.mapping import MappingTable
    from llm_shield.m7_egress.gateway import EgressGateway
    from llm_shield.m2_detect.pipeline import segmentize, attach_spans
    fixtures = [
        ("PHONE", "13900001234", "external_model", "RETAIN", "PAUSE"),
        ("PHONE", "13900001234", "external_model", "PSEUDONYMIZE", "PAUSE"),
        ("BUDGET", "7200元", "external_model", "GENERALIZE", "PAUSE"),
        ("PERSON_NAME", "沈予安", "egress_tool_public", "RETAIN", "PAUSE"),
        ("SENSITIVE_ATTR", "抑郁症", "external_model", "RETAIN", "PAUSE"),
        ("PERSON_NAME", "沈予安", "external_model", "PSEUDONYMIZE", "PSEUDONYMIZE"),
        ("PHONE", "13900001234", "external_model", "DELETE", "DELETE"),
    ]
    checks, transforms = [], []
    for cat, text, recipient, chosen, expected in fixtures:
        segment = Segment("guard", text, 0, len(text), [Span(0, len(text), text, cat)])
        decision = decide_segment(segment, "meeting_minutes", recipient, "student_leader", lambda *a, **k: {chosen: 1.0})
        checks.append({"category": cat, "chosen": chosen, "recipient": recipient,
                       "actual": decision.action.value, "expected": expected, "passed": decision.action.value == expected})
        if decision.action in {Action.DELETE, Action.PSEUDONYMIZE}:
            transformed = apply_decisions(text, [segment], [decision], "guard-"+cat, MappingTable())
            transforms.append({"action": chosen, "category": cat, "passed": text not in transformed["sanitized_text"]})
    gateways = []
    gateway = EgressGateway()
    for recipient, text, cat, expected in [
        ("external_model", "电话13900001234", "PHONE", False),
        ("viewer_peer", "电话13900001234", "PHONE", False),
        ("egress_tool_public", "电话13900001234", "PHONE", False),
        ("external_model", "预算7200元", "BUDGET", False),
        ("external_model", "校园讲座将于周六举行。", None, True),
    ]:
        spans = [] if cat is None else [Span(2, len(text), text[2:], cat)]
        actual = gateway.precheck(recipient, "student_leader", text, spans, set(), task_key="meeting_minutes")["allowed"]
        gateways.append({"recipient": recipient, "category": cat, "expected_allowed": expected,
                         "actual_allowed": actual, "passed": actual == expected})
    def pack(items):
        return {"passed": sum(item["passed"] for item in items), "total": len(items), "checks": items}
    return {"constraints": pack(checks), "transformation": pack(transforms), "boundaries": pack(gateways),
            "scope": "Synthetic canary checks; does not prove zero leakage on arbitrary inputs."}


def transformation_and_utility_checks():
    from llm_shield.schema import Action, Span, Decision
    from llm_shield.m2_detect.pipeline import segmentize, attach_spans
    from llm_shield.m6_transform.anonymizer import apply_decisions
    from llm_shield.m6_transform.mapping import MappingTable
    from llm_shield.m5_utility.estimator import estimate
    checks = []
    for action in Action:
        if action == Action.GENERALIZE:
            text, values, cat = "印刷费为6400元。", ["6400元"], "BUDGET"
        elif action == Action.LOCAL_AGGREGATE:
            text, values, cat = "沈予安参加。宋知白参加。", ["沈予安", "宋知白"], "PERSON_NAME"
        else:
            text, values, cat = "沈予安负责整理器材。", ["沈予安"], "PERSON_NAME"
        spans = [Span(text.index(value), text.index(value)+len(value), value, cat) for value in values]
        segments = segmentize(text, spans)
        attach_spans(segments, spans, text=text)
        decisions = [Decision(seg.seg_id, action, [cat]) for seg in segments]
        result = apply_decisions(text, segments, decisions, "transform-"+action.value, MappingTable())
        if action == Action.RETAIN:
            passed = result["sanitized_text"] == text
        elif action == Action.PAUSE:
            passed = result["paused"] and not result["sanitized_text"]
        elif action == Action.LOCAL_AGGREGATE:
            passed = result["aggregates"].get("person_count") == 2 and all(value not in result["sanitized_text"] for value in values)
        else:
            passed = all(value not in result["sanitized_text"] for value in values)
            if action == Action.PSEUDONYMIZE:
                passed = passed and bool(result["mapping"])
            if action == Action.GENERALIZE:
                passed = passed and bool(result["sanitized_text"])
        checks.append({"action": action.value, "passed": bool(passed)})
    utility = []
    fixtures = [
        ("meeting_minutes", "人员甲负责整理器材，周五前提交。", True),
        ("meeting_minutes", "人员甲负责整理器材。", False),
        ("activity_stats", "校园讲座共0人参加。", True),
        ("project_intro", "校园读书项目面向全体同学开放，包含公开讲座和书籍交流活动，所有具体安排以正式通知为准。", True),
        ("project_intro", "介绍", False),
        ("unknown_task", "本任务没有检查规则。", None),
    ]
    for task, text, expected in fixtures:
        result = estimate(text, task)
        actual = result["completeness"] == 1 if result["evaluated"] else None
        utility.append({"task": task, "expected_complete": expected, "actual_complete": actual, "passed": actual == expected})
    def pack(items):
        return {"passed": sum(item["passed"] for item in items), "total": len(items), "checks": items}
    return {"transformation": pack(checks), "utility": pack(utility)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gliner-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Use a new output directory to preserve earlier evidence")
    os.environ.update(LLM_MODE="mock", SHIELD_USE_GLINER="true", HF_HUB_OFFLINE="1",
                      TRANSFORMERS_OFFLINE="1", SHIELD_GLINER_MODEL_DIR=str(args.gliner_dir.resolve()))
    import torch
    torch.set_num_threads(4)
    from llm_shield.m2_detect.gliner_ner import GLiNERDetector
    from llm_shield.m2_detect.regex_rules import RegexDetector
    from llm_shield.m2_detect.entity_rules import EntityDetector
    from llm_shield.m2_detect import pipeline as detection
    started = time.perf_counter()
    model = GLiNERDetector(str(args.gliner_dir.resolve()))
    if not model.available:
        raise RuntimeError(model.reason)
    load_ms = (time.perf_counter() - started) * 1000
    # Reuse the explicitly selected official profile for boundary rescans, without changing .env.
    detection._gliner_singleton = model
    model.detect("本轮验证只使用合成及既有公开测试材料。")
    args.out.mkdir(parents=True)
    diagnostics = APP / "data/stage_diagnostics_20261102/cases.json"
    input_sha = digest(diagnostics)
    environment = {"gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                   "device": model.device, "gliner_load_ms": round(load_ms, 2),
                   "packages": {name: importlib.metadata.version(name) for name in ("torch", "gliner", "transformers", "scikit-learn", "joblib")},
                   "official_weight_sha256": digest(args.gliner_dir / "model.safetensors")}
    write(args.out / "protocol.json", {"diagnostics_sha256_before": input_sha, "training_performed": False,
          "threshold": model.threshold, "cloud_api_called": False, "environment": environment})
    parser_result = parser_checks()
    ner = ner_evaluation(model)
    policy = policy_evaluation([RegexDetector(), EntityDetector(detect_org_location=False), model], args.out)
    guards = safeguard_checks(None)
    guards.update(transformation_and_utility_checks())
    assert digest(diagnostics) == input_sha
    historical = json.loads((APP / "eval/releases/campus_blind31_20261102/confusion.json").read_text(encoding="utf-8"))
    historical_summary = [{"id": name, "n": result["pipeline"]["n"],
                           "correct": result["pipeline"]["correct"],
                           "macro_f1": result["pipeline"]["macro_f1_six_actions"]}
                          for name, result in historical["models"].items()]
    report = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
              "profile": "official_gliner_multi_v2.1_baseline_not_original_finetune",
              "cloud_api_called": False, "default_models_promoted": False,
              "environment": environment, "parsing": parser_result, "ner": ner,
              "necessity": policy, "safeguards": guards,
              "historical_human31": {"rerun": False, "source": "eval/releases/campus_blind31_20261102",
                                     "models": historical_summary},
              "limitations": ["官方GLiNER不等于缺失的项目微调权重。", "field_v1是已使用的开发基准。",
                              "24条新诊断由AI编写，不能当作独立人工准确率。", "历史31条人工评测未重新执行。",
                              "未测试真实云端生成；未自动晋级必要性候选。"]}
    write(args.out / "summary.json", report)
    print(json.dumps({"parsing": parser_result, "policy": policy, "guards": guards}, ensure_ascii=False), flush=True)
    print("Report saved to " + str(args.out / "summary.json"), flush=True)


if __name__ == "__main__":
    main()
