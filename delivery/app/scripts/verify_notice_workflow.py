"""Verify local-only roster review and roster-free notice drafting over loopback."""
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
    parser.add_argument("--activity-name", required=True)
    parser.add_argument("--port", type=int, default=8789)
    args = parser.parse_args()
    local = (APP / "outputs").resolve()
    if args.out.exists() or not all(path.resolve().is_relative_to(local) for path in (args.input, args.out)):
        raise ValueError("Use an ignored private input and a new ignored report directory")
    if not 1024 <= args.port <= 65535:
        raise ValueError("Invalid local port")
    base = f"http://127.0.0.1:{args.port}"
    with urlopen(base + "/api/config", timeout=20) as response:
        config = json.load(response)
    if config["models"]["llm"]["mode"] != "mock":
        raise RuntimeError("Verification requires a mock service")
    source = json.loads(args.input.read_text(encoding="utf-8-sig"))

    def post(path, body):
        request = Request(base + path, data=json.dumps(body).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=60) as response:
            return json.load(response)

    review = post("/api/notice/review", {"text": source["text"], "identity": "student_leader"})
    expected = expected_spans(source)
    predicted = [{key: span[key] for key in ("start", "end", "category")} for span in review["spans"]]
    metrics = detection_metrics(expected, predicted)
    body = {"identity": "student_leader", "activity_name": args.activity_name,
            "items": ["check_in", "join_group", "verify_contact"]}
    draft = post("/api/notice/draft", body)
    residuals = {field: sum(source["text"][item["start"]:item["end"]] in draft[field] for item in expected)
                 for field in ("original_text", "sanitized_text", "model_output", "display_text", "egress_text")}
    passed = (review["local_only"] and not review["external_model_called"]
              and metrics["strict_tp"] == len(expected) and metrics["strict_fp"] == 0
              and draft["ok"] and not draft["paused"] and bool(draft["display_text"])
              and not any(residuals.values()) and len(draft["boundaries"]) == 3
              and all(not boundary["blocked"] for boundary in draft["boundaries"])
              and "模拟" in draft["display_text"])
    report = {"status": "passed" if passed else "failed", "llm_mode": "mock",
              "external_model_called": False, "local_review_detection": metrics,
              "generation_request_keys": sorted(body), "residual_direct_fields": residuals,
              "draft_ok": draft["ok"], "draft_paused": draft["paused"],
              "draft_actions": [item["action"] for item in draft["decisions"]],
              "boundary_status": [{key: item.get(key) for key in ("boundary", "allowed", "blocked", "leaked_categories")}
                                  for item in draft["boundaries"]]}
    args.out.mkdir(parents=True)
    (args.out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if not passed:
        raise RuntimeError("Notice verification failed; raw values and boundary text were not printed")
    (args.out / "notice_draft.txt").write_text(draft["display_text"] + "\n", encoding="utf-8")
    (args.out / "public_brief.txt").write_text(draft["sanitized_text"] + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
