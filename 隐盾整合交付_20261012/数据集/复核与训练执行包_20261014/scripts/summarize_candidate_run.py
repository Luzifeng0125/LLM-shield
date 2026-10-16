"""Collect existing experiment evidence; does not train or evaluate any dataset."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def read(path):
    return path.read_text(encoding="utf-8-sig")


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def summarize(run, app):
    load = lambda name: json.loads(read(run / name))
    baseline = load("run_summary.json")
    neural = load("ner_bert_v1/validation_metrics.json")
    application = load("ner_app_integration_final/summary.json")
    policy = load("policy_context_v2/metrics.json")
    service = load("candidate_service_verification.json")
    artifact_checks = {}
    for folder, manifest_name, key in (
            ("ner_bert_v1", "artifact_manifest.json", "artifact_files_sha256"),
            ("policy_context_v2", "manifest.json", "files")):
        manifest = load(folder + "/" + manifest_name)
        checks = {name: (run / folder / name).is_file() and digest(run / folder / name) == value
                  for name, value in manifest[key].items()}
        assert checks and all(checks.values()), f"Artifact integrity failed: {folder}"
        artifact_checks[folder] = {"files_verified": len(checks), "all_passed": True}
    tests = []
    for filename in ("regression_tests.xml", "adapter_final_tests.xml"):
        suites = ET.fromstring(read(run / filename)).findall("testsuite")
        record = {key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
                  for key in ("tests", "failures", "errors", "skipped")}
        assert record["tests"] and not record["failures"] and not record["errors"]
        tests.append({"report": filename, **record})
    smoke = read(run / "candidate_smoke.log")
    assert "通过 38 项，失败 0 项" in smoke
    current_model_hash = digest(app / "models" / "necessity_action.joblib")
    assert current_model_hash == baseline["live_model_sha256"]
    assert service["status"] == "passed" and service["external_model_calls"] == 0
    report = {
        "status": "trained_and_local_ner_candidate_verified_not_production_deployed",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_report": "run_summary.json",
        "ner": {"validation_units": 56,
                "rules_baseline": baseline["ner_current_rule_context_baseline"]["micro"],
                "bert_model": neural["micro"],
                "application_combined": application["scores"]["application_combined"]["micro"],
                "application_report": "ner_app_integration_final/summary.json"},
        "policy_context_v2": {key: policy[key] for key in (
            "samples", "preferred_accuracy", "preferred_macro_f1", "pause_false_allow_suggestion",
            "nonpause_false_pause_suggestion", "dialogue_all_preferred_actions_correct")},
        "artifact_integrity": artifact_checks, "regression_checks": tests,
        "candidate_smoke": {"passed": 38, "failed": 0, "report": "candidate_smoke.log"},
        "service_verification": {"status": service["status"], "external_model_calls": 0,
                                 "report": "candidate_service_verification.json"},
        "environment_lock": "training_environment_lock.txt",
        "live_action_model_unchanged": True, "live_action_model_sha256": current_model_hash,
        "test_used_for_training_or_scoring": False,
        "test_access_note": baseline["test_access_note"],
        "launch": str(app.parent / "启动人工gold候选版.cmd"),
        "limitations": [
            "Human-reviewed synthetic development validation, not sealed test or real-world safety.",
            "Three combined NER boundary errors remain in ORG/LOCATION.",
            "Request-level policy v2 is not yet integrated with the application's segment decisions.",
            "A mixed request exposed an inapplicable action in the unchanged segment model; it safely paused.",
            "Candidate launcher uses local mock replies. No real provider egress was tested.",
            "Application ID-span guard was added after training; training and current application hashes are separately preserved.",
        ],
    }
    (run / "improvement_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "artifact_integrity": artifact_checks,
                      "out": str(run / "improvement_summary.json")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--app", type=Path, required=True)
    args = parser.parse_args()
    summarize(args.run.resolve(), args.app.resolve())
