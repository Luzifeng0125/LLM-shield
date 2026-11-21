"""一次任务必要性判断，三条边界共用，再按边界使用。

这里不是三套模型，也不负责扩充固定匹配库。
`needs` 只允许共享 kind，加上这条信息能否在某条边界出现。
模型输入默认最小披露。结果展示只在当前接收人有权时保留原值。
工具外发重新按接收方判断，不沿用展示边界的结果。
硬约束仍然只能放行或暂停。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from ..config import campus_workflows, category_level, identities, recipients
from ..m3_decide.constraints import _task_cfg
from ..schema import Action
from .magnitude import amount_precision, magnitude_phrase

RULE_VERSION = "r0-campus-v1.1-shared-core-boundary"
SHARED_NEED_KINDS = frozenset({
    "drop", "link_person", "public_fact", "aggregate_count", "contact", "drop_unless_raw", "amount",
})
NEED_FIELDS = frozenset({"kind", "raw_on", "required_on"})
COVERED_WORKFLOWS = frozenset({
    "class_coordination", "coursework_grades", "teacher_counselor_handoff",
    "club_membership", "student_events", "awards_financial_aid",
    "campus_services", "minutes_reports_statistics",
})


def validate_shared_core(table: Mapping[str, Any]) -> None:
    """拒绝把边界拆成独立模型，也拒绝在 kind 之外追加动作表。"""
    constraint = table.get("design_constraint")
    if not isinstance(constraint, Mapping):
        raise ValueError("缺少单一必要性判断约束")
    if constraint.get("judgment") != "single_task_necessity":
        raise ValueError("必要性必须只判断一次，不能按边界各做一套模型")
    if constraint.get("boundary_policy") != "shared_core_three_strategies":
        raise ValueError("三条边界必须共用规则核心，只保留使用策略差异")
    if constraint.get("rule_growth") != "minimum_task_difference_only":
        raise ValueError("只能为明确的任务差异补充规则，不能扩张固定匹配库")
    workflows = table.get("workflows")
    if not isinstance(workflows, Mapping) or set(workflows) != set(COVERED_WORKFLOWS):
        raise ValueError("校园覆盖保持八类协作；新增工作必须复用共享 kind，并先改覆盖名单")
    for name, workflow in workflows.items():
        needs = workflow.get("needs") if isinstance(workflow, Mapping) else None
        if not isinstance(needs, Mapping) or not needs:
            raise ValueError(f"{name} 缺少可复用的任务需求")
        for category, need in needs.items():
            if not isinstance(need, Mapping) or set(need) - NEED_FIELDS:
                raise ValueError(f"{name}.{category} 写成了独立动作表，只能保留共享 kind")
            if need.get("kind") not in SHARED_NEED_KINDS:
                raise ValueError(f"{name}.{category} 使用了未共享的匹配规则")
        purposes = workflow.get("purposes") if isinstance(workflow, Mapping) else None
        if purposes is None:
            continue
        if not isinstance(purposes, Mapping):
            raise ValueError(f"{name} 的用途差异格式不正确")
        for purpose_id, purpose_needs in purposes.items():
            if not isinstance(purpose_needs, Mapping):
                raise ValueError(f"{name}.{purpose_id} 的用途差异格式不正确")
            for category, need in purpose_needs.items():
                if not isinstance(need, Mapping) or set(need) - NEED_FIELDS:
                    raise ValueError(f"{name}.{purpose_id}.{category} 写成了独立动作表")
                if need.get("kind") not in SHARED_NEED_KINDS:
                    raise ValueError(f"{name}.{purpose_id}.{category} 使用了未共享的匹配规则")


def _workflows() -> Mapping[str, Any]:
    value = campus_workflows().get("workflows", {})
    return value if isinstance(value, Mapping) else {}


def resolve_workflow(runtime: Mapping[str, Any]) -> Optional[str]:
    workflow_id = runtime.get("workflow_id")
    if isinstance(workflow_id, str) and workflow_id in _workflows():
        return workflow_id
    task_key = runtime.get("task_key")
    if isinstance(task_key, str) and task_key in _workflows():
        return task_key
    return None


def _permission_allows_raw(runtime: Mapping[str, Any], category: str) -> bool:
    identity_key = runtime.get("identity_key")
    recipient_id = runtime.get("recipient_id")
    identity = identities().get(identity_key) if isinstance(identity_key, str) else None
    recipient = recipients().get(recipient_id) if isinstance(recipient_id, str) else None
    task = _task_cfg(str(runtime.get("hard_task_key") or runtime.get("workflow_id") or runtime.get("task_key") or ""))
    if not isinstance(identity, dict) or not isinstance(recipient, dict):
        return False
    if category in set(task.get("never_send") or []):
        return False
    if category in set(recipient.get("forbidden") or []):
        return False
    if category in set(rules_absolute_ban()):
        return False
    limit = min(int(identity.get("max_level", 1)), int(recipient.get("max_level", 1)))
    return category_level(category) <= limit


def rules_absolute_ban() -> set:
    from ..config import rules
    return set(rules().get("hard_constraints", {}).get("absolute_ban", []))


def _minimum(kind: str) -> Optional[str]:
    return {
        "drop": Action.DELETE.value,
        "link_person": Action.PSEUDONYMIZE.value,
        "public_fact": Action.RETAIN.value,
        "aggregate_count": Action.LOCAL_AGGREGATE.value,
        "contact": Action.DELETE.value,
        "drop_unless_raw": Action.DELETE.value,
    }.get(kind)


def propose(runtime: Mapping[str, Any]) -> Dict[str, Any]:
    validate_shared_core(campus_workflows())
    workflow_id = resolve_workflow(runtime)
    if workflow_id is None:
        return {"status": "uncovered", "rule_version": RULE_VERSION}
    workflow = _workflows()[workflow_id]
    category = runtime.get("category")
    needs = workflow.get("needs") if isinstance(workflow.get("needs"), Mapping) else {}
    purposes = workflow.get("purposes") if isinstance(workflow.get("purposes"), Mapping) else {}
    purpose_needs = purposes.get(runtime.get("purpose_id"))
    if isinstance(purpose_needs, Mapping) and category in purpose_needs:
        needs = purpose_needs
    need = needs.get(category) if isinstance(category, str) else None
    if not isinstance(need, dict):
        return {"status": "uncovered", "rule_version": RULE_VERSION, "workflow_id": workflow_id}
    boundary = runtime.get("boundary_id")
    kind = need.get("kind")
    raw_on = set(need.get("raw_on") or [])
    required_on = set(need.get("required_on") or [])
    base = {
        "status": "proposed",
        "rule_version": RULE_VERSION,
        "workflow_id": workflow_id,
        "hard_task_key": workflow_id,
        "boundary_conditioned": True,
        "magnitude_phrase": None,
    }
    if kind == "amount":
        precision = amount_precision(str(runtime.get("user_task") or ""))
        if precision == "unspecified":
            return {"status": "uncovered", "rule_version": RULE_VERSION, "workflow_id": workflow_id}
        if precision == "exact":
            if boundary == "authorized_local_delivery" and _permission_allows_raw({**runtime, "hard_task_key": workflow_id}, "BUDGET"):
                return {**base, "action": Action.RETAIN.value, "reason_code": "display_exact_amount_authorized"}
            return {**base, "status": "pause", "action": None, "pause_kind": "policy_block",
                    "reason_code": "exact_amount_not_allowed_on_boundary"}
        phrase = magnitude_phrase(str(runtime.get("target_text") or ""))
        if phrase is None:
            return {**base, "status": "pause", "action": None, "pause_kind": "clarification",
                    "reason_code": "magnitude_unknown"}
        return {**base, "action": Action.GENERALIZE.value, "reason_code": "magnitude_generalize",
                "magnitude_phrase": phrase}

    if required_on and boundary not in required_on:
        return {**base, "status": "pause", "action": None, "pause_kind": "policy_block",
                "reason_code": "required_fact_not_allowed_on_boundary"}
    if boundary == "authorized_local_delivery" and boundary in raw_on:
        if _permission_allows_raw({**runtime, "hard_task_key": workflow_id}, str(category)):
            return {**base, "action": Action.RETAIN.value, "reason_code": "display_raw_authorized"}
        if boundary in required_on:
            return {**base, "status": "pause", "action": None, "pause_kind": "policy_block",
                    "reason_code": "display_permission_insufficient"}
    action = _minimum(str(kind))
    if action is None:
        return {"status": "uncovered", "rule_version": RULE_VERSION, "workflow_id": workflow_id}
    return {**base, "action": action, "reason_code": f"{boundary}:{kind}"}
