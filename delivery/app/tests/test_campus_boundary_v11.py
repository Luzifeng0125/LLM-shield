"""三条边界共用一套必要性，分别选动作。五类新工作各覆盖保留、最小化和权限不足。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from llm_shield.campus_v11.magnitude import magnitude_phrase
from llm_shield.campus_v11.r0 import decide
from llm_shield.config import tasks

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
        "task_key": None,
        "purpose_id": "case",
        "purpose_source": "user_explicit",
        "category": "PERSON_NAME",
        "confidence": 1,
        "trusted_permissions": PERMISSIONS,
        "user_task": "整理这份材料",
        "target_text": "示例",
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize("workflow,boundary,recipient,category,purpose,expected", [
    ("class_coordination", "external_generation", "external_model", "PERSON_NAME", "duty", "PSEUDONYMIZE"),
    ("class_coordination", "authorized_local_delivery", "viewer_peer", "PERSON_NAME", "duty", "RETAIN"),
    ("class_coordination", "public_release", "egress_tool_public", "PERSON_NAME", "duty", "PAUSE"),
    ("coursework_grades", "external_generation", "external_model", "GRADE", "course-reminder", "DELETE"),
    ("coursework_grades", "authorized_local_delivery", "viewer_teacher", "GRADE", "teacher-grade-view", "RETAIN"),
    ("coursework_grades", "external_generation", "external_model", "SENSITIVE_ATTR", "course-reminder", "DELETE"),
    ("teacher_counselor_handoff", "authorized_local_delivery", "viewer_teacher", "PERSON_NAME", "handoff", "RETAIN"),
    ("teacher_counselor_handoff", "external_generation", "external_model", "PERSON_NAME", "handoff", "PSEUDONYMIZE"),
    ("teacher_counselor_handoff", "external_generation", "external_model", "SENSITIVE_ATTR", "handoff", "DELETE"),
    ("awards_financial_aid", "public_release", "egress_tool_public", "PERSON_NAME", "public-count", "DELETE"),
    ("awards_financial_aid", "public_release", "egress_tool_public", "ORG", "public-count", "RETAIN"),
    ("awards_financial_aid", "public_release", "egress_tool_public", "BANK_CARD", "public-count", "DELETE"),
    ("campus_services", "authorized_local_delivery", "viewer_teacher", "PHONE", "repair", "RETAIN"),
    ("campus_services", "external_generation", "external_model", "PHONE", "repair", "PAUSE"),
    ("campus_services", "public_release", "egress_tool_public", "DORM", "repair", "PAUSE"),
])
def test_five_workflows_cover_retain_minimum_and_permission(workflow, boundary, recipient, category, purpose, expected):
    result = decide(runtime(workflow_id=workflow, boundary_id=boundary, recipient_id=recipient,
                            category=category, purpose_id=purpose, target_text="13800001000" if category == "PHONE" else "示例"))
    assert result["final_action"] == expected
    assert result["boundary_conditioned"] is True
    if expected == "PAUSE":
        assert result["proposed_action"] != "DELETE" or result["reason_code"] != "never_send"


def test_display_permission_is_not_reused_for_public_release():
    shared = dict(workflow_id="class_coordination", category="PERSON_NAME", purpose_id="duty")
    display = decide(runtime(**shared, boundary_id="authorized_local_delivery", recipient_id="viewer_peer"))
    public = decide(runtime(**shared, boundary_id="public_release", recipient_id="egress_tool_public"))
    assert display["final_action"] == "RETAIN"
    assert public["final_action"] == "PAUSE"
    assert public["final_action"] != display["final_action"]


def test_external_model_does_not_receive_a_name_just_because_the_teacher_may():
    external = decide(runtime(workflow_id="teacher_counselor_handoff", boundary_id="external_generation",
                              recipient_id="external_model", category="PERSON_NAME"))
    teacher = decide(runtime(workflow_id="teacher_counselor_handoff", boundary_id="authorized_local_delivery",
                             recipient_id="viewer_teacher", category="PERSON_NAME"))
    assert external["final_action"] == "PSEUDONYMIZE"
    assert teacher["final_action"] == "RETAIN"


def test_unlisted_identity_cannot_open_a_new_workflow():
    result = decide(runtime(workflow_id="coursework_grades", identity_key="external_partner",
                            boundary_id="external_generation", recipient_id="external_model", category="GRADE"))
    assert result["final_action"] == "PAUSE"
    assert result["reason_code"] == "identity_cannot_provide"


def test_magnitude_generalizes_without_keeping_the_exact_amount():
    assert magnitude_phrase("12800元") == "约一万元"
    assert magnitude_phrase("数百") is None
    result = decide(runtime(
        workflow_id="minutes_reports_statistics", category="BUDGET", target_text="12800元",
        user_task="整理纪要，印刷费大概是什么水平",
    ))
    assert result["final_action"] == "GENERALIZE"
    assert result["magnitude_phrase"] == "约一万元"
    assert "12800" not in result["magnitude_phrase"]
    missing = decide(runtime(
        workflow_id="minutes_reports_statistics", category="BUDGET", target_text="一笔费用",
        user_task="印刷费大概是什么水平",
    ))
    assert missing["final_action"] == "PAUSE"
    assert missing["reason_code"] == "magnitude_unknown"


def test_exact_amount_stays_on_the_authorized_display_boundary_only():
    external = decide(runtime(
        workflow_id="minutes_reports_statistics", category="BUDGET", target_text="12800元",
        user_task="请做精确核算", boundary_id="external_generation", recipient_id="external_model",
    ))
    teacher = decide(runtime(
        workflow_id="minutes_reports_statistics", category="BUDGET", target_text="12800元",
        user_task="请做精确核算", boundary_id="authorized_local_delivery", recipient_id="viewer_teacher",
    ))
    assert external["final_action"] == "PAUSE"
    assert external["reason_code"] == "exact_amount_not_allowed_on_boundary"
    assert teacher["final_action"] == "RETAIN"


def test_old_task_template_without_workflow_stays_boundary_blind():
    before = tasks()["meeting_minutes"]["prefer"]["PERSON_NAME"]
    result = decide(runtime(task_key="meeting_minutes", workflow_id=None, category="PERSON_NAME",
                            boundary_id="authorized_local_delivery", recipient_id="viewer_teacher"))
    assert before == "PSEUDONYMIZE"
    assert result["final_action"] == "PSEUDONYMIZE"
    assert result["boundary_conditioned"] is False


def test_one_necessity_judgment_is_not_three_models_or_a_growing_rule_table():
    import copy

    from llm_shield.campus_v11 import boundary
    from llm_shield.campus_v11.boundary import COVERED_WORKFLOWS, SHARED_NEED_KINDS, validate_shared_core
    from llm_shield.config import campus_workflows

    table = campus_workflows()
    validate_shared_core(table)
    assert table["design_constraint"]["judgment"] == "single_task_necessity"
    assert table["design_constraint"]["rule_growth"] == "minimum_task_difference_only"
    assert set(table["workflows"]) == set(COVERED_WORKFLOWS)
    assert not any(name.startswith("propose_") for name in dir(boundary))
    for workflow in table["workflows"].values():
        for need in workflow["needs"].values():
            assert need["kind"] in SHARED_NEED_KINDS
            assert "action" not in need

    split = copy.deepcopy(table)
    split["workflows"]["class_coordination"]["needs"]["PERSON_NAME"] = {
        "external_generation": "PSEUDONYMIZE",
        "authorized_local_delivery": "RETAIN",
        "public_release": "DELETE",
    }
    with pytest.raises(ValueError, match="独立动作表"):
        validate_shared_core(split)

    extra = copy.deepcopy(table)
    extra["workflows"]["another_fixed_template"] = extra["workflows"]["class_coordination"]
    with pytest.raises(ValueError, match="八类协作"):
        validate_shared_core(extra)


def test_name_codes_stay_separate_from_phone_numbers():
    external = decide(runtime(
        workflow_id="campus_services", category="PHONE", target_text="13800001007",
        boundary_id="external_generation", recipient_id="external_model",
    ))
    teacher = decide(runtime(
        workflow_id="campus_services", category="PHONE", target_text="13800001007",
        boundary_id="authorized_local_delivery", recipient_id="viewer_teacher",
    ))
    duty = decide(runtime(workflow_id="class_coordination", category="PHONE", target_text="13800001001"))
    assert external["final_action"] == "PAUSE"
    assert teacher["final_action"] == "RETAIN"
    assert duty["final_action"] == "DELETE"

    from llm_shield.m1_access.identity import can_restore
    from llm_shield.m3_decide.constraints import feasible_actions
    from llm_shield.m6_transform.anonymizer import process_segment
    from llm_shield.m6_transform.mapping import MappingTable
    from llm_shield.schema import Action, Decision, Segment, Span

    table = MappingTable()
    name = table.get_or_create("s", "周晚宁", "PERSON_NAME", list("甲乙丙丁戊己庚辛壬癸"), {"person": "人员{code}"})
    assert name.startswith("人员")
    assert table.restore("s", name, can_restore("student_leader", "viewer_teacher")) == "周晚宁"
    assert table.restore("s", name, can_restore("student_leader", "viewer_peer")) is None

    phone = Segment("p", "13800001007", 0, 11, [Span(0, 11, "13800001007", "PHONE")])
    replaced = process_segment(phone, Decision("p", Action.PSEUDONYMIZE, ["PHONE"]), "s2", [], MappingTable())
    assert replaced == ""
    mixed = Segment("m", "周晚宁13800001007", 0, 14, [
        Span(0, 3, "周晚宁", "PERSON_NAME"), Span(3, 14, "13800001007", "PHONE"),
    ])
    kept_name = process_segment(
        mixed, Decision("m", Action.PSEUDONYMIZE, ["PERSON_NAME"]), "s3", [], MappingTable(),
    )
    assert "13800001007" not in kept_name and "周晚宁" not in kept_name and "人员" in kept_name
    acts = feasible_actions(phone, "activity_stats", "external_model", "student_leader")
    assert Action.PSEUDONYMIZE not in acts and Action.RETAIN not in acts


def test_repair_without_a_registered_recipient_pauses_before_guessing():
    result = decide(runtime(workflow_id="campus_services", recipient_id=None, category="PHONE",
                            boundary_id="authorized_local_delivery"))
    assert result["reason_code"] == "unknown_recipient"
    assert result["final_action"] == "PAUSE"
