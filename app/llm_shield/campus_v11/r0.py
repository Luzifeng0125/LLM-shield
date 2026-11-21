"""R0：由现有任务表冻结出来的离线基线。

线上 ``decision.py`` 仍由模型选动作，硬约束只放行或暂停。R0 不是那条在线路径，
也不读取 ``prefer`` 以外的人工标签。``prefer`` 在任务配置里注明只供给离线参考，
本基线明确使用它，并保持“先提出一个动作，再由硬约束批准或暂停”。

现有 ``prefer`` 不区分处理边界。老师本机交付和外部生成会得到同一提议。
四类任务键以外的校园工作流记为未覆盖并暂停，不套用最近的旧模板。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from ..config import identities, recipients, rules, tasks
from ..m1_access.identity import check_provide
from ..m3_decide.constraints import _task_cfg, action_applicable, check_hard
from ..schema import Action, Segment, Span
from .boundary import propose as boundary_propose

RULE_VERSION = "r0-tasks-v0.1-boundary-blind"
ARBITRATION_VERSION = "r0-b0-arbitration-v1.1"
POLICY_VERSION = "campus-min-disclosure-v1.1"

REQUIRED_PERMISSIONS = {
    "config/identities.yaml": "identities-v0.1",
    "config/recipients.yaml": "recipients-v0.1",
    "config/tasks.yaml": "tasks-v0.1",
    "config/rules.yaml": "rules-v0.1",
}
BOUNDARY_RECIPIENT_TYPE = {
    "external_generation": "EXTERNAL_MODEL",
    "authorized_local_delivery": "VIEWER",
    "public_release": "EGRESS_TOOL",
}
RUNTIME_PURPOSE_SOURCES = {"user_explicit", "trusted_system"}
IGNORED_FIELDS = {
    "annotation",
    "audit_metadata",
    "acceptable_actions",
    "canonical_action",
    "expected_output_constraints",
    "gold_permission_conclusions",
    "human_required_facts",
    "human_resolved_purpose",
    "permission_basis_refs",
    "required_facts",
}
B0_MAY_COVER = {"task_not_in_frozen_table", "category_not_in_frozen_table"}
POLICY_BLOCK_RULES = {
    "PERMISSION",
    "ABSOLUTE_BAN",
    "PURPOSE_LIMIT",
    "RECEIVER_BAN",
    "PERMISSION_LEVEL",
    "LOW_TRUST_IDENTIFIERS",
    "LOW_CONFIDENCE",
    "KNOWN_CATEGORY",
    "ACTION_APPLICABLE",
}
CLARIFICATION_RULES = {"KNOWN_TASK", "KNOWN_RECIPIENT", "KNOWN_IDENTITY"}


def _fail(reason_code: str, pause_kind: str, coverage: str = "not_run", **extra) -> Dict[str, Any]:
    result = {
        "rule_version": RULE_VERSION,
        "coverage": coverage,
        "proposed_action": None,
        "final_action": Action.PAUSE.value,
        "pause_kind": pause_kind,
        "reason_code": reason_code,
        "hard_failed": [],
        "ignored_fields": [],
        "boundary_conditioned": False,
    }
    result.update(extra)
    return result


def _task_table(override: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    return override if override is not None else tasks()


def _known_task(table: Mapping[str, Any], task_key: Any) -> Optional[Mapping[str, Any]]:
    if not isinstance(task_key, str) or not task_key or task_key == "version":
        return None
    value = table.get(task_key)
    return value if isinstance(value, Mapping) else None


def propose_action(task: Mapping[str, Any], category: str) -> tuple[Optional[str], str]:
    """按冻结表提出唯一动作。显式 prefer 优先于 never_send，不在失败后再改选。"""
    prefer = task.get("prefer") if isinstance(task.get("prefer"), Mapping) else {}
    never = set(task.get("never_send") or [])
    if category in prefer:
        action = prefer[category]
        if action not in Action._value2member_map_ or action == Action.PAUSE.value:
            return None, "prefer_value_invalid"
        return str(action), "prefer"
    if category in never:
        return Action.DELETE.value, "never_send"
    return None, "category_not_in_frozen_table"


def _permissions_ok(records: Any) -> bool:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        return False
    found = {}
    for record in records:
        if not isinstance(record, Mapping):
            return False
        source_id = record.get("source_id")
        version = record.get("version")
        if not isinstance(source_id, str) or not isinstance(version, str):
            return False
        found[source_id] = version
    return all(found.get(source) == version for source, version in REQUIRED_PERMISSIONS.items())


def _confidence(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number < 0.0 or number > 1.0:
        return None
    return number


def _segment(unit_id: str, category: str, confidence: float) -> Segment:
    # 硬约束只看类别和置信度。不把原文放进决策对象，避免理由回显敏感片段。
    span = Span(0, 0, "", category, confidence, detector="r0_given_category")
    return Segment(unit_id or "r0", "", 0, 0, [span])


def apply_proposed(runtime: Mapping[str, Any], proposed: str) -> Dict[str, Any]:
    """对已经提出的一个动作做可执行性和硬约束检查。失败则暂停，不改选别的动作。"""
    if proposed not in Action._value2member_map_ or proposed == Action.PAUSE.value:
        return _fail("invalid_proposed_action", "human_handoff")
    category = runtime.get("category")
    confidence = _confidence(runtime.get("confidence"))
    task_key = runtime.get("task_key")
    recipient_id = runtime.get("recipient_id")
    identity_key = runtime.get("identity_key")
    if not isinstance(category, str) or confidence is None:
        return _fail("incomplete_runtime", "human_handoff", proposed_action=proposed)
    segment = _segment(str(runtime.get("unit_id") or ""), category, confidence)
    try:
        applicable = action_applicable(Action(proposed), segment, str(task_key))
        checks = check_hard(Action(proposed), segment, str(task_key), str(recipient_id), str(identity_key))
    except Exception:
        return _fail("hard_check_error", "human_handoff", "not_run", proposed_action=proposed)
    failed = ["ACTION_APPLICABLE"] if not applicable else []
    failed += [check.rule for check in checks if not check.passed]
    if not failed:
        return {
            "rule_version": RULE_VERSION,
            "coverage": "checked",
            "proposed_action": proposed,
            "final_action": proposed,
            "pause_kind": None,
            "reason_code": "hard_check_passed",
            "hard_failed": [],
            "ignored_fields": [],
            "boundary_conditioned": False,
        }
    if any(rule in CLARIFICATION_RULES for rule in failed):
        kind = "clarification"
    elif any(rule in POLICY_BLOCK_RULES for rule in failed):
        kind = "policy_block"
    else:
        kind = "human_handoff"
    return {
        "rule_version": RULE_VERSION,
        "coverage": "checked",
        "proposed_action": proposed,
        "final_action": Action.PAUSE.value,
        "pause_kind": kind,
        "reason_code": "hard_check_rejected",
        "hard_failed": failed,
        "ignored_fields": [],
        "boundary_conditioned": False,
    }


def _waive_precise_budget_ban(checked: Dict[str, Any], proposal: Mapping[str, Any]) -> Dict[str, Any]:
    """量级泛化不再携带精确金额。接收方对精确金额的禁令不改写成删除。"""
    if proposal.get("reason_code") != "magnitude_generalize" or not proposal.get("magnitude_phrase"):
        return checked
    task = _task_cfg(str(proposal.get("hard_task_key") or ""))
    if "BUDGET" in set(task.get("never_send") or []):
        return checked
    failed = set(checked.get("hard_failed") or [])
    if not failed or not failed <= {"RECEIVER_BAN", "PERMISSION_LEVEL"}:
        return checked
    updated = dict(checked)
    updated["hard_failed"] = []
    updated["final_action"] = Action.GENERALIZE.value
    updated["pause_kind"] = None
    updated["magnitude_waiver"] = sorted(failed)
    return updated


def decide(runtime: Mapping[str, Any], *, tasks_override: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """只根据运行时字段决策。标注字段即使被传入也会丢弃，且不出现在结果里。"""
    if not isinstance(runtime, Mapping):
        return _fail("runtime_not_mapping", "human_handoff")
    ignored = sorted(set(runtime) & IGNORED_FIELDS)
    data = {key: value for key, value in runtime.items() if key not in IGNORED_FIELDS}

    if data.get("policy_version") != POLICY_VERSION:
        return _fail("policy_version_mismatch", "human_handoff", ignored_fields=ignored)
    if not _permissions_ok(data.get("trusted_permissions")):
        return _fail("missing_trusted_permission", "clarification", ignored_fields=ignored)

    boundary = data.get("boundary_id")
    recipient_id = data.get("recipient_id")
    if boundary not in BOUNDARY_RECIPIENT_TYPE:
        return _fail("unknown_boundary", "clarification", ignored_fields=ignored)
    if not isinstance(recipient_id, str) or recipient_id not in recipients():
        return _fail("unknown_recipient", "clarification", ignored_fields=ignored)
    expected_type = BOUNDARY_RECIPIENT_TYPE[boundary]
    actual_type = recipients()[recipient_id].get("type")
    if actual_type != expected_type:
        return _fail("boundary_recipient_type_mismatch", "policy_block", ignored_fields=ignored)

    identity_key = data.get("identity_key")
    if not isinstance(identity_key, str) or identity_key not in identities():
        return _fail("unknown_identity", "clarification", ignored_fields=ignored)
    allowed, _why = check_provide(identity_key, recipient_id)
    if not allowed:
        return _fail("identity_cannot_provide", "policy_block", ignored_fields=ignored,
                     proposed_action=None)

    category = data.get("category")
    if not isinstance(category, str) or category not in rules().get("categories", {}):
        return _fail("unknown_category", "human_handoff", ignored_fields=ignored)
    if _confidence(data.get("confidence")) is None:
        return _fail("missing_confidence", "human_handoff", ignored_fields=ignored)
    if data.get("purpose_source") not in RUNTIME_PURPOSE_SOURCES:
        return _fail("purpose_not_runtime", "clarification", "out_of_table", ignored_fields=ignored)

    # 仍是这一次必要性判断。三条边界只改变使用方式，不另建判断入口。
    proposal = boundary_propose(data)
    if proposal.get("status") == "pause":
        return _fail(proposal["reason_code"], proposal.get("pause_kind") or "policy_block", "in_table",
                     ignored_fields=ignored, boundary_conditioned=True,
                     rule_version=proposal.get("rule_version", RULE_VERSION),
                     workflow_id=proposal.get("workflow_id"), magnitude_phrase=None)
    if proposal.get("status") == "proposed":
        checked_runtime = dict(data)
        checked_runtime["task_key"] = proposal["hard_task_key"]
        checked = _waive_precise_budget_ban(apply_proposed(checked_runtime, proposal["action"]), proposal)
        checked["coverage"] = "in_table"
        checked["boundary_conditioned"] = True
        checked["rule_version"] = proposal.get("rule_version", RULE_VERSION)
        checked["workflow_id"] = proposal.get("workflow_id")
        checked["ignored_fields"] = ignored
        checked["magnitude_phrase"] = proposal.get("magnitude_phrase")
        checked["selection_basis"] = proposal.get("reason_code")
        if checked["hard_failed"]:
            checked["reason_code"] = "hard_check_rejected"
        else:
            checked["reason_code"] = proposal.get("reason_code")
        phrase = checked.get("magnitude_phrase") or ""
        digits = "".join(character for character in str(data.get("target_text") or "") if character.isdigit())
        if digits and digits in str(phrase):
            return _fail("magnitude_kept_exact_digits", "human_handoff", ignored_fields=ignored,
                         boundary_conditioned=True)
        return checked

    table = _task_table(tasks_override)
    task = _known_task(table, data.get("task_key"))
    if task is None:
        return _fail("task_not_in_frozen_table", "clarification", "out_of_table", ignored_fields=ignored)
    # 覆盖表只能替换离线 prefer/never_send。硬约束仍读取正式任务配置，因此覆盖键必须真实存在。
    if tasks_override is not None and _known_task(tasks(), data.get("task_key")) is None:
        return _fail("override_task_not_in_live_config", "human_handoff", ignored_fields=ignored)

    proposed, why = propose_action(task, category)
    if proposed is None:
        kind = "human_handoff" if why == "prefer_value_invalid" else "clarification"
        coverage = "out_of_table" if why == "category_not_in_frozen_table" else "not_run"
        return _fail(why, kind, coverage, ignored_fields=ignored)
    checked = apply_proposed(data, proposed)
    checked["coverage"] = "in_table"
    checked["reason_code"] = why if not checked["hard_failed"] else "hard_check_rejected"
    checked["ignored_fields"] = ignored
    checked["selection_basis"] = why
    return checked


def arbitrate(runtime: Mapping[str, Any], r0: Mapping[str, Any], b0_action: Optional[str]) -> Dict[str, Any]:
    """覆盖范围内以 R0 为准。硬权限否决不能被 B0 改写。只有冻结表未覆盖时才考察 B0。"""
    raw_b0 = b0_action if isinstance(b0_action, str) else None
    base = {
        "arbitration_version": ARBITRATION_VERSION,
        "raw_r0": r0.get("final_action"),
        "raw_b0": raw_b0,
        "r0_reason_code": r0.get("reason_code"),
        "boundary_conditioned": r0.get("boundary_conditioned") is True,
        "disagreement": raw_b0 is not None and raw_b0 != r0.get("final_action"),
    }
    if r0.get("reason_code") not in B0_MAY_COVER:
        source = "hard_veto" if r0.get("pause_kind") == "policy_block" else "r0_retained"
        return {**base, "final_action": r0.get("final_action"), "pause_kind": r0.get("pause_kind"),
                "source": source, "b0_applied": False}
    if raw_b0 not in Action._value2member_map_:
        return {**base, "final_action": Action.PAUSE.value, "pause_kind": "human_handoff",
                "source": "b0_unavailable", "b0_applied": False, "disagreement": False}
    if raw_b0 == Action.PAUSE.value:
        return {**base, "final_action": Action.PAUSE.value, "pause_kind": "human_handoff",
                "source": "b0_out_of_table", "b0_applied": True}
    checked = apply_proposed(runtime, raw_b0)
    paused = checked["final_action"] == Action.PAUSE.value
    return {
        **base,
        "final_action": checked["final_action"],
        "pause_kind": checked["pause_kind"],
        "source": "b0_hard_veto" if paused else "b0_out_of_table",
        "b0_applied": True,
        "hard_failed": checked["hard_failed"],
        "proposed_action": checked["proposed_action"],
    }
