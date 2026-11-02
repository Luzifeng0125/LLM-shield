"""校验校园材料的三个区域确实分开，并给出只含运行时字段的 R0 输入。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping

from .r0 import POLICY_VERSION

FORBIDDEN_RUNTIME_KEYS = {
    "annotation",
    "audit_metadata",
    "acceptable_actions",
    "canonical_action",
    "expected_output_constraints",
    "human_required_facts",
    "human_resolved_purpose",
    "permission_basis_refs",
    "required_facts",
    "representational_gap",
    "pause_group_id",
    "pause_kind",
    "counts_as_primary",
    "counterfactual",
    "annotation_status",
}
LENGTH_BANDS = {
    "short": (100, 400),
    "medium": (401, 1600),
    "long": (1601, 4000),
}


class PackError(ValueError):
    """材料包违反 v1.1 的区域或标注约束。"""


def _keys(value: Any, found: set) -> None:
    if isinstance(value, Mapping):
        found.update(str(key) for key in value)
        for item in value.values():
            _keys(item, found)
    elif isinstance(value, list):
        for item in value:
            _keys(item, found)


def validate_runtime_file(payload: Mapping[str, Any]) -> None:
    found: set = set()
    _keys(payload, found)
    leaked = sorted(found & FORBIDDEN_RUNTIME_KEYS)
    if leaked:
        raise PackError(f"运行时文件含有标注字段 {leaked}")


def validate_annotation(text: str, annotation: Mapping[str, Any]) -> None:
    units = annotation.get("units")
    if not isinstance(units, list) or not units:
        raise PackError("标注没有信息单元")
    seen = set()
    for unit in units:
        quote = unit.get("quote")
        start, end = unit.get("start"), unit.get("end")
        if not isinstance(quote, str) or not isinstance(start, int) or not isinstance(end, int):
            raise PackError("信息单元缺少原文区间")
        if text[start:end] != quote:
            raise PackError(f"区间与原文不一致: {unit.get('information_unit_id')}")
        key = (unit.get("information_unit_id"), unit.get("boundary_id"), unit.get("recipient_id"))
        if key in seen:
            raise PackError(f"决策键重复: {key}")
        seen.add(key)
        if unit.get("policy_version") != POLICY_VERSION or unit.get("annotation_status") != "ai_draft":
            raise PackError("标注状态不是本轮 AI 草稿")
        gap = unit.get("representational_gap") is True
        action = unit.get("canonical_action")
        if gap and action is not None:
            raise PackError("能力缺口不能强行填写六类首选")
        if not gap and not isinstance(action, str):
            raise PackError("非缺口单元缺少首选动作")
        if not str(unit.get("required_facts") or "").strip():
            raise PackError("缺少必要事实")
        if unit.get("canonical_action") == "PAUSE" and not unit.get("pause_group_id"):
            raise PackError("PAUSE 缺少分组")


def validate_document(document: Mapping[str, Any]) -> None:
    runtime = document["runtime_input"]
    validate_runtime_file(runtime)
    text = runtime["text"]
    band = document["length_band"]
    low, high = LENGTH_BANDS[band]
    if not low <= len(text) <= high:
        raise PackError(f"{document['document_id']} 篇幅 {len(text)} 不在 {band} {low}-{high}")
    if runtime.get("policy_version") != POLICY_VERSION:
        raise PackError("运行时协议版本不符")
    validate_annotation(text, document["annotation"])
    if document["audit_metadata"].get("authoring") != "ai_draft":
        raise PackError("审计区把 AI 草稿写成了人工")
    if document["audit_metadata"].get("train_validation") != "unassigned_until_40_document_manifest":
        raise PackError("40 篇未齐，不能提前写成训练或验证")


def load_document(directory: Path) -> Dict[str, Any]:
    runtime = json.loads((directory / "runtime_input.json").read_text(encoding="utf-8"))
    units = json.loads((directory / "runtime_units.json").read_text(encoding="utf-8"))
    annotation = json.loads((directory / "annotation.json").read_text(encoding="utf-8"))
    audit = json.loads((directory / "audit_metadata.json").read_text(encoding="utf-8"))
    validate_runtime_file(runtime)
    validate_runtime_file({"units": units})
    document = {
        "document_id": directory.name,
        "length_band": audit["length_band"],
        "runtime_input": runtime,
        "annotation": annotation,
        "audit_metadata": audit,
    }
    validate_document(document)
    return {"document": document, "runtime_units": units}


def iter_r0_runtime(directory: Path) -> Iterator[Mapping[str, Any]]:
    loaded = load_document(directory)
    for unit in loaded["runtime_units"]:
        yield unit
