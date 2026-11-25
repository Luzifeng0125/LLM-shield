"""L4：用当前证据检验披露结论是否仍然成立。

不调用产品外发，也不用结论去挑选互相冲突的证据。
必要维缺失、无法解析或未解决冲突都停住，不放行。
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from experiments.third_stage.c3 import claim_extraction, propose_link, propose_update, unresolved_subjects
from experiments.third_stage.context import build_context_package
from experiments.third_stage.extract import (
    QUANTITY_ATTRIBUTES,
    STATUS_REQUIRED,
    apply_table,
    extract_text,
    locate,
)
from experiments.third_stage.keys import EXAMPLE_VAULT_KEY
from experiments.third_stage.links import IDENTITY_FIELDS, apply_update, l2_text, validate_link
from experiments.third_stage.registry import build_registry

DIMENSIONS = (
    "subject",
    "attribute",
    "context_scope",
    "grain",
    "numeric_value",
    "unit",
    "valid_time",
    "polarity",
    "status",
)


def _kind(item: Mapping[str, Any] | None) -> str:
    if not item:
        return "unmentioned"
    return str(item.get("kind") or "unmentioned")


def _value(item: Mapping[str, Any] | None) -> str:
    if not item or item.get("kind") != "value":
        return ""
    return str(item.get("value") or "")


def _parse_time(value: str) -> tuple[int | None, int]:
    if value.startswith("month:"):
        return None, int(value.split(":", 1)[1])
    year, month = value.split("-", 1)
    return int(year), int(month)


def times_disjoint(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """两边都是确定时间且没有交集时才算不相交。没写时间不能证明分开。"""
    if _kind(left) != "value" or _kind(right) != "value":
        return False
    left_year, left_month = _parse_time(_value(left))
    right_year, right_month = _parse_time(_value(right))
    if left_month != right_month:
        return True
    if left_year is not None and right_year is not None and left_year != right_year:
        return True
    return False


def time_supports(claim_time: Mapping[str, Any], evidence_time: Mapping[str, Any]) -> bool:
    """同一月份可以互相支持。缺少年份的“三月”不从另一条证据抄入年份。"""
    if _kind(claim_time) != "value" or _kind(evidence_time) != "value":
        return False
    if _value(claim_time) == _value(evidence_time):
        return True
    if times_disjoint(claim_time, evidence_time):
        return False
    return True


def _finish(
    *,
    four_state: str | None,
    source_conflict: str,
    reasons: list[str],
    disposition: str,
    extra: dict[str, Any],
) -> dict[str, Any]:
    result = {
        "four_state": four_state,
        "source_conflict": source_conflict,
        "reasons": reasons,
        "disposition": disposition,
        "c4_called": False,
        "deliverable": four_state in {"still_valid", "affected_still_valid"},
    }
    result.update(extra)
    return result


def _current_revision(case: Mapping[str, Any]) -> dict[str, Any]:
    currents = [item for item in case["revisions"] if item.get("role") == "current"]
    if len(currents) != 1:
        raise RuntimeError(f"{case.get('case_id')} 必须有且只有一个当前修订")
    return currents[0]


def _candidate_for(case: Mapping[str, Any], revision_id: str, anchor: str) -> dict[str, str]:
    binding = next(
        item for item in case["registry_binding"]
        if item["revision_id"] == revision_id and item["evidence_anchor"] == anchor
    )
    return next(
        item for item in case["expected_registry"]["candidates"]
        if item["candidate_id"] == binding["candidate_id"]
    )


def _parent_anchor(case: Mapping[str, Any], anchor: Mapping[str, Any], parent_revision_id: str) -> Mapping[str, Any] | None:
    if not parent_revision_id:
        return None
    for item in case["anchors"]:
        if item["revision_id"] == parent_revision_id and item["evidence_anchor"] == anchor["evidence_anchor"]:
            return item
    return None


def _explicit_dims(dimensions: Mapping[str, Any]) -> set[str]:
    explicit = set()
    for name in ("attribute", "grain", "numeric_value", "unit", "valid_time", "status", "polarity"):
        if _kind(dimensions.get(name)) in {"value", "not_applicable", "unparsable"}:
            explicit.add(name)
    return explicit


def _merge_revision(child: dict[str, Any], parent: dict[str, Any] | None) -> dict[str, Any]:
    merged = copy.deepcopy(child)
    if parent is None:
        return merged
    explicit = _explicit_dims(child)
    for name in DIMENSIONS:
        child_item = child[name]
        parent_item = parent[name]
        if name in explicit:
            merged[name] = copy.deepcopy(child_item)
        elif _kind(parent_item) == "value" and _kind(child_item) == "unmentioned":
            merged[name] = copy.deepcopy(parent_item)
        else:
            merged[name] = copy.deepcopy(child_item)
    return merged


def _identity_of(candidate: Mapping[str, str]) -> dict[str, str]:
    return {name: candidate.get(name) or "" for name in IDENTITY_FIELDS}


def _complete(identity: Mapping[str, str]) -> bool:
    return all(identity.get(name) for name in IDENTITY_FIELDS)


def _fact_key(identity: Mapping[str, str]) -> tuple[str, str, str, str] | None:
    if not _complete(identity):
        return None
    return (
        identity["subject_id"],
        identity["attribute_id"],
        identity["context_scope_id"],
        identity["grain_id"],
    )


def _relation(claim_item: Mapping[str, Any], evidence_values: list[str], *, necessary: bool, blocked: bool) -> str:
    if blocked or _kind(claim_item) == "unparsable":
        return "blocked"
    if not necessary:
        if _kind(claim_item) == "not_applicable":
            return "not_applicable"
        return "not_applicable"
    if _kind(claim_item) != "value" or not evidence_values:
        return "missing"
    if any(value != evidence_values[0] for value in evidence_values):
        return "blocked"
    if evidence_values[0] == _value(claim_item):
        return "match"
    return "mismatch"


def verify_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """对一个夹具跑 R0、上下文包、C3、L3 和 L4。不改夹具里的金标。"""
    current = _current_revision(case)
    current_id = current["revision_id"]
    current_anchors = [item for item in case["anchors"] if item["revision_id"] == current_id]
    doc_id = ""
    documents = case.get("source_documents") or []
    if documents:
        doc_id = str(documents[0].get("doc_id") or "")

    registry = build_registry(case["anchors"], vault_key=EXAMPLE_VAULT_KEY, for_real_data=False)
    packages = []
    for anchor in current_anchors:
        packages.append(build_context_package(
            registry,
            current_anchor=anchor["evidence_anchor"],
            current_text=l2_text(str(anchor.get("raw_text") or "")),
            parent_scope=str(anchor.get("parent_scope") or ""),
        ))
    if packages and any(item["registry_sha256"] != registry["registry_sha256"] for item in packages):
        raise RuntimeError("上下文包与注册表哈希不一致")

    extractions: dict[tuple[str, str], dict[str, Any]] = {}
    assertions = []
    for anchor in case["anchors"]:
        extracted = apply_table(extract_text(str(anchor.get("raw_text") or "")), anchor.get("table"))
        extractions[(anchor["revision_id"], anchor["evidence_anchor"])] = extracted
        revision = next(item for item in case["revisions"] if item["revision_id"] == anchor["revision_id"])
        assertions.append({
            "schema": "yin-dun.evidence_assertion.v1",
            "evidence_id": f"{anchor['revision_id']}:{anchor['evidence_anchor']}",
            "revision_id": anchor["revision_id"],
            "role": revision.get("role") or "",
            "evidence_location": locate(
                extracted,
                doc_id=doc_id,
                revision_id=anchor["revision_id"],
                anchor=anchor["evidence_anchor"],
            ),
            "dimensions": extracted["dimensions"],
            "rule_ids": [
                item.get("rule_id", "")
                for item in extracted["dimensions"].values()
                if item.get("rule_id")
            ],
        })

    by_anchor_candidate = {
        anchor["evidence_anchor"]: _candidate_for(case, anchor["revision_id"], anchor["evidence_anchor"])
        for anchor in current_anchors
    }
    blocked_subjects = unresolved_subjects(current_anchors, by_anchor_candidate)
    for assertion in assertions:
        anchor_id = assertion["evidence_location"]["anchor"]
        if assertion["role"] == "current" and anchor_id in blocked_subjects:
            assertion["dimensions"]["subject"] = {
                "kind": "unparsable",
                "rule_id": "c3.subject.unresolved_name",
            }

    claim_text = str((case.get("claim") or {}).get("text") or "")
    claim = claim_extraction(claim_text) if claim_text else None

    base = {
        "registry_sha256": registry["registry_sha256"],
        "context_packages": len(packages),
        "assertions": assertions,
        "claim_assertion": _claim_assertion(claim) if claim else None,
        "links": [],
        "updates": [],
        "temporal_slices": [],
    }

    if not current_anchors:
        return _finish(
            four_state="paused",
            source_conflict="none",
            reasons=["location_missing"],
            disposition="evaluated",
            extra=base,
        )
    texts = [l2_text(str(item.get("raw_text") or "")) for item in current_anchors]
    if len(texts) != len(set(texts)):
        return _finish(
            four_state="paused",
            source_conflict="none",
            reasons=["location_not_unique"],
            disposition="evaluated",
            extra=base,
        )

    stored_links = list(case.get("expected_links") or [])
    human_pending = any(item.get("semantic_gold") == "requires_human" for item in stored_links)
    adversarial = any(item.get("role") == "proposal" for item in stored_links) and not human_pending

    records = []
    candidates = registry["candidates"]
    for anchor in current_anchors:
        candidate = _candidate_for(case, current_id, anchor["evidence_anchor"])
        text = l2_text(str(anchor.get("raw_text") or ""))
        package = next(item for item in packages if item["current_anchor"] == anchor["evidence_anchor"])
        c3_link = propose_link(
            text,
            current_anchor=anchor["evidence_anchor"],
            candidates=package["candidate_facts"],
            parent_scope=str(anchor.get("parent_scope") or ""),
        )
        link_result = c3_link
        link_source = "c3"
        stored = next((item for item in stored_links if item.get("current_anchor") == anchor["evidence_anchor"]), None)
        if adversarial and stored is not None:
            gate = validate_link(
                stored,
                current_text=text,
                current_anchor=anchor["evidence_anchor"],
                candidates=candidates,
                parent_scope=str(anchor.get("parent_scope") or ""),
            )
            link_result = {"proposal": stored, "gate": gate, "eligible_count": c3_link["eligible_count"]}
            link_source = "adversarial_proposal"
        identity = _identity_of(candidate)
        eligible_count = c3_link["eligible_count"]
        incomplete = any(not identity[name] for name in IDENTITY_FIELDS)
        link_needed = incomplete and eligible_count > 0
        accepted = bool(link_result["gate"].get("accepted"))
        inherited = None
        if accepted:
            target = next(
                item for item in candidates
                if item["candidate_id"] == link_result["proposal"].get("target_candidate_id")
            )
            inherited = _identity_of(target)
            identity = inherited
        extraction = extractions[(current_id, anchor["evidence_anchor"])]
        update = propose_update(text, extraction, link_accepted=accepted and link_source == "c3")
        applied = apply_update(update, current_text=text) if update and link_source == "c3" else None
        base["links"].append({
            "anchor": anchor["evidence_anchor"],
            "source": link_source,
            "c3": c3_link,
            "used": link_result,
            "needed": link_needed,
        })
        if update is not None:
            base["updates"].append({"anchor": anchor["evidence_anchor"], "update": update, "applied": applied})
        parent = _parent_anchor(case, anchor, str(current.get("parent_revision_id") or ""))
        parent_extraction = extractions[(parent["revision_id"], parent["evidence_anchor"])]["dimensions"] if parent else None
        values = _merge_revision(extraction["dimensions"], parent_extraction)
        retired: set[str] = set()
        records.append({
            "anchor": anchor["evidence_anchor"],
            "text": text,
            "candidate": candidate,
            "identity": identity,
            "link_needed": link_needed,
            "link_accepted": accepted,
            "inherited": inherited is not None,
            "values": values,
            "retired": retired,
            "update": update,
            "applied": applied,
            "target_anchor": _target_anchor(case, link_result) if accepted else "",
            "subject_unparsable": anchor["evidence_anchor"] in blocked_subjects,
            "l3_attribute": _value(extraction["dimensions"]["attribute"]),
        })

    if human_pending:
        return _finish(
            four_state=None,
            source_conflict="none",
            reasons=["c4_pending"],
            disposition="c4_pending",
            extra=base,
        )

    if any(item.get("applied") and item["applied"].get("pause") for item in base["updates"]):
        return _finish(
            four_state="paused",
            source_conflict="none",
            reasons=["update_unknown"],
            disposition="evaluated",
            extra=base,
        )

    for record in records:
        applied = record["applied"]
        if not applied or applied.get("pause"):
            continue
        target = next((item for item in records if item["anchor"] == record["target_anchor"]), None)
        if target is None:
            continue
        for dimension in applied["retired_dimensions"]:
            target["retired"].add(dimension)
            target["values"][dimension] = {"kind": "unmentioned", "rule_id": "retired"}

    conflict = _source_conflict(records)
    base["source_conflict_pairs"] = conflict
    if conflict:
        return _finish(
            four_state="paused",
            source_conflict="conflict",
            reasons=["source_conflict"],
            disposition="evaluated",
            extra=base,
        )

    if any(item["link_needed"] and not item["link_accepted"] for item in records):
        reason = "subject_unparsable" if blocked_subjects else "link_rejected"
        return _finish(
            four_state="paused",
            source_conflict="none",
            reasons=[reason],
            disposition="evaluated",
            extra=base,
        )

    if claim is None:
        return _finish(
            four_state="paused",
            source_conflict="none",
            reasons=["claim_missing"],
            disposition="evaluated",
            extra=base,
        )

    relations, reasons, temporal = _compare(records, claim)
    base["claim_relation"] = relations
    base["temporal_slices"] = temporal
    if any(item in {"missing", "blocked"} for item in relations.values()):
        return _finish(
            four_state="paused",
            source_conflict="none",
            reasons=reasons or ["necessary_dimension_unresolved"],
            disposition="evaluated",
            extra=base,
        )
    fingerprint_changed = bool(current.get("parent_revision_id")) and not bool(current.get("fingerprint_same_as_snapshot"))
    if relations and all(item in {"match", "not_applicable"} for item in relations.values()):
        state = "affected_still_valid" if fingerprint_changed else "still_valid"
        return _finish(
            four_state=state,
            source_conflict="none",
            reasons=["fingerprint_changed"] if fingerprint_changed else ["fingerprint_unchanged"],
            disposition="evaluated",
            extra=base,
        )
    if any(item == "mismatch" for item in relations.values()):
        return _finish(
            four_state="invalid",
            source_conflict="none",
            reasons=["necessary_dimension_mismatch"],
            disposition="evaluated",
            extra=base,
        )
    return _finish(
        four_state="paused",
        source_conflict="none",
        reasons=["unresolved"],
        disposition="evaluated",
        extra=base,
    )


def _claim_assertion(claim: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "yin-dun.claim_assertion.v1",
        "channel": "claim",
        "text": claim["text"],
        "dimensions": claim["dimensions"],
        "quote_sha256": claim["quote_sha256"],
    }


def _target_anchor(case: Mapping[str, Any], link_result: Mapping[str, Any]) -> str:
    target_id = link_result["proposal"].get("target_candidate_id") or ""
    for binding in case.get("registry_binding") or []:
        if binding["candidate_id"] == target_id:
            return binding["evidence_anchor"]
    return ""


def _active_value(record: Mapping[str, Any], dimension: str) -> Mapping[str, Any] | None:
    if dimension in record["retired"]:
        return None
    return record["values"].get(dimension)


def _record_attribute(record: Mapping[str, Any]) -> str:
    identity_attribute = record["identity"].get("attribute_id") or ""
    if identity_attribute:
        return identity_attribute
    return record.get("l3_attribute") or ""


def _record_grain(record: Mapping[str, Any]) -> str:
    identity_grain = record["identity"].get("grain_id") or ""
    if identity_grain:
        return identity_grain
    return _value(_active_value(record, "grain"))


def _source_conflict(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str, str, str, str], list[tuple[dict[str, Any], str]]] = {}
    for record in records:
        identity = record["identity"]
        if record["link_needed"] and not record["link_accepted"]:
            continue
        if not _complete(identity) and not _record_attribute(record):
            continue
        attribute = _record_attribute(record)
        grain = _record_grain(record)
        subject = identity.get("subject_id") or ""
        scope = identity.get("context_scope_id") or ""
        if not (subject and attribute and scope and grain):
            continue
        for dimension in ("numeric_value", "unit", "status", "polarity", "grain"):
            item = _active_value(record, dimension)
            if _kind(item) != "value":
                continue
            key = (subject, attribute, scope, grain, dimension)
            grouped.setdefault(key, []).append((record, _value(item)))
    conflicts = []
    for key, items in grouped.items():
        for index, (left, left_value) in enumerate(items):
            for right, right_value in items[index + 1:]:
                if left_value == right_value:
                    continue
                if times_disjoint(left["values"]["valid_time"], right["values"]["valid_time"]):
                    continue
                conflicts.append({
                    "dimension": key[4],
                    "left_anchor": left["anchor"],
                    "right_anchor": right["anchor"],
                    "left_value": left_value,
                    "right_value": right_value,
                })
    return conflicts


def _compare(records: list[dict[str, Any]], claim: Mapping[str, Any]) -> tuple[dict[str, str], list[str], list[str]]:
    claim_dims = claim["dimensions"]
    claim_attribute = _value(claim_dims["attribute"])
    reasons: list[str] = []
    if not claim_attribute:
        return {"attribute": "missing"}, ["claim_attribute_unmentioned"], []

    selected = []
    for record in records:
        if record["subject_unparsable"]:
            return {"subject": "blocked"}, ["subject_unparsable"], []
        if _record_attribute(record) == claim_attribute:
            selected.append(record)
    if not selected:
        return {"attribute": "missing"}, ["evidence_attribute_missing"], []

    claim_grain = _value(claim_dims["grain"])
    evidence_grains = {_record_grain(item) for item in selected}
    if claim_grain:
        matched = [item for item in selected if _record_grain(item) == claim_grain]
        if matched:
            selected = matched
        else:
            reasons.append("grain_mismatch")
    elif any(evidence_grains):
        return {"grain": "missing"}, ["claim_grain_unmentioned"], []

    temporal: list[str] = []
    support = []
    for record in selected:
        evidence_time = record["values"]["valid_time"]
        if _kind(claim_dims["valid_time"]) == "value" and times_disjoint(claim_dims["valid_time"], evidence_time):
            temporal.append(record["anchor"])
            continue
        support.append(record)
    if _kind(claim_dims["valid_time"]) == "value" and not support:
        return {"valid_time": "missing"}, ["claim_time_without_evidence"], temporal

    relations: dict[str, str] = {}
    subjects = {item["identity"].get("subject_id") or "" for item in support}
    scopes = {item["identity"].get("context_scope_id") or "" for item in support}
    if "" in subjects or len(subjects) != 1:
        relations["subject"] = "blocked" if any(item["subject_unparsable"] for item in support) else "missing"
        reasons.append("subject_unresolved")
    else:
        relations["subject"] = "match"
    if "" in scopes or len(scopes) != 1:
        relations["context_scope"] = "missing"
        reasons.append("scope_unresolved")
    else:
        relations["context_scope"] = "match"
    relations["attribute"] = "match"

    if claim_grain:
        active_grains = {_record_grain(item) for item in support}
        relations["grain"] = "match" if active_grains == {claim_grain} else "mismatch"
    else:
        relations["grain"] = "not_applicable"

    def evidence_values(dimension: str) -> tuple[list[str], bool]:
        values = []
        blocked = False
        for record in support:
            item = _active_value(record, dimension)
            if _kind(item) == "unparsable":
                blocked = True
            elif _kind(item) == "value" and _value(item) not in values:
                values.append(_value(item))
        return values, blocked

    polarity_values, polarity_blocked = evidence_values("polarity")
    relations["polarity"] = _relation(claim_dims["polarity"], polarity_values, necessary=True, blocked=polarity_blocked)

    status_necessary = claim_attribute in STATUS_REQUIRED
    status_values, status_blocked = evidence_values("status")
    if not status_necessary:
        relations["status"] = "not_applicable"
    else:
        relations["status"] = _relation(
            claim_dims["status"], status_values, necessary=True, blocked=status_blocked
        )

    number_values, number_blocked = evidence_values("numeric_value")
    number_necessary = claim_attribute in QUANTITY_ATTRIBUTES or _kind(claim_dims["numeric_value"]) == "value" or bool(number_values)
    relations["numeric_value"] = _relation(
        claim_dims["numeric_value"], number_values, necessary=number_necessary, blocked=number_blocked
    )

    unit_values, unit_blocked = evidence_values("unit")
    unit_necessary = _kind(claim_dims["numeric_value"]) == "value" or bool(number_values)
    if unit_necessary:
        relations["unit"] = _relation(claim_dims["unit"], unit_values, necessary=True, blocked=unit_blocked)
    else:
        relations["unit"] = "not_applicable"

    time_values, time_blocked = evidence_values("valid_time")
    time_necessary = _kind(claim_dims["valid_time"]) == "value" or bool(time_values)
    if not time_necessary:
        relations["valid_time"] = "not_applicable"
    elif _kind(claim_dims["valid_time"]) == "unparsable" or time_blocked:
        relations["valid_time"] = "blocked"
    elif _kind(claim_dims["valid_time"]) != "value" or not time_values:
        relations["valid_time"] = "missing"
    elif all(time_supports(claim_dims["valid_time"], {"kind": "value", "value": item}) for item in time_values) and len(time_values) == 1:
        relations["valid_time"] = "match"
    elif len(time_values) != 1:
        relations["valid_time"] = "blocked"
    else:
        relations["valid_time"] = "mismatch"

    if any(item in {"missing", "blocked", "mismatch"} for item in relations.values()):
        reasons.append("comparison_finished")
    return relations, reasons, temporal
