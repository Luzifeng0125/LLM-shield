"""C3 规则基线：显式链接、更新关系和身份拒判。

词表只有“上述、该预算、此项”。没有命中就弃权，不用候选唯一性补关系。
身份链接不自动变成更新关系。历史说法不能替换当前值。
"""
from __future__ import annotations

from typing import Any, Mapping

from experiments.third_stage.extract import HISTORICAL_MARKERS, STATUS_PHRASES, extract_text
from experiments.third_stage.links import eligible_candidates, validate_link
from experiments.third_stage.maps import EXPLICIT_COREFERENCE


def _explicit_hit(text: str) -> tuple[int, int, str] | None:
    hits = []
    for word in EXPLICIT_COREFERENCE:
        index = text.find(word)
        if index >= 0:
            hits.append((index, index + len(word), word))
    if not hits:
        return None
    hits.sort()
    return hits[0]


def propose_link(
    text: str,
    *,
    current_anchor: str,
    candidates: list[Mapping[str, str]],
    parent_scope: str,
) -> dict[str, Any]:
    """只根据当前原文和上下文包里的候选做显式链接。不读取结论。"""
    hit = _explicit_hit(text)
    if hit is None:
        proposal = {
            "link_type": "abstain",
            "target_candidate_id": "",
            "basis_span": "",
            "basis_start": None,
            "basis_end": None,
            "link_rationale": "",
            "rule_id": "c3.link.abstain",
        }
        gate = validate_link(
            proposal,
            current_text=text,
            current_anchor=current_anchor,
            candidates=list(candidates),
            parent_scope=parent_scope,
        )
        return {"proposal": proposal, "gate": gate, "eligible_count": len(eligible_candidates(
            candidates, current_anchor=current_anchor, parent_scope=parent_scope
        ))}

    start, end, span = hit
    eligible = eligible_candidates(candidates, current_anchor=current_anchor, parent_scope=parent_scope)
    if len(eligible) != 1:
        proposal = {
            "link_type": "explicit_coreference",
            "target_candidate_id": "",
            "basis_span": span,
            "basis_start": start,
            "basis_end": end,
            "link_rationale": "",
            "rule_id": "c3.link.not_unique" if eligible else "c3.link.no_target",
        }
        return {
            "proposal": proposal,
            "gate": {
                "accepted": False,
                "structural_failure": True,
                "reason": "not_unique" if eligible else "no_target",
            },
            "eligible_count": len(eligible),
        }

    proposal = {
        "link_type": "explicit_coreference",
        "target_candidate_id": eligible[0]["candidate_id"],
        "basis_span": span,
        "basis_start": start,
        "basis_end": end,
        "link_rationale": "",
        "rule_id": "c3.link.explicit",
    }
    gate = validate_link(
        proposal,
        current_text=text,
        current_anchor=current_anchor,
        candidates=list(candidates),
        parent_scope=parent_scope,
    )
    return {"proposal": proposal, "gate": gate, "eligible_count": 1}


def _historical_span(text: str) -> tuple[int, int, str] | None:
    for marker in HISTORICAL_MARKERS:
        index = text.find(marker)
        if index < 0:
            continue
        nearest: tuple[int, int] | None = None
        for phrase, kind, _value in STATUS_PHRASES:
            if kind == "polarity":
                continue
            pos = text.find(phrase, index)
            if pos < 0:
                continue
            if nearest is None or pos < nearest[0]:
                nearest = (pos, pos + len(phrase))
        end = nearest[1] if nearest else index + len(marker)
        return index, end, text[index:end]
    return None


def propose_update(text: str, extraction: dict[str, Any], *, link_accepted: bool) -> dict[str, Any] | None:
    """已接受的身份链接本身不退役任何值。只有明确写出的维才能更新。"""
    if not link_accepted:
        return None
    if extraction.get("historical"):
        span = _historical_span(text)
        start, end, basis = span if span else (None, None, "")
        return {
            "relation": "unknown",
            "basis_span": basis,
            "basis_start": start,
            "basis_end": end,
            "updated_dimensions": [],
            "rule_id": "c3.update.historical",
        }
    dimensions = []
    basis = None
    status = extraction["dimensions"]["status"]
    number = extraction["dimensions"]["numeric_value"]
    if status.get("kind") == "value" and "start" in status:
        dimensions.append("status")
        basis = status
    if number.get("kind") == "value" and "start" in number:
        dimensions.append("numeric_value")
        if basis is None:
            basis = number
    if not dimensions or basis is None:
        return {
            "relation": "reference_only",
            "basis_span": "",
            "basis_start": None,
            "basis_end": None,
            "updated_dimensions": [],
            "rule_id": "c3.update.reference_only",
        }
    return {
        "relation": "updates_dimension",
        "basis_span": text[basis["start"]:basis["end"]],
        "basis_start": basis["start"],
        "basis_end": basis["end"],
        "updated_dimensions": dimensions,
        "rule_id": "c3.update.explicit",
    }


def unresolved_subjects(anchors: list[Mapping[str, Any]], candidates: Mapping[str, Mapping[str, str]]) -> set[str]:
    """同名且没有区分信息时不分配主体。这里只拒绝，不哈希姓名。"""
    empty = []
    for anchor in anchors:
        candidate = candidates.get(anchor["evidence_anchor"])
        if candidate is not None and not candidate.get("subject_id"):
            empty.append(anchor)
    if len(empty) < 2:
        return set()

    def bigrams(text: str) -> set[str]:
        chars = list(text)
        found = set()
        for index in range(len(chars) - 1):
            pair = chars[index] + chars[index + 1]
            if all("\u4e00" <= char <= "\u9fff" for char in pair):
                found.add(pair)
        return found

    shared = bigrams(str(empty[0].get("raw_text") or ""))
    for anchor in empty[1:]:
        shared &= bigrams(str(anchor.get("raw_text") or ""))
    if not shared:
        return set()
    return {str(anchor["evidence_anchor"]) for anchor in empty}


def claim_extraction(text: str) -> dict[str, Any]:
    """结论通道。调用方只能传入结论文本。"""
    extracted = extract_text(text)
    extracted["channel"] = "claim"
    return extracted
