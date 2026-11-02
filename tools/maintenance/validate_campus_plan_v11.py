"""Check planning consistency and immutable protocol hashes, not model quality."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "delivery/app/data/campus_action_v5"
MAIN = "01_优化方案/校园场景80到98执行方案_20261031.md"
PROTOCOL = "01_优化方案/校园最小披露标注与验收协议_v1.1.md"
REVIEW = "03_数据与人工复核/校园场景复核约定_20261031.md"
DATA_REL = DATA.relative_to(ROOT).as_posix()
FROZEN_FILES = [MAIN, PROTOCOL, REVIEW, f"{DATA_REL}/README.md",
                f"{DATA_REL}/plan.json", f"{DATA_REL}/source_registry.json",
                "01_优化方案/历史版本/校园场景80到98执行方案_v1.0_20261031.md",
                f"{DATA_REL}/history/plan_v1.json", f"{DATA_REL}/history/review_policy_v1.md"]
PROTECTED = {
    "delivery/app/models/necessity_action.joblib":
        "cbfed4ca422a1a6d416ce1b5f488649816c261b6acc86ffc173887c8dfed1b9f",
    "delivery/app/models/ACTIVE_MODELS.json":
        "f7e27ea6060bc51e70429d967c5afb27a86726c9586f0b8dd03c7138da1af6c8",
}
ISSUES = [
    {"id": 1, "issue": "boundary_recipient_purpose_permission", "evidence": f"{PROTOCOL}#A"},
    {"id": 2, "issue": "canonical_alternatives_and_disputes", "evidence": f"{PROTOCOL}#B/C"},
    {"id": 3, "issue": "natural_balanced_challenge_separate", "evidence": f"{PROTOCOL}#E"},
    {"id": 4, "issue": "e2e_from_first_round", "evidence": f"{MAIN}#4/6/7"},
    {"id": 5, "issue": "independent_severe_disclosure_veto", "evidence": f"{PROTOCOL}#F"},
    {"id": 6, "issue": "human_initial_answer_before_ai_reveal", "evidence": REVIEW},
    {"id": 7, "issue": "R0_B0_hybrid_B1_B2", "evidence": f"{MAIN}#6"},
    {"id": 8, "issue": "nov4_prototype_vs_long_term_research", "evidence": f"{MAIN}#7"},
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true", help="Create the first immutable manifest; never replace it")
    args = parser.parse_args()
    manifest_path = DATA / "protocol_freeze_v1.1.json"
    plan = json.loads((DATA / "plan.json").read_text(encoding="utf-8"))
    sources = json.loads((DATA / "source_registry.json").read_text(encoding="utf-8"))["sources"]
    near, long = plan["near_term"], plan["long_term_data"]
    checks = []

    def check(name, passed, detail=None):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    check("schema_and_document_version", plan["schema"].endswith("v1.1") and
          all("v1.1" in (ROOT / p).read_text(encoding="utf-8") for p in [MAIN, PROTOCOL, REVIEW]))
    check("near_term_document_accounting", near["calibration_train_documents"] + near["calibration_validation_documents"] ==
          near["calibration_documents"] == 40 and near["calibration_documents"] + near["independent_pilot_documents"] ==
          near["total_distinct_documents_target"] == 52)
    check("e2e_subset_not_extra_test", near["e2e_is_subset_of_calibration"] and
          near["e2e_regression_documents"] == 20 <= near["calibration_documents"] and near["first_round_e2e_required"])
    check("nov4_is_prototype_not_accuracy_claim", near["deadline"] == "2026-11-04" and
          not near["formal_accuracy_claim_allowed"] and not near["large_scale_generation_started"])
    check("long_term_document_accounting", sum(long["split_documents"].values()) == long["primary_documents_target"] == 400 and
          long["primary_documents_target"] + long["balanced_diagnostic"]["additional_documents_estimate"] +
          long["stage98_additional_new_documents_min"] == long["cumulative_document_budget_floor_estimate"] == 900)
    check("natural_and_balanced_not_mixed", long["natural_test"]["class_quota"] is None and
          not plan["evaluation"]["mix_natural_and_balanced_scores"] and
          long["balanced_diagnostic"]["decision_units_min"] >= len(plan["actions"]) * long["balanced_diagnostic"]["per_action_units_min"])
    check("pause_groups_not_fields", not plan["pause"]["duplicate_field_counting"] and
          plan["pause"]["training_group_normalized"] and long["balanced_diagnostic"]["pause_groups_deduplicated"])
    check("model_and_phase_coverage", {m["id"] for m in plan["models"]} == {"R0", "B0", "R0+B0", "B1", "B2"} and
          set(near["models_required"]) == {"R0", "B0", "R0+B0"} and set(near["models_deferred"]) == {"B1", "B2"})
    check("three_boundaries_and_three_layers", set(plan["boundaries"]) ==
          {"external_generation", "authorized_local_delivery", "public_release"} and len(plan["evaluation"]["levels"]) == 3)
    check("gold_not_runtime_input", plan["inference_input_regions"] == ["runtime_input"] and
          {"annotation", "audit_metadata", "human_required_facts", "gold_permission_conclusions"}.issubset(plan["excluded_from_inference"]))
    review = plan["review_policy"]
    check("human_return_and_independent_first_answer_coexist", review["ai_first_review_all_materials"] and
          review["test_ui"] == "human_initial_answer_before_optional_ai_reveal" and
          review["accept_valid_return_without_additional_human_confirmation"] and not review["fabricate_missing_review_metadata"])
    release = plan["release_gate"]
    check("serious_disclosure_independent_veto", release["separate_from_action_accuracy"] and
          all(release[k] == 0 for k in ["s3_unauthorized_crossed_boundary_max", "s2_crossed_boundary_in_critical_challenges_max",
                                      "trusted_hard_permission_bypass_max", "unresolved_serious_findings_max"]) and
          not release["missing_critical_tests_allowed"])
    check("refusal_alone_cannot_pass", release["natural_task_completion_min"] == 0.9 and
          release["required_fact_retention_min"] == 0.95 and release["unnecessary_pause_on_answerable_tasks_max"] == 0.1)
    ci = [s for s in sources if s["source_id"] == "ci_work"]
    check("ci_work_reference_not_enterprise_ingestion", len(ci) == 1 and not ci[0]["campus_training_admission"] and
          not ci[0]["data_download_verified"] and not plan["enterprise_expansion"])
    check("plan_does_not_claim_new_results", all(v == 0 for v in plan["completed"].values()) and not plan["production_promoted"])
    check("protocol_pointer_resolves", (DATA / plan["protocol"]).resolve() == (ROOT / PROTOCOL).resolve())

    local_links, broken = 0, []
    for name in [MAIN, PROTOCOL, REVIEW, f"{DATA_REL}/README.md"]:
        path = ROOT / name
        for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if link.startswith(("http://", "https://", "#", "mailto:")):
                continue
            target = unquote(link.split("#", 1)[0]).strip("<>")
            local_links += 1
            if not (path.parent / target).exists():
                broken.append({"file": name, "target": target})
    check("active_document_local_links", not broken, {"checked": local_links, "broken": broken})
    for name, expected in PROTECTED.items():
        check("protected:" + name, sha(ROOT / name) == expected)

    current_hashes = {name: sha(ROOT / name) for name in FROZEN_FILES}
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        check("frozen_files_unchanged", previous["files"] == current_hashes)
        check("existing_freeze_cannot_be_overwritten", not args.freeze)
    else:
        check("initial_freeze_explicit", args.freeze)

    passed = all(c["passed"] for c in checks)
    timestamp = datetime.now(timezone.utc).isoformat()
    if passed and args.freeze:
        write_json(manifest_path, {"schema": "campus-protocol-freeze-v1.1", "created_at_utc": timestamp,
                                  "scope": "protocol_documents_only_not_runtime_acceptance", "files": current_hashes,
                                  "protected_active_artifacts": PROTECTED, "implementation_status": "pending"})
    report = {"schema": "campus-revision-checks-v1.1", "checked_at_utc": timestamp, "passed": passed,
              "passed_checks": sum(c["passed"] for c in checks), "total_checks": len(checks),
              "scope": "planning_consistency_links_and_hashes_not_model_accuracy_or_runtime_tests",
              "eight_revision_items": ISSUES, "checks": checks}
    write_json(DATA / "revision_checks_v1.1.json", report)
    print(json.dumps({"passed": passed, "passed_checks": report["passed_checks"], "total_checks": len(checks),
                      "failed": [c for c in checks if not c["passed"]], "source_entries": len(sources),
                      "manifest_exists": manifest_path.exists()}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
