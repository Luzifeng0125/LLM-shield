import copy

import pytest

from llm_shield.m3_decide.decision import decide_segment
from llm_shield.m4_necessity.model import NecessityModel
from llm_shield.m4_necessity.research import (
    annotation_for, calibrate, case_hash, training_sample, validate_cases, segment_for,
)
from llm_shield.schema import Action
from scripts.build_action_review import build_legacy_cases as build_cases
from scripts.merge_action_reviews import merge_reviews


def test_synthetic_pack_has_source_and_template_isolation_and_no_human_claim():
    cases = build_cases()
    manifest = validate_cases(cases)
    assert manifest["cases"] == 336 and manifest["sources"] == 96
    assert manifest["splits"] == {"train": 224, "validation": 56, "test": 56}
    assert {c["review"]["status"] for c in cases} == {"machine_draft"}
    with pytest.raises(ValueError, match="人工复核"):
        annotation_for(cases[0], allow_drafts=False)


def test_rephrased_source_or_template_cannot_cross_partitions():
    cases = build_cases()
    cases[-1]["template_group"] = cases[0]["template_group"]
    with pytest.raises(ValueError, match="跨拆分"):
        validate_cases(cases)


def test_context_pairs_keep_task_and_text_fixed_but_change_necessity():
    cases = {c["case_id"]: c for c in build_cases()}
    a, b = cases["f00-person-2-0"], cases["f00-person-2-1"]
    assert a["text"] == b["text"] and a["task_description"] == b["task_description"]
    assert a["context"] != b["context"]
    assert a["proposal"]["action"] != b["proposal"]["action"]


def test_explicit_training_refuses_template_overlap(tmp_path):
    cases = build_cases()
    train = [training_sample(c, allow_drafts=True) for c in cases[:112]]
    validation = [copy.deepcopy(train[0])]
    result = NecessityModel(tmp_path / "candidate.joblib").train(train, validation_samples=validation)
    assert not result["ok"] and "重叠" in result["reason"]
    assert not (tmp_path / "candidate.joblib").exists()


def test_confidence_policy_abstains_without_changing_to_second_action():
    case = build_cases()[1]
    decision = decide_segment(segment_for(case), case["task"], case["recipient"], case["identity"],
        lambda *a, **k: {"PSEUDONYMIZE": .51, "DELETE": .49},
        confidence_policy={"min_probability": .6, "min_margin": .1})
    assert decision.action == Action.PAUSE


@pytest.mark.parametrize("policy", [{}, {"min_probability": float("nan"), "min_margin": 0},
                                    {"min_probability": True, "min_margin": 0}])
def test_corrupt_confidence_policy_fails_closed(policy):
    case = build_cases()[1]
    decision = decide_segment(segment_for(case), case["task"], case["recipient"], case["identity"],
        lambda *a, **k: {"PSEUDONYMIZE": 1.0}, confidence_policy=policy)
    assert decision.action == Action.PAUSE


def test_calibration_reports_when_error_target_cannot_be_supported():
    result = calibrate({"rows": [{"predicted": "RETAIN", "acceptable": False,
                                  "probability": .99, "margin": .9}]})
    assert result is None


def response(cases, role, reviewer):
    # Simulated test fixture, never a real human review or a training artifact.
    return {"schema": "action-review-response-v1", "role": role, "reviewer": reviewer,
            "reviews": [{"case_id": c["case_id"], "case_sha256": case_hash(c),
                         "annotation": copy.deepcopy(c["proposal"])} for c in cases]}


def test_partial_reviews_do_not_promote_missing_cases_or_fake_consensus():
    cases = build_cases()
    a, b = response(cases[:2], "A", "test-reviewer-A"), response(cases[:2], "B", "test-reviewer-B")
    b["reviews"][0]["annotation"]["action"] = "PAUSE"
    b["reviews"][0]["annotation"]["allowed_actions"] = ["PAUSE"]
    b["reviews"][0]["annotation"]["minimum_representation"] = "uncertain"
    merged, status = merge_reviews(cases, a, b)
    assert status["reviewed"] == 1 and len(status["disagreements"]) == 1
    assert len(status["pending"]) == len(cases) - 2
    assert merged[0]["review"]["status"] != "human_reviewed"
    assert merged[1]["review"]["status"] == "human_reviewed"
    assert "annotation" not in merged[2]


def test_same_reviewer_and_changed_source_are_rejected():
    cases = build_cases()
    a = response(cases[:1], "A", "test-same-person")
    b = response(cases[:1], "B", "test-same-person")
    with pytest.raises(ValueError, match="不同"):
        merge_reviews(cases, a, b)
    b["reviewer"] = "test-other-person"
    b["reviews"][0]["case_sha256"] = "outdated"
    with pytest.raises(ValueError, match="哈希"):
        merge_reviews(cases, a, b)
