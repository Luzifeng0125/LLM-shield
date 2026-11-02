"""Prevent explicit draft provenance from being upgraded by A/B role labels."""
import copy

import pytest

from llm_shield.m4_necessity.research import case_hash
from scripts.build_action_review import build_legacy_cases as build_cases
from scripts.merge_action_reviews import merge_reviews


def response(cases, role, reviewer):
    return {"schema": "action-review-response-v1", "role": role, "reviewer": reviewer,
            "reviews": [{"case_id": cases[0]["case_id"], "case_sha256": case_hash(cases[0]),
                         "annotation": copy.deepcopy(cases[0]["proposal"])}]}


@pytest.mark.parametrize("evidence", [
    {"reviewer": "AI更正稿-待二审-A"},
    {"reviewer_kind": "AI"},
    {"supervision": "machine_draft_not_gold"},
    {"human_reviewed": False},
])
def test_explicit_ai_drafts_cannot_become_human_gold(evidence):
    cases = build_cases()
    a = response(cases, "A", "test-reviewer-A")
    b = response(cases, "B", "test-reviewer-B")
    a.update(evidence)
    with pytest.raises(ValueError, match="AI 草稿"):
        merge_reviews(cases, a, b)


def test_row_level_draft_evidence_cannot_be_hidden_by_top_level_role():
    cases = build_cases()
    a = response(cases, "A", "test-reviewer-A")
    b = response(cases, "B", "test-reviewer-B")
    a["reviews"][0]["reviewer_kind"] = "AI"
    with pytest.raises(ValueError, match="AI 草稿"):
        merge_reviews(cases, a, b)


def test_human_review_can_preserve_previous_ai_provenance():
    cases = build_cases()
    a = response(cases, "A", "test-reviewer-A")
    b = response(cases, "B", "test-reviewer-B")
    a["previous_review_provenance"] = {"reviewer_kind": "AI", "human_reviewed": False}
    _, summary = merge_reviews(cases, a, b)
    assert summary["reviewed"] == 1
