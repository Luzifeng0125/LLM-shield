"""R0：公共候选注册表。规格 yin-dun.candidate_registry.v1。

只读夹具锚点、原文、父节、表格和冻结映射。
不读披露结论、金标、C3/C4 输出，也不把金额、状态、极性或有效时间写入候选。
"""
from __future__ import annotations

from typing import Any, Mapping

from experiments.third_stage.canonical import sha256_hex
from experiments.third_stage.keys import hmac_sha256_display, vault_key_bytes
from experiments.third_stage.maps import (
    ATTRIBUTE_HEADWORDS,
    CLOSED_GRAIN_IDS,
    COLUMN_TO_ATTRIBUTE,
    FORBIDDEN_KEYS,
    GRAIN_BY_SURFACE,
    GRAIN_SURFACES,
    SECTION_SCOPES,
)

SCHEMA = "yin-dun.candidate_registry.v1"
CANDIDATE_FIELDS = (
    "candidate_id",
    "evidence_anchor",
    "subject_id",
    "attribute_id",
    "context_scope_id",
    "grain_id",
    "parent_scope",
)


class RegistryInputError(ValueError):
    """锚点缺失、重复，或输入带有禁止字段。"""


def _reject_forbidden(value: Any, *, where: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in FORBIDDEN_KEYS:
                raise RegistryInputError(f"{where} 含有禁止字段 {key}")
            _reject_forbidden(item, where=f"{where}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_forbidden(item, where=f"{where}[{index}]")


def _unique_attribute(text: str) -> str:
    hits: list[tuple[int, int, str]] = []
    for surface, attribute_id in sorted(ATTRIBUTE_HEADWORDS, key=lambda item: len(item[0]), reverse=True):
        start = 0
        while True:
            found = text.find(surface, start)
            if found < 0:
                break
            end = found + len(surface)
            covered = any(left <= found and end <= right for left, right, _ in hits)
            if not covered:
                hits.append((found, end, attribute_id))
            start = found + len(surface)
    attributes = {attribute_id for _, _, attribute_id in hits}
    if len(attributes) == 1:
        return next(iter(attributes))
    return ""


def _unique_grain(text: str) -> str:
    found = {grain_id for surface, grain_id in GRAIN_SURFACES if surface in text}
    if len(found) == 1:
        return next(iter(found))
    return ""


def _table_attribute(table: Mapping[str, Any]) -> str:
    column_id = str(table.get("column_id") or "")
    header = str(table.get("header") or "")
    from_id = COLUMN_TO_ATTRIBUTE.get(column_id, "")
    from_header = COLUMN_TO_ATTRIBUTE.get(header, "")
    if from_id and from_header and from_id != from_header:
        return ""
    return from_id or from_header


def _table_grain(table: Mapping[str, Any]) -> str:
    cell = str(table.get("grain_cell") or "")
    if not cell:
        return ""
    if cell in CLOSED_GRAIN_IDS:
        return cell
    if cell in GRAIN_BY_SURFACE:
        return GRAIN_BY_SURFACE[cell]
    return ""


def _identity_message(revision_id: str, anchor: str, fields: Mapping[str, str]) -> str:
    parts = [f"revision_id={revision_id}", f"evidence_anchor={anchor}"]
    for name in ("subject_id", "attribute_id", "context_scope_id", "grain_id"):
        if fields[name]:
            parts.append(f"{name}={fields[name]}")
    return "\n".join(parts)


def _subject_id(key: bytes, anchor: Mapping[str, Any], table: Mapping[str, Any] | None) -> str:
    source = table if table and table.get("subject_cluster_key") else anchor
    cluster = str(source.get("subject_cluster_key") or "")
    subject_type = str(source.get("subject_type") or "")
    if not cluster or not subject_type:
        return ""
    if any(ord(char) > 127 for char in cluster):
        return ""
    return hmac_sha256_display(key, f"subject_type={subject_type}\ncluster_key={cluster}")


def _scope_id(key: bytes, anchor: Mapping[str, Any]) -> str:
    scope_type = str(anchor.get("scope_type") or "")
    local_key = str(anchor.get("scope_local_key") or "")
    heading = str(anchor.get("section_heading") or "")
    if not (scope_type and local_key) and heading in SECTION_SCOPES:
        scope_type, local_key = SECTION_SCOPES[heading]
    if not scope_type or not local_key:
        return ""
    if any(ord(char) > 127 for char in local_key):
        return ""
    return hmac_sha256_display(key, f"scope_type={scope_type}\nscope_local_key={local_key}")


def build_candidate(anchor: Mapping[str, Any], *, key: bytes) -> dict[str, str]:
    _reject_forbidden(anchor, where="anchor")
    evidence_anchor = str(anchor.get("evidence_anchor") or "")
    revision_id = str(anchor.get("revision_id") or "")
    if not evidence_anchor or not revision_id:
        raise RegistryInputError("锚点必须同时有 evidence_anchor 和 revision_id")
    raw_text = str(anchor.get("raw_text") or "")
    table = anchor.get("table")
    if table is not None and not isinstance(table, Mapping):
        raise RegistryInputError("table 必须是对象")
    if table:
        attribute_id = _table_attribute(table)
        grain_id = _table_grain(table)
    else:
        attribute_id = _unique_attribute(raw_text)
        grain_id = _unique_grain(raw_text)
    fields = {
        "subject_id": _subject_id(key, anchor, table if isinstance(table, Mapping) else None),
        "attribute_id": attribute_id,
        "context_scope_id": _scope_id(key, anchor),
        "grain_id": grain_id,
        "parent_scope": str(anchor.get("parent_scope") or ""),
    }
    candidate = {
        "candidate_id": hmac_sha256_display(
            key, _identity_message(revision_id, evidence_anchor, fields)
        ),
        "evidence_anchor": evidence_anchor,
        "subject_id": fields["subject_id"],
        "attribute_id": fields["attribute_id"],
        "context_scope_id": fields["context_scope_id"],
        "grain_id": fields["grain_id"],
        "parent_scope": fields["parent_scope"],
    }
    missing = [name for name in CANDIDATE_FIELDS if name not in candidate]
    if missing:
        raise RegistryInputError(f"候选缺少字段 {missing}")
    return candidate


def build_registry(anchors: list[Mapping[str, Any]], *, vault_key: str, for_real_data: bool = False) -> dict[str, Any]:
    """生成注册表。输入顺序不影响哈希。同一锚点重复出现则拒绝。"""
    key = vault_key_bytes(vault_key, for_real_data=for_real_data)
    seen: set[tuple[str, str]] = set()
    candidates: list[dict[str, str]] = []
    for anchor in anchors:
        candidate = build_candidate(anchor, key=key)
        identity = (str(anchor.get("revision_id")), candidate["evidence_anchor"])
        if identity in seen:
            raise RegistryInputError(f"同一修订中的锚点重复注册：{identity[1]}")
        seen.add(identity)
        candidates.append(candidate)
    candidates.sort(key=lambda item: (item["evidence_anchor"], item["candidate_id"]))
    body = {
        "schema": SCHEMA,
        "registry_origin": "r0",
        "candidates": candidates,
    }
    _reject_forbidden(body, where="registry")
    body["registry_sha256"] = sha256_hex(body)
    return body
