"""链接结构门，以及身份链接和更新关系的分离。

这不是 C3，也不是 L4。它只执行冻结方案里已经规定的确定性检查。
link_rationale 不参与判断。结构通过不等于语义正确。
"""
from __future__ import annotations

from typing import Any, Mapping

from experiments.third_stage.maps import EXPLICIT_COREFERENCE

IDENTITY_FIELDS = ("subject_id", "attribute_id", "context_scope_id", "grain_id")
UPDATE_RELATIONS = ("reference_only", "updates_dimension", "unknown")


def l2_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.endswith("\n"):
        normalized = normalized[:-1]
    return normalized


def _hard_conflict(current: Mapping[str, str] | None, target: Mapping[str, str]) -> bool:
    if not current:
        return False
    for field in IDENTITY_FIELDS:
        left = current.get(field) or ""
        right = target.get(field) or ""
        if left and right and left != right:
            return True
    return False


def eligible_candidates(
    candidates: list[Mapping[str, str]],
    *,
    current_anchor: str,
    parent_scope: str,
) -> list[Mapping[str, str]]:
    current = next((item for item in candidates if item.get("evidence_anchor") == current_anchor), None)
    eligible = []
    for candidate in candidates:
        if candidate.get("parent_scope") != parent_scope or not parent_scope:
            continue
        if candidate.get("evidence_anchor") == current_anchor:
            continue
        if _hard_conflict(current, candidate):
            continue
        eligible.append(candidate)
    return eligible


def validate_link(
    proposal: Mapping[str, Any],
    *,
    current_text: str,
    current_anchor: str,
    candidates: list[Mapping[str, str]],
    parent_scope: str,
) -> dict[str, Any]:
    """返回结构结果。accepted 只表示结构门通过，不表示金标正确。"""
    link_type = proposal.get("link_type")
    if link_type == "abstain":
        return {"accepted": False, "structural_failure": False, "reason": "abstain"}
    if link_type not in {"explicit_coreference", "implicit_semantic_reference", "ellipsis"}:
        return {"accepted": False, "structural_failure": True, "reason": "bad_link_type"}

    target_id = proposal.get("target_candidate_id") or ""
    target = next((item for item in candidates if item.get("candidate_id") == target_id), None)
    if target is None or target.get("evidence_anchor") == current_anchor:
        return {"accepted": False, "structural_failure": True, "reason": "target_missing"}
    if target.get("parent_scope") != parent_scope or not parent_scope:
        return {"accepted": False, "structural_failure": True, "reason": "parent_scope"}

    text = l2_text(current_text)
    span = proposal.get("basis_span") or ""
    start = proposal.get("basis_start")
    end = proposal.get("basis_end")
    if not isinstance(start, int) or not isinstance(end, int):
        return {"accepted": False, "structural_failure": True, "reason": "bad_offsets"}
    if not (0 <= start < end <= len(text)) or text[start:end] != span or not span:
        return {"accepted": False, "structural_failure": True, "reason": "basis_mismatch"}

    current = next((item for item in candidates if item.get("evidence_anchor") == current_anchor), None)
    if _hard_conflict(current, target):
        return {"accepted": False, "structural_failure": True, "reason": "hard_conflict"}

    eligible = eligible_candidates(candidates, current_anchor=current_anchor, parent_scope=parent_scope)
    if len(eligible) != 1 or eligible[0].get("candidate_id") != target_id:
        return {"accepted": False, "structural_failure": True, "reason": "not_unique"}

    if link_type == "explicit_coreference" and not any(word in span for word in EXPLICIT_COREFERENCE):
        return {"accepted": False, "structural_failure": True, "reason": "not_explicit"}
    return {"accepted": True, "structural_failure": False, "reason": "structural_pass"}


def apply_update(update: Mapping[str, Any] | None, *, current_text: str) -> dict[str, Any]:
    """身份链接本身不调用本函数。没有更新关系时，旧值全部保留。"""
    if update is None:
        return {"retired_dimensions": [], "pause": False, "reason": "identity_link_only"}
    relation = update.get("relation")
    if relation not in UPDATE_RELATIONS:
        return {"retired_dimensions": [], "pause": True, "reason": "bad_relation"}
    if relation in {"reference_only", "unknown"}:
        return {
            "retired_dimensions": [],
            "pause": relation == "unknown",
            "reason": relation,
        }
    text = l2_text(current_text)
    span = update.get("basis_span") or ""
    start = update.get("basis_start")
    end = update.get("basis_end")
    located = (
        isinstance(start, int)
        and isinstance(end, int)
        and 0 <= start < end <= len(text)
        and text[start:end] == span
        and bool(span)
    )
    dimensions = list(update.get("updated_dimensions") or [])
    if not located or not dimensions:
        return {"retired_dimensions": [], "pause": True, "reason": "update_basis_missing"}
    return {"retired_dimensions": dimensions, "pause": False, "reason": "updates_dimension"}
