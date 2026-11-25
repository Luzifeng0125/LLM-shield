"""Context Package。规格 yin-dun.context_package.v1。

切片只按 parent_scope。不复制其他锚点的原文，也不携带结论、金标或提取结果。
"""
from __future__ import annotations

from typing import Any

from experiments.third_stage.canonical import sha256_hex
from experiments.third_stage.maps import FORBIDDEN_KEYS
from experiments.third_stage.registry import SCHEMA as REGISTRY_SCHEMA

SCHEMA = "yin-dun.context_package.v1"


class ContextError(ValueError):
    """注册表哈希不符，或包内出现禁止内容。"""


def _body_without_hash(registry: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": registry.get("schema"),
        "registry_origin": registry.get("registry_origin"),
        "candidates": registry.get("candidates"),
    }


def assert_registry_intact(registry: dict[str, Any]) -> None:
    if registry.get("schema") != REGISTRY_SCHEMA:
        raise ContextError("不是公共候选注册表")
    expected = sha256_hex(_body_without_hash(registry))
    if registry.get("registry_sha256") != expected:
        raise ContextError("registry_sha256 与候选内容不一致")


def build_context_package(
    registry: dict[str, Any],
    *,
    current_anchor: str,
    current_text: str,
    parent_scope: str,
) -> dict[str, Any]:
    assert_registry_intact(registry)
    if not parent_scope:
        facts: list[dict[str, str]] = []
    else:
        facts = [
            dict(candidate)
            for candidate in registry["candidates"]
            if candidate.get("parent_scope") == parent_scope
        ]
    package = {
        "schema": SCHEMA,
        "registry_sha256": registry["registry_sha256"],
        "current_evidence": {
            "text": current_text,
            "evidence_anchor": current_anchor,
        },
        "current_anchor": current_anchor,
        "parent_scope": parent_scope,
        "candidate_facts": facts,
    }
    _assert_isolated(package)
    return package


def _assert_isolated(package: dict[str, Any]) -> None:
    for fact in package["candidate_facts"]:
        extra = set(fact) - {
            "candidate_id",
            "evidence_anchor",
            "subject_id",
            "attribute_id",
            "context_scope_id",
            "grain_id",
            "parent_scope",
        }
        if extra:
            raise ContextError(f"候选带有注册表以外的字段 {sorted(extra)}")
        leaked = set(fact) & FORBIDDEN_KEYS
        if leaked:
            raise ContextError(f"候选含有禁止字段 {sorted(leaked)}")
    leaked_top = set(package) & FORBIDDEN_KEYS
    if leaked_top:
        raise ContextError(f"上下文包含禁止字段 {sorted(leaked_top)}")


def same_candidate_input(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """C3 与 C4 必须看到同一哈希和同一父节切片。"""
    return (
        left.get("registry_sha256") == right.get("registry_sha256")
        and left.get("candidate_facts") == right.get("candidate_facts")
        and left.get("parent_scope") == right.get("parent_scope")
    )
