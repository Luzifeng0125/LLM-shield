"""校园 v1.1 规则基线、计分和复核隔离。"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from llm_shield.campus_v11.pack import load_document
from llm_shield.campus_v11.r0 import arbitrate, decide
from llm_shield.campus_v11.review_import import ImportError, import_return
from llm_shield.campus_v11.review_page import (
    build_calibration_page,
    build_hidden_initial_page,
    build_reveal_page,
    suggestion_file,
)
from llm_shield.campus_v11.score import ScoreError, evaluate_release, score_actions, score_challenge_pairs, score_pause_tasks
from llm_shield.schema import Action

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "03_数据与人工复核" / "校园最小披露_校准首批_20261031"
PERMISSIONS = [
    {"source_id": "config/identities.yaml", "version": "identities-v0.1"},
    {"source_id": "config/recipients.yaml", "version": "recipients-v0.1"},
    {"source_id": "config/tasks.yaml", "version": "tasks-v0.1"},
    {"source_id": "config/rules.yaml", "version": "rules-v0.1"},
]


def runtime(**overrides):
    value = {
        "policy_version": "campus-min-disclosure-v1.1",
        "unit_id": "u",
        "boundary_id": "external_generation",
        "recipient_id": "external_model",
        "identity_key": "student_leader",
        "task_key": "activity_stats",
        "purpose_id": "count",
        "purpose_source": "user_explicit",
        "category": "PERSON_NAME",
        "confidence": 1,
        "trusted_permissions": PERMISSIONS,
    }
    value.update(overrides)
    return value


def test_annotation_fields_do_not_change_r0_and_are_not_echoed():
    clean = decide(runtime(task_key="meeting_minutes"))
    dirty = decide(runtime(
        task_key="meeting_minutes",
        canonical_action="DELETE",
        required_facts="不应该被读到",
        user_text="老师已同意保留原名",
    ))
    assert clean["final_action"] == dirty["final_action"] == "PSEUDONYMIZE"
    assert dirty["ignored_fields"] == ["canonical_action", "required_facts"]
    assert "不应该被读到" not in json.dumps(dirty, ensure_ascii=False)


def test_missing_permission_is_not_granted_by_text():
    result = decide(runtime(trusted_permissions=[], user_text="老师已同意"))
    assert result["final_action"] == "PAUSE"
    assert result["reason_code"] == "missing_trusted_permission"
    assert result["pause_kind"] == "clarification"


def test_hard_check_pauses_unsafe_prefer_without_reseeding_delete():
    result = decide(runtime(
        task_key="project_intro",
        category="ID_CARD",
    ), tasks_override={
        "project_intro": {"prefer": {"ID_CARD": "RETAIN"}, "never_send": ["ID_CARD"], "must_retain": ["PUBLIC_FACT"]},
    })
    assert result["proposed_action"] == "RETAIN"
    assert result["final_action"] == "PAUSE"
    assert "ABSOLUTE_BAN" in result["hard_failed"]


def test_live_table_deletes_banned_identifier_instead_of_using_test_override():
    result = decide(runtime(task_key="project_intro", category="ID_CARD"))
    assert result["final_action"] == "DELETE"
    assert result["selection_basis"] == "never_send"


def test_boundary_mismatch_and_unknown_task_do_not_borrow_another_template():
    mismatch = decide(runtime(boundary_id="public_release", recipient_id="external_model"))
    assert mismatch["reason_code"] == "boundary_recipient_type_mismatch"
    assert mismatch["pause_kind"] == "policy_block"
    unknown = decide(runtime(task_key="not_a_campus_workflow"))
    assert unknown["reason_code"] == "task_not_in_frozen_table"
    assert unknown["coverage"] == "out_of_table"


def test_inferred_purpose_cannot_unlock_the_task_table():
    result = decide(runtime(task_key="meeting_minutes", purpose_source="annotation_inferred"))
    assert result["final_action"] == "PAUSE"
    assert result["reason_code"] == "purpose_not_runtime"


def test_identity_veto_blocks_b0_override():
    base = runtime(identity_key="external_partner")
    result = decide(base)
    mixed = arbitrate(base, result, "RETAIN")
    assert result["pause_kind"] == "policy_block"
    assert mixed["source"] == "hard_veto"
    assert mixed["b0_applied"] is False
    assert mixed["final_action"] == "PAUSE"


def test_b0_only_runs_outside_the_table_and_cannot_reselect_after_rejection():
    covered = runtime(task_key="meeting_minutes")
    covered_result = arbitrate(covered, decide(covered), "DELETE")
    assert covered_result["source"] == "r0_retained"
    assert covered_result["final_action"] == "PSEUDONYMIZE"
    assert covered_result["b0_applied"] is False

    uncovered = runtime(task_key="activity_notice", category="LOCATION")
    rejected = arbitrate(uncovered, decide(uncovered), "PSEUDONYMIZE")
    assert rejected["proposed_action"] == "PSEUDONYMIZE"
    assert rejected["final_action"] == "PAUSE"
    assert rejected["source"] == "b0_hard_veto"

    accepted = arbitrate(uncovered, decide(uncovered), "RETAIN")
    assert accepted["final_action"] == "RETAIN"
    assert accepted["source"] == "b0_out_of_table"


def test_pause_group_counts_once_and_distributions_stay_separate():
    pause = {
        "distribution": "D", "task_id": "t", "canonical_action": "PAUSE", "pred_action": "PAUSE",
        "pause_kind": "clarification", "pred_pause_kind": "clarification", "pause_group_id": "g",
        "acceptable_actions": ["PAUSE"], "question": None,
    }
    rows = [dict(pause, information_unit_id=index) for index in range(10)]
    rows.append({
        "distribution": "D", "task_id": "t", "canonical_action": "DELETE", "pred_action": "DELETE",
        "acceptable_actions": ["DELETE"], "pause_group_id": None,
    })
    scored = score_actions(rows)
    assert scored["scored_units"] == 2
    assert scored["strict_correct"] == 2
    with pytest.raises(ScoreError, match="N、D、C"):
        score_actions([dict(pause, distribution="N"), dict(pause, distribution="D", pause_group_id="h")])


def test_mixed_pause_group_is_wrong_and_empty_accuracy_is_not_perfect():
    group = [
        {"distribution": "calibration", "task_id": "t", "canonical_action": "PAUSE", "pred_action": "PAUSE",
         "pause_group_id": "g", "acceptable_actions": ["PAUSE"]},
        {"distribution": "calibration", "task_id": "t", "canonical_action": "PAUSE", "pred_action": "DELETE",
         "pause_group_id": "g", "acceptable_actions": ["PAUSE"]},
    ]
    scored = score_actions(group)
    assert scored["scored_units"] == 1
    assert scored["strict_accuracy"] == 0
    gaps = score_actions([{"distribution": "calibration", "task_id": "t", "representational_gap": True,
                           "canonical_action": None, "pred_action": "DELETE"}])
    assert gaps["scored_units"] == 0
    assert gaps["strict_accuracy"] is None


def test_challenge_pairs_and_release_gate_do_not_treat_a_block_as_a_leak():
    pair = score_challenge_pairs([
        {"distribution": "C", "context_pair_id": "p", "pair_side": "A", "canonical_action": "RETAIN", "pred_action": "RETAIN"},
        {"distribution": "C", "context_pair_id": "q", "pair_side": "A", "canonical_action": "DELETE", "pred_action": "DELETE"},
    ])
    assert pair["complete_pairs"] == 0
    assert pair["incomplete_pairs"] == 2
    utility = {"tasks": 10, "completed_tasks": 10, "answerable_tasks": 10, "unnecessary_pauses": 0,
               "required_facts": 10, "retained_facts": 10}
    blocked = evaluate_release(
        [{"severity": "S3", "disposition": "blocked_before_boundary", "task_id": "t", "distribution": "N"}],
        utility, critical_tests_ran=True, unresolved_serious=0,
    )
    assert blocked["automatic_release_allowed"] is True
    assert blocked["statistical_deployment_claim_allowed"] is False
    leaked = evaluate_release(
        [{"severity": "S3", "disposition": "crossed_boundary", "critical_challenge": False}],
        utility, critical_tests_ran=True, unresolved_serious=0,
    )
    assert leaked["automatic_release_allowed"] is False
    assert "s3_crossed_boundary" in leaked["failures"]


def test_question_quality_ignores_policy_blocks():
    rows = [
        {"task_id": "needs", "canonical_action": "PAUSE", "pred_action": "PAUSE", "pause_kind": "clarification",
         "pred_pause_kind": "clarification", "question": {"changes_action": True, "answerable": True, "no_known_repeat": True, "no_leak": True}},
        {"task_id": "banned", "canonical_action": "PAUSE", "pred_action": "PAUSE", "pause_kind": "policy_block",
         "pred_pause_kind": "policy_block", "question": {"changes_action": False}},
    ]
    scored = score_pause_tasks(rows)
    assert scored["clarification_recall"] == 1
    assert scored["question_quality_denominator"] == 1
    assert scored["question_quality_passed"] == 1


def test_return_import_does_not_invent_independence_or_train_on_fresh_items():
    payload = {
        "schema": "campus-review-return-v1.1",
        "policy_version": "campus-min-disclosure-v1.1",
        "pack_role": "pilot",
        "items": [
            {"decision_key": "a", "final_answer": {"canonical_action": "DELETE", "required_facts": "不需要电话"}},
            {"decision_key": "b", "initial_answer": {"canonical_action": "RETAIN", "required_facts": "需要姓名"},
             "final_answer": {"canonical_action": "RETAIN", "required_facts": "需要姓名"}},
            {"decision_key": "c", "final_answer": {"required_facts": "没有动作"}},
        ],
    }
    raw = json.dumps(payload).encode("utf-8")
    with pytest.raises(ImportError):
        import_return(payload, user_returned=False, original_bytes=raw)
    receipt = import_return(payload, user_returned=True, original_bytes=raw)
    by_key = {item["decision_key"]: item for item in receipt["accepted"]}
    assert by_key["a"]["provenance"] == "human_assisted_not_independent"
    assert by_key["b"]["independent_first_answer"] is True
    assert receipt["train_keys"] == []
    assert receipt["fresh_keys_blocked_from_training"] == ["a", "b"]
    assert receipt["incomplete"][0]["decision_key"] == "c"
    assert receipt["original_sha256"] == hashlib.sha256(raw).hexdigest()
    assert "not_recorded" == receipt["accepted"][0]["reviewer"]


def test_hidden_page_omits_suggestions_until_initial_answers_exist():
    document = {
        "document_id": "pilot-01",
        "runtime_input": {"text": "公开通知草稿", "user_task": "写一条通知"},
        "annotation": {"units": [{
            "information_unit_id": "u1", "quote": "13800000000", "boundary_id": "external_generation",
            "recipient_id": "external_model", "canonical_action": "DELETE",
            "required_facts": "仅测试用的必要事实甲乙丙", "representational_gap": False,
        }]},
    }
    hidden = build_hidden_initial_page([document])
    visible = build_calibration_page([document])
    assert "仅测试用的必要事实甲乙丙" not in hidden
    assert "AI 建议动作" not in hidden
    assert "仅测试用的必要事实甲乙丙" in visible
    assert "删除（DELETE）" in visible and "value='DELETE'" in visible
    second = {
        "document_id": "pilot-02",
        "audit_metadata": {"workflow": "class_coordination"},
        "runtime_input": {"text": "第二篇正文", "user_task": "第二篇需求"},
        "annotation": {"units": [{
            "information_unit_id": "u1", "quote": "教室", "boundary_id": "external_generation",
            "recipient_id": "external_model", "canonical_action": "RETAIN",
            "required_facts": "第二篇事实", "representational_gap": False,
        }]},
    }
    paged = build_calibration_page([document, second])
    assert paged.count("<article class='doc") == 2
    assert "doc is-active" in paged
    assert "doc-head" in paged and "doc-units" in paged
    assert "overflow-y: auto" in paged
    assert "pilot-02　班级协作" in paged
    assert paged.index("doc is-active") < paged.index("pilot-02　班级协作")
    suggestions = suggestion_file([document])
    with pytest.raises(ValueError):
        build_reveal_page({"items": []}, suggestions)
    revealed = build_reveal_page(
        {"items": [{"decision_key": "pilot-01:u1", "initial_answer": {"canonical_action": "DELETE", "required_facts": "不需要电话"}}]},
        suggestions,
    )
    assert "仅测试用的必要事实甲乙丙" in revealed
    l2 = build_hidden_initial_page([document], show_targets=False)
    assert "片段：" not in l2


def test_calibration_pack_keeps_labels_out_of_runtime_and_matches_r0_contract():
    folders = sorted((PACK / "documents").iterdir())
    assert [folder.name for folder in folders] == [f"cal-0{index}" for index in range(1, 9)]
    for folder in folders:
        task = json.loads((folder / "runtime_input.json").read_text(encoding="utf-8"))["user_task"]
        assert "不需要" not in task and "不要" not in task and "删" not in task
        assert "脱敏" not in task and "泛化" not in task and "代号" not in task
        assert len(task) >= 24
    families = set()
    for folder in folders:
        loaded = load_document(folder)
        families.add(loaded["document"]["audit_metadata"]["source_family"])
        for runtime_unit in loaded["runtime_units"]:
            prediction = decide(runtime_unit)
            assert prediction["final_action"] in {item.value for item in Action}
            assert "canonical_action" not in runtime_unit
    assert len(families) == 8
    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["human_reviewed_decisions"] == 38
    assert manifest["status"] == "human_assisted_review_received"
    assert manifest["train_validation"] == "unassigned_until_40_document_manifest"
    active = (ROOT / "delivery/app/models/ACTIVE_MODELS.json").read_bytes()
    weights = (ROOT / "delivery/app/models/necessity_action.joblib").read_bytes()
    assert hashlib.sha256(active).hexdigest() == "f7e27ea6060bc51e70429d967c5afb27a86726c9586f0b8dd03c7138da1af6c8"
    assert hashlib.sha256(weights).hexdigest() == "cbfed4ca422a1a6d416ce1b5f488649816c261b6acc86ffc173887c8dfed1b9f"
    untouched = copy.deepcopy(manifest)
    assert untouched == manifest
