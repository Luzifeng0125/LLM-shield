"""Check a private example over loopback; persist only counts and masked boundaries."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

from replay_local_example import APP, detection_metrics, expected_spans


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    local = (APP / "outputs").resolve()
    if args.out.exists() or not all(path.resolve().is_relative_to(local) for path in (args.input, args.out)):
        raise ValueError("Use private local inputs and a new ignored report path")
    if not 1024 <= args.port <= 65535:
        raise ValueError("Invalid local port")
    base = f"http://127.0.0.1:{args.port}"
    with urlopen(base + "/api/config", timeout=20) as response:
        config = json.load(response)
    if config["models"]["llm"]["mode"] != "mock":
        raise RuntimeError("Refusing to submit private example unless service is in mock mode")
    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    body = {"session_id": "private-local-roster-http", "identity": "student_leader", "task": "activity_stats",
            "recipient": "external_model", "custom_text": source["text"], "send_model": True,
            "task_description": "核对活动签到、排班、群组通知和紧急联络信息"}
    request = Request(base + "/api/run", data=json.dumps(body).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=30) as response:
        status, result = response.status, json.load(response)
    text = result["original_text"]
    expected = expected_spans({**source, "text": text})
    predicted = [{key: span[key] for key in ("start", "end", "category")} for span in result["spans"]]
    metrics = detection_metrics(expected, predicted)
    def masked(item):
        return "".join("*" if any(entity["start"] <= index < entity["end"] for entity in expected)
                       else text[index] for index in range(item["start"], item["end"]))
    residuals = {field: sum(text[item["start"]:item["end"]] in result[field] for item in expected)
                 for field in ("sanitized_text", "model_output", "egress_text")}
    passed = (result["ok"] and not result["paused"] and metrics["fully_covered"] == len(expected)
              and not any(residuals.values()) and "模拟" in result["model_output"]
              and all(not boundary["blocked"] for boundary in result["boundaries"]))
    report = {"status": "passed" if passed else "failed", "http_status": status, "llm_mode": "mock",
              "scope": "Coverage and no direct-field residue; exact NER boundaries reported separately",
              "detection": metrics, "residual_direct_fields": residuals,
              "actions": [decision["action"] for decision in result["decisions"]],
              "boundaries": result["boundaries"],
              "masked_boundary_errors": [{**item, "masked_text": masked(item)}
                                         for item in metrics["extra_or_wrong_boundary"]]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "strict_tp": metrics["strict_tp"],
                      "fully_covered": metrics["fully_covered"], "expected": len(expected),
                      "residual_direct_fields": residuals, "masked_boundary_errors": report["masked_boundary_errors"]},
                     ensure_ascii=False))
    if not passed:
        raise RuntimeError("Local verification failed; raw values were not printed")


if __name__ == "__main__":
    main()
