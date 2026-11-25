"""T1–T13 夹具定义。

expected_four_state 只记录冻结方案的金标。本模块不计算四态。
R0 能核对的只有注册表；链接结构门和更新分离另有确定性检查。
"""
from __future__ import annotations

from typing import Any

from experiments.third_stage.keys import EXAMPLE_VAULT_KEY
from experiments.third_stage.registry import build_registry

SUBJECT = {"subject_type": "organization", "subject_cluster_key": "cluster-014"}
SCOPE = {"scope_type": "activity", "scope_local_key": "spring-recruit"}
PENDING = "pending_l3_l4"

CORE_FOUR_STATE = {
    "T1": "invalid",
    "T2": "invalid",
    "T3": "affected_still_valid",
    "T4": "paused",
    "T5": "invalid",
    "T6": "invalid",
    "T7": "paused",
    "T8": "paused",
    "T9": "invalid",
    "T10": "paused",
    "T11": "still_valid",
    "T12": "still_valid",
    "T13": "still_valid",
}


def _dim(kind: str, value: str | None = None) -> dict[str, str]:
    if kind == "value":
        if value is None:
            raise ValueError("value 维必须带规范值")
        return {"kind": "value", "value": value}
    return {"kind": kind}


def _anchor(anchor: str, revision: str, text: str, parent: str, *, identity: bool = True, table: dict | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "evidence_anchor": anchor,
        "revision_id": revision,
        "raw_text": text,
        "parent_scope": parent,
    }
    if identity:
        item.update(SUBJECT)
        item.update(SCOPE)
    if table:
        item["table"] = table
    return item


def _case(**kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("execution", PENDING)
    kwargs.setdefault("expected_links", [])
    kwargs.setdefault("expected_update_relations", [])
    kwargs.setdefault("negative_proposals", [])
    return kwargs


def _definitions() -> list[dict[str, Any]]:
    budget = "建议将差旅预算调整为 8000 元。"
    approved_8000 = "差旅预算已批准，金额为 8000 元。"
    approved_9000 = "差旅预算已批准，金额为 9000 元。"
    return [
        _case(
            case_id="T1",
            core_id="T1",
            source_documents=[{"doc_id": "doc-t1", "text": budget}],
            revisions=[{"revision_id": "rev-t1", "parent_revision_id": "", "role": "current"}],
            evidence_anchors=["block:a1"],
            anchors=[_anchor("block:a1", "rev-t1", budget, "sec_1")],
            oracle={"block:a1": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True}},
            claim={"text": "差旅预算已经批准为 8000 元。", "status": _dim("value", "approved"), "numeric_value": _dim("value", "8000")},
            expected_assertions={"block:a1": {"status": _dim("value", "suggested"), "numeric_value": _dim("value", "8000")}},
            expected_source_conflict="none",
            expected_four_state="invalid",
            rationale="只有建议金额。状态 suggested 与结论 approved 不相等，没有第二条证据。",
        ),
        _case(
            case_id="T2",
            core_id="T2",
            source_documents=[{"doc_id": "doc-t2", "text": approved_9000}],
            revisions=[
                {"revision_id": "rev-t2-old", "parent_revision_id": "", "role": "parent"},
                {"revision_id": "rev-t2", "parent_revision_id": "rev-t2-old", "role": "current"},
            ],
            evidence_anchors=["block:a1"],
            anchors=[
                _anchor("block:a1", "rev-t2-old", approved_8000, "sec_1"),
                _anchor("block:a1", "rev-t2", approved_9000, "sec_1"),
            ],
            oracle={
                "rev-t2-old/block:a1": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True},
                "rev-t2/block:a1": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True},
            },
            claim={"text": "差旅预算已经批准为 8000 元。", "numeric_value": _dim("value", "8000")},
            expected_update_relations=[{
                "relation": "updates_dimension",
                "via": "parent_child_revision",
                "source_anchor": "block:a1",
                "revision_id": "rev-t2",
                "basis_span": approved_9000,
                "basis_start": 0,
                "basis_end": len(approved_9000),
                "updated_dimensions": ["numeric_value"],
                "current_text": approved_9000,
            }],
            expected_assertions={"current": {"numeric_value": _dim("value", "9000"), "status": _dim("value", "approved")}},
            expected_source_conflict="none",
            expected_four_state="invalid",
            rationale="父子修订让旧金额退出活动集。这不是两条金额并存，活动金额与结论不一致。",
        ),
        _case(
            case_id="T3",
            core_id="T3",
            source_documents=[{"doc_id": "doc-t3", "text": approved_8000}],
            revisions=[{"revision_id": "rev-t3", "parent_revision_id": "rev-t3-old", "role": "current"}],
            evidence_anchors=["block:a1"],
            anchors=[_anchor("block:a1", "rev-t3", approved_8000, "sec_1")],
            oracle={"block:a1": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True}},
            claim={"text": "差旅预算已经批准为 8000 元。"},
            expected_assertions={"block:a1": {"status": _dim("value", "approved"), "numeric_value": _dim("value", "8000")}},
            expected_source_conflict="none",
            expected_four_state="affected_still_valid",
            rationale="同一 block_id 改写后重新提取，必要维与结论一致，引文指纹已经变化。",
        ),
        _case(
            case_id="T3-no-block",
            core_id="T3",
            source_documents=[{"doc_id": "doc-t3b", "text": "差旅经费调整为八千元。"}],
            revisions=[{"revision_id": "rev-t3b", "parent_revision_id": "", "role": "current"}],
            evidence_anchors=[],
            anchors=[],
            oracle={},
            claim={"text": "差旅预算已经批准为 8000 元。"},
            expected_assertions={},
            expected_source_conflict="none",
            expected_four_state="paused",
            rationale="去掉 block_id 后，改写句不能唯一对应旧引文，停在定位。",
        ),
        _case(
            case_id="T4",
            core_id="T4",
            source_documents=[{"doc_id": "doc-t4", "text": "张三到场。另一处也记录张三到场。"}],
            revisions=[{"revision_id": "rev-t4", "parent_revision_id": "", "role": "current"}],
            evidence_anchors=["block:p1", "block:p2"],
            anchors=[
                _anchor("block:p1", "rev-t4", "张三到场。", "sec_1", identity=False),
                _anchor("block:p2", "rev-t4", "另一处记录张三到场。", "sec_1", identity=False),
            ],
            oracle={
                "block:p1": {"attribute_id": "", "grain_id": "", "has_subject": False, "has_scope": False},
                "block:p2": {"attribute_id": "", "grain_id": "", "has_subject": False, "has_scope": False},
            },
            claim={"text": "张三参加了活动。"},
            expected_assertions={"subject": _dim("unparsable")},
            expected_source_conflict="none",
            expected_four_state="paused",
            rationale="两名张三没有区分信息。R0 不哈希姓名，主体留空，不能靠结论补上。",
        ),
        _case(
            case_id="T4-claim-unparsable",
            core_id="T4",
            source_documents=[{"doc_id": "doc-t4c", "text": budget}],
            revisions=[{"revision_id": "rev-t4c", "parent_revision_id": "", "role": "current"}],
            evidence_anchors=["block:a1"],
            anchors=[_anchor("block:a1", "rev-t4c", budget, "sec_1")],
            oracle={"block:a1": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True}},
            claim={"text": "差旅预算已核准为 8000 元。", "status": _dim("unparsable")},
            expected_assertions={"block:a1": {"status": _dim("value", "suggested"), "numeric_value": _dim("value", "8000")}},
            expected_source_conflict="none",
            expected_four_state="paused",
            rationale="结论侧必要状态不能规范化。不得把证据里的金额当成结论已经得到支持。",
        ),
        _case(
            case_id="T4-claim-unmentioned",
            core_id="T4",
            source_documents=[{"doc_id": "doc-t4d", "text": approved_8000}],
            revisions=[{"revision_id": "rev-t4d", "parent_revision_id": "", "role": "current"}],
            evidence_anchors=["block:a1"],
            anchors=[_anchor("block:a1", "rev-t4d", approved_8000, "sec_1")],
            oracle={"block:a1": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True}},
            claim={"text": "活动按计划进行。", "numeric_value": _dim("unmentioned"), "status": _dim("unmentioned")},
            expected_assertions={"block:a1": {"numeric_value": _dim("value", "8000"), "status": _dim("value", "approved")}},
            expected_source_conflict="none",
            expected_four_state="paused",
            rationale="结论没有写必要金额和必要状态。证据里有值也不是 match。",
        ),
        _case(
            case_id="T5",
            core_id="T5",
            source_documents=[{"doc_id": "doc-t5", "text": "尚未达到 12 人。"}],
            revisions=[{"revision_id": "rev-t5", "parent_revision_id": "", "role": "current"}],
            evidence_anchors=["block:n1"],
            anchors=[_anchor("block:n1", "rev-t5", "尚未达到 12 人。", "sec_1")],
            oracle={"block:n1": {"attribute_id": "", "grain_id": "", "has_subject": True, "has_scope": True}},
            claim={"text": "活动人数达到 12 人。", "polarity": _dim("value", "affirm")},
            expected_assertions={"block:n1": {"polarity": _dim("value", "neg"), "status": _dim("not_applicable"), "numeric_value": _dim("value", "12")}},
            expected_source_conflict="none",
            expected_four_state="invalid",
            rationale="尚未达到改的是极性。人数属性的状态是 not_applicable，不是 not_yet_approved。这句没有冻结中心词“人数”或“活动人数”，R0 不把“12 人”猜成属性。",
        ),
        _case(
            case_id="T6",
            core_id="T6",
            source_documents=[{"doc_id": "doc-t6", "text": "计划周五前完成。"}],
            revisions=[{"revision_id": "rev-t6", "parent_revision_id": "", "role": "current"}],
            evidence_anchors=["block:d1"],
            anchors=[_anchor("block:d1", "rev-t6", "计划周五前完成。", "sec_1")],
            oracle={"block:d1": {"attribute_id": "", "grain_id": "", "has_subject": True, "has_scope": True}},
            claim={"text": "该项已完成。", "status": _dim("value", "completed")},
            expected_assertions={"block:d1": {"status": _dim("value", "planned")}},
            expected_source_conflict="none",
            expected_four_state="invalid",
            rationale="计划对已完成。R0 在这句里没有唯一属性中心词，属性留空，不从结论补。",
        ),
        _case(
            case_id="T7",
            core_id="T7",
            source_documents=[{"doc_id": "doc-t7", "text": "全体活动人数为 12 人。全体活动人数为 15 人。"}],
            revisions=[{"revision_id": "rev-t7", "parent_revision_id": "", "role": "current"}],
            evidence_anchors=["block:c12", "block:c15"],
            anchors=[
                _anchor("block:c12", "rev-t7", "全体活动人数为 12 人。", "sec_1"),
                _anchor("block:c15", "rev-t7", "全体活动人数为 15 人。", "sec_1"),
            ],
            oracle={
                "block:c12": {"attribute_id": "participant_count", "grain_id": "grain_all", "has_subject": True, "has_scope": True},
                "block:c15": {"attribute_id": "participant_count", "grain_id": "grain_all", "has_subject": True, "has_scope": True},
            },
            claim={"text": "全体活动人数为 12 人。", "numeric_value": _dim("value", "12")},
            expected_assertions={
                "block:c12": {"numeric_value": _dim("value", "12"), "valid_time": _dim("value", "2026-03")},
                "block:c15": {"numeric_value": _dim("value", "15"), "valid_time": _dim("value", "2026-03")},
            },
            expected_source_conflict="conflict",
            expected_four_state="paused",
            rationale="同一事实、同一时间、人数不同，没有修订。结论写成 12 也不能挑选证据。",
        ),
        _case(
            case_id="T7-a",
            core_id="T7",
            source_documents=[{"doc_id": "doc-t7a", "text": "两笔差旅预算金额不同。"}],
            revisions=[{"revision_id": "rev-t7a", "parent_revision_id": "", "role": "current"}],
            evidence_anchors=["block:m8", "block:m9"],
            anchors=[
                _anchor("block:m8", "rev-t7a", "差旅预算为 8000 元。", "sec_1"),
                _anchor("block:m9", "rev-t7a", "差旅预算为 9000 元。", "sec_1"),
            ],
            oracle={
                "block:m8": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True},
                "block:m9": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True},
            },
            claim={"text": "差旅预算为 8000 元。"},
            expected_assertions={
                "block:m8": {"numeric_value": _dim("value", "8000"), "valid_time": _dim("value", "2026-03")},
                "block:m9": {"numeric_value": _dim("value", "9000"), "valid_time": _dim("value", "2026-03")},
            },
            expected_source_conflict="conflict",
            expected_four_state="paused",
            rationale="同一事实身份、同一有效时间、金额不同。",
        ),
        _case(
            case_id="T7-b",
            core_id="T7",
            source_documents=[{"doc_id": "doc-t7b", "text": "人数和预算是两件事实。"}],
            revisions=[{"revision_id": "rev-t7b", "parent_revision_id": "", "role": "current"}],
            evidence_anchors=["block:people", "block:money"],
            anchors=[
                _anchor("block:people", "rev-t7b", "全体活动人数为 12 人。", "sec_1"),
                _anchor("block:money", "rev-t7b", "差旅预算为 8000 元。", "sec_1"),
            ],
            oracle={
                "block:people": {"attribute_id": "participant_count", "grain_id": "grain_all", "has_subject": True, "has_scope": True},
                "block:money": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True},
            },
            claim={"text": "全体活动人数为 12 人。"},
            expected_assertions={
                "block:people": {"numeric_value": _dim("value", "12")},
                "block:money": {"numeric_value": _dim("value", "8000")},
            },
            expected_source_conflict="none",
            expected_four_state="still_valid",
            rationale="同一主体的人数和金额是不同 fact_key。预算数字不构成人数冲突。结论只核对人数。",
        ),
        _case(
            case_id="T7-c",
            core_id="T7",
            source_documents=[{"doc_id": "doc-t7c", "text": "两种口径同时存在。"}],
            revisions=[{"revision_id": "rev-t7c", "parent_revision_id": "", "role": "current"}],
            evidence_anchors=["block:all", "block:staff"],
            anchors=[
                _anchor("block:all", "rev-t7c", "全体活动人数为 12 人。", "sec_1"),
                _anchor("block:staff", "rev-t7c", "不含工作人员的活动人数为 9 人。", "sec_1"),
            ],
            oracle={
                "block:all": {"attribute_id": "participant_count", "grain_id": "grain_all", "has_subject": True, "has_scope": True},
                "block:staff": {"attribute_id": "participant_count", "grain_id": "grain_excluding_staff", "has_subject": True, "has_scope": True},
            },
            claim={"text": "全体活动人数为 12 人。"},
            expected_assertions={
                "block:all": {"numeric_value": _dim("value", "12"), "grain": _dim("value", "grain_all")},
                "block:staff": {"numeric_value": _dim("value", "9"), "grain": _dim("value", "grain_excluding_staff")},
            },
            expected_source_conflict="none",
            expected_four_state="still_valid",
            rationale="同一属性、不同口径，没有修订把旧口径退出。不直接记 Source Conflict。结论只对全体口径。",
        ),
        _case(
            case_id="T7-d",
            core_id="T7",
            source_documents=[{"doc_id": "doc-t7d", "text": "12 与 15 并存，结论写成其中一边。"}],
            revisions=[{"revision_id": "rev-t7d", "parent_revision_id": "", "role": "current"}],
            evidence_anchors=["block:left", "block:right"],
            anchors=[
                _anchor("block:left", "rev-t7d", "全体活动人数为 12 人。", "sec_1"),
                _anchor("block:right", "rev-t7d", "全体活动人数为 15 人。", "sec_1"),
            ],
            oracle={
                "block:left": {"attribute_id": "participant_count", "grain_id": "grain_all", "has_subject": True, "has_scope": True},
                "block:right": {"attribute_id": "participant_count", "grain_id": "grain_all", "has_subject": True, "has_scope": True},
            },
            claim={"text": "全体活动人数为 12 人。"},
            expected_assertions={
                "block:left": {"numeric_value": _dim("value", "12")},
                "block:right": {"numeric_value": _dim("value", "15")},
            },
            expected_source_conflict="conflict",
            expected_four_state="paused",
            rationale="同一必要维无法消除矛盾。即使结论等于其中一边，也暂停，不改成 invalid 或交付。",
        ),
        _case(
            case_id="T8",
            core_id="T8",
            source_documents=[{"doc_id": "doc-t8", "text": "旧引文已删除。"}],
            revisions=[{"revision_id": "rev-t8", "parent_revision_id": "rev-t8-old", "role": "current"}],
            evidence_anchors=[],
            anchors=[],
            oracle={},
            claim={"text": "全体活动人数为 12 人。"},
            expected_assertions={},
            expected_source_conflict="none",
            expected_four_state="paused",
            rationale="旧引文删除且没有锚点，精确检索零次，停在 L1。",
        ),
        _case(
            case_id="T9",
            core_id="T9",
            source_documents=[{"doc_id": "doc-t9", "text": "同一业务键改口径。"}],
            revisions=[
                {"revision_id": "rev-t9-old", "parent_revision_id": "", "role": "parent"},
                {"revision_id": "rev-t9", "parent_revision_id": "rev-t9-old", "role": "current"},
            ],
            evidence_anchors=["row:1"],
            anchors=[
                _anchor("row:1", "rev-t9-old", "12", "sec_1", table={
                    "column_id": "participant_count", "header": "人数", "grain_cell": "全体", **SUBJECT,
                }),
                _anchor("row:1", "rev-t9", "9", "sec_1", table={
                    "column_id": "participant_count", "header": "人数", "grain_cell": "不含工作人员", **SUBJECT,
                }),
            ],
            oracle={
                "rev-t9-old/row:1": {"attribute_id": "participant_count", "grain_id": "grain_all", "has_subject": True, "has_scope": True},
                "rev-t9/row:1": {"attribute_id": "participant_count", "grain_id": "grain_excluding_staff", "has_subject": True, "has_scope": True},
            },
            claim={"text": "全体活动人数为 12 人。"},
            expected_update_relations=[{
                "relation": "updates_dimension",
                "via": "parent_child_revision",
                "source_anchor": "row:1",
                "revision_id": "rev-t9",
                "basis_span": "9",
                "basis_start": 0,
                "basis_end": 1,
                "updated_dimensions": ["grain", "numeric_value"],
                "current_text": "9",
            }],
            expected_assertions={"current": {"numeric_value": _dim("value", "9"), "grain": _dim("value", "grain_excluding_staff")}},
            expected_source_conflict="none",
            expected_four_state="invalid",
            rationale="同一业务键的父修订替换口径。旧口径退出活动集，不是两个口径并存的冲突。",
        ),
        _case(
            case_id="T10",
            core_id="T10",
            source_documents=[{"doc_id": "doc-t10", "text": "同一引文出现两次。"}],
            revisions=[{"revision_id": "rev-t10", "parent_revision_id": "", "role": "current"}],
            evidence_anchors=["block:q1", "block:q2"],
            anchors=[
                _anchor("block:q1", "rev-t10", "全体活动人数为 12 人。", "sec_1"),
                _anchor("block:q2", "rev-t10", "全体活动人数为 12 人。", "sec_1"),
            ],
            oracle={
                "block:q1": {"attribute_id": "participant_count", "grain_id": "grain_all", "has_subject": True, "has_scope": True},
                "block:q2": {"attribute_id": "participant_count", "grain_id": "grain_all", "has_subject": True, "has_scope": True},
            },
            claim={"text": "全体活动人数为 12 人。"},
            expected_assertions={},
            expected_source_conflict="none",
            expected_four_state="paused",
            rationale="同一引文出现两次，没有唯一锚点，停在 L1。R0 仍为两个锚点各登记一条，不负责消解定位。",
        ),
        _case(
            case_id="T11",
            core_id="T11",
            source_documents=[{"doc_id": "doc-t11", "text": approved_8000}],
            revisions=[{"revision_id": "rev-t11", "parent_revision_id": "", "role": "current", "fingerprint_same_as_snapshot": True}],
            evidence_anchors=["block:a1"],
            anchors=[_anchor("block:a1", "rev-t11", approved_8000, "sec_1")],
            oracle={"block:a1": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True}},
            claim={"text": "差旅预算已经批准为 8000 元。"},
            expected_assertions={"block:a1": {"numeric_value": _dim("value", "8000"), "status": _dim("value", "approved")}},
            expected_source_conflict="none",
            expected_four_state="still_valid",
            rationale="全文指纹相同，必要维都是相等的 value。",
        ),
        _case(
            case_id="T12",
            core_id="T12",
            source_documents=[{"doc_id": "doc-t12", "text": "三月与四月人数不同。"}],
            revisions=[{"revision_id": "rev-t12", "parent_revision_id": "", "role": "current"}],
            evidence_anchors=["block:mar", "block:apr"],
            anchors=[
                _anchor("block:mar", "rev-t12", "2026年3月全体活动人数为 12 人。", "sec_1"),
                _anchor("block:apr", "rev-t12", "2026年4月全体活动人数为 15 人。", "sec_1"),
            ],
            oracle={
                "block:mar": {"attribute_id": "participant_count", "grain_id": "grain_all", "has_subject": True, "has_scope": True},
                "block:apr": {"attribute_id": "participant_count", "grain_id": "grain_all", "has_subject": True, "has_scope": True},
            },
            claim={"text": "三月全体活动人数为 12 人。", "valid_time": _dim("value", "2026-03")},
            expected_assertions={
                "block:mar": {"numeric_value": _dim("value", "12"), "valid_time": _dim("value", "2026-03")},
                "block:apr": {"numeric_value": _dim("value", "15"), "valid_time": _dim("value", "2026-04")},
            },
            expected_source_conflict="none",
            expected_four_state="still_valid",
            rationale="有效时间不相交。四月不进入三月结论的活动集，不形成 Source Conflict。时间写在原文里供 L3 读取；R0 仍不把时间写入注册表。",
        ),
        _case(
            case_id="T12-a",
            core_id="T12",
            source_documents=[{"doc_id": "doc-t12a", "text": "同一预算的两个月份。"}],
            revisions=[{"revision_id": "rev-t12a", "parent_revision_id": "", "role": "current"}],
            evidence_anchors=["block:mar-b", "block:apr-b"],
            anchors=[
                _anchor("block:mar-b", "rev-t12a", "2026年3月差旅预算为 8000 元。", "sec_1"),
                _anchor("block:apr-b", "rev-t12a", "2026年4月差旅预算为 9000 元。", "sec_1"),
            ],
            oracle={
                "block:mar-b": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True},
                "block:apr-b": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True},
            },
            claim={"text": "三月差旅预算为 8000 元。", "valid_time": _dim("value", "2026-03")},
            expected_assertions={
                "block:mar-b": {"numeric_value": _dim("value", "8000"), "valid_time": _dim("value", "2026-03")},
                "block:apr-b": {"numeric_value": _dim("value", "9000"), "valid_time": _dim("value", "2026-04")},
            },
            expected_source_conflict="none",
            expected_four_state="still_valid",
            rationale="同一事实身份但有效时间不相交。数值不同也不直接冲突。",
        ),
        _t13_a(),
        _t13_b(),
        _t13_c(),
        _t13_d(),
        _t13_e(),
        _t13_f(),
        _t13_hist(),
    ]


def _t13_a() -> dict[str, Any]:
    text_a = "建议将差旅预算调整为 8000 元。"
    text_b = "上述建议已经批准。"
    return _case(
        case_id="T13",
        subcase_id="T13-a",
        core_id="T13",
        source_documents=[{"doc_id": "doc-t13", "text": text_a + text_b}],
        revisions=[{"revision_id": "rev-t13", "parent_revision_id": "", "role": "current"}],
        evidence_anchors=["block:a1", "block:b1"],
        anchors=[
            _anchor("block:a1", "rev-t13", text_a, "sec_1"),
            _anchor("block:b1", "rev-t13", text_b, "sec_1", identity=False),
        ],
        oracle={
            "block:a1": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True},
            "block:b1": {"attribute_id": "", "grain_id": "", "has_subject": False, "has_scope": False},
        },
        claim={"text": "差旅预算已经批准为 8000 元。", "status": _dim("value", "approved"), "numeric_value": _dim("value", "8000")},
        expected_links=[{
            "role": "gold",
            "current_anchor": "block:b1",
            "current_text": text_b,
            "target_anchor": "block:a1",
            "link_type": "explicit_coreference",
            "basis_span": "上述",
            "basis_start": 0,
            "basis_end": 2,
            "structural_expectation": "accept",
            "semantic_gold": "accept",
        }],
        expected_update_relations=[{
            "relation": "updates_dimension",
            "via": "accepted_update",
            "requires_identity_link": True,
            "source_anchor": "block:b1",
            "current_text": text_b,
            "basis_span": "已经批准",
            "basis_start": 4,
            "basis_end": 8,
            "updated_dimensions": ["status"],
        }],
        expected_assertions={
            "block:a1": {"numeric_value": _dim("value", "8000"), "status": _dim("value", "suggested")},
            "block:b1": {"numeric_value": _dim("unmentioned"), "status": _dim("value", "approved")},
        },
        expected_source_conflict="none",
        expected_four_state="still_valid",
        rationale="B 只更新 status。A 的 8000 保留。身份链接本身不覆盖金额。",
    )


def _t13_b() -> dict[str, Any]:
    text_a = "建议将差旅预算调整为 8000 元。"
    text_c = "场地申请另案处理。"
    return _case(
        case_id="T13-b",
        core_id="T13",
        source_documents=[{"doc_id": "doc-t13b", "text": text_a + text_c}],
        revisions=[{"revision_id": "rev-t13b", "parent_revision_id": "", "role": "current"}],
        evidence_anchors=["block:a1", "block:c1"],
        anchors=[
            _anchor("block:a1", "rev-t13b", text_a, "sec_1"),
            _anchor("block:c1", "rev-t13b", text_c, "sec_1", identity=False),
        ],
        oracle={
            "block:a1": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True},
            "block:c1": {"attribute_id": "", "grain_id": "", "has_subject": False, "has_scope": False},
        },
        claim={"text": "差旅预算已经批准为 8000 元。"},
        expected_links=[{
            "role": "gold",
            "current_anchor": "block:c1",
            "current_text": text_c,
            "link_type": "abstain",
            "basis_span": "",
            "structural_expectation": "abstain",
            "semantic_gold": "reject",
        }],
        negative_proposals=[{
            "current_anchor": "block:c1",
            "current_text": text_c,
            "target_anchor": "block:a1",
            "link_type": "implicit_semantic_reference",
            "basis_span": "场地",
            "basis_start": 0,
            "basis_end": 2,
            "structural_expectation": "accept",
            "semantic_gold": "reject",
        }],
        expected_assertions={},
        expected_source_conflict="none",
        expected_four_state="paused",
        rationale="候选唯一，但当前句没有指向该预算。正确行为是弃权。真实但无关的片段即使位置正确，语义金标仍然拒绝。",
    )


def _t13_c() -> dict[str, Any]:
    text_b = "上述建议已经批准。"
    return _case(
        case_id="T13-c",
        core_id="T13",
        source_documents=[{"doc_id": "doc-t13c", "text": "父节有两笔预算。"}],
        revisions=[{"revision_id": "rev-t13c", "parent_revision_id": "", "role": "current"}],
        evidence_anchors=["block:a1", "block:a2", "block:b1"],
        anchors=[
            _anchor("block:a1", "rev-t13c", "建议将差旅预算调整为 8000 元。", "sec_1"),
            _anchor("block:a2", "rev-t13c", "建议将差旅预算调整为 9000 元。", "sec_1"),
            _anchor("block:b1", "rev-t13c", text_b, "sec_1", identity=False),
        ],
        oracle={
            "block:a1": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True},
            "block:a2": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True},
            "block:b1": {"attribute_id": "", "grain_id": "", "has_subject": False, "has_scope": False},
        },
        claim={"text": "差旅预算已经批准为 8000 元。"},
        expected_links=[{
            "role": "gold",
            "current_anchor": "block:b1",
            "current_text": text_b,
            "target_anchor": "block:a1",
            "link_type": "explicit_coreference",
            "basis_span": "上述",
            "basis_start": 0,
            "basis_end": 2,
            "structural_expectation": "reject",
            "semantic_gold": "reject",
        }],
        expected_assertions={},
        expected_source_conflict="none",
        expected_four_state="paused",
        rationale="多个可链接候选。句中有“上述”也不放宽唯一性。",
    )


def _t13_d() -> dict[str, Any]:
    text_b = "上述建议已经批准。"
    return _case(
        case_id="T13-d",
        core_id="T13",
        source_documents=[{"doc_id": "doc-t13d", "text": text_b}],
        revisions=[{"revision_id": "rev-t13d", "parent_revision_id": "", "role": "current"}],
        evidence_anchors=["block:a1", "block:b1"],
        anchors=[
            _anchor("block:a1", "rev-t13d", "建议将差旅预算调整为 8000 元。", "sec_1"),
            _anchor("block:b1", "rev-t13d", text_b, "sec_1", identity=False),
        ],
        oracle={
            "block:a1": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True},
            "block:b1": {"attribute_id": "", "grain_id": "", "has_subject": False, "has_scope": False},
        },
        claim={"text": "差旅预算已经批准为 8000 元。"},
        expected_links=[{
            "role": "proposal",
            "current_anchor": "block:b1",
            "current_text": text_b,
            "target_anchor": "block:a1",
            "link_type": "explicit_coreference",
            "basis_span": "并不存在",
            "basis_start": 0,
            "basis_end": 4,
            "structural_expectation": "reject",
            "semantic_gold": "reject",
        }],
        expected_assertions={},
        expected_source_conflict="none",
        expected_four_state="paused",
        rationale="依据片段不在当前原文中，结构门拒绝。",
    )


def _t13_e() -> dict[str, Any]:
    text_b = "上述建议已经批准。"
    return _case(
        case_id="T13-e",
        core_id="T13",
        source_documents=[{"doc_id": "doc-t13e", "text": text_b}],
        revisions=[{"revision_id": "rev-t13e", "parent_revision_id": "", "role": "current"}],
        evidence_anchors=["block:a1", "block:b1"],
        anchors=[
            _anchor("block:a1", "rev-t13e", "建议将差旅预算调整为 8000 元。", "sec_1"),
            _anchor("block:b1", "rev-t13e", text_b, "sec_1", identity=False),
        ],
        oracle={
            "block:a1": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True},
            "block:b1": {"attribute_id": "", "grain_id": "", "has_subject": False, "has_scope": False},
        },
        claim={"text": "差旅预算已经批准为 8000 元。"},
        expected_links=[{
            "role": "proposal",
            "current_anchor": "block:b1",
            "current_text": text_b,
            "target_anchor": "block:a1",
            "link_type": "explicit_coreference",
            "basis_span": "上述",
            "basis_start": 0,
            "basis_end": 3,
            "structural_expectation": "reject",
            "semantic_gold": "reject",
        }],
        expected_assertions={},
        expected_source_conflict="none",
        expected_four_state="paused",
        rationale="片段文字是“上述”，但终点多出一个字，切片与片段不一致。",
    )


def _t13_f() -> dict[str, Any]:
    text_b = "经费申请已核准。"
    return _case(
        case_id="T13-f",
        core_id="T13",
        source_documents=[{"doc_id": "doc-t13f", "text": text_b}],
        revisions=[{"revision_id": "rev-t13f", "parent_revision_id": "", "role": "current"}],
        evidence_anchors=["block:a1", "block:b1"],
        anchors=[
            _anchor("block:a1", "rev-t13f", "建议将差旅预算调整为 8000 元。", "sec_1"),
            _anchor("block:b1", "rev-t13f", text_b, "sec_1", identity=False),
        ],
        oracle={
            "block:a1": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True},
            "block:b1": {"attribute_id": "", "grain_id": "", "has_subject": False, "has_scope": False},
        },
        claim={"text": "差旅预算已经批准为 8000 元。", "status_note": "核准在 C3 为 unparsable；C4 是否等于 approved 只由人工金标判断"},
        expected_links=[{
            "role": "proposal",
            "current_anchor": "block:b1",
            "current_text": text_b,
            "target_anchor": "block:a1",
            "link_type": "implicit_semantic_reference",
            "basis_span": "经费申请",
            "basis_start": 0,
            "basis_end": 4,
            "structural_expectation": "accept",
            "semantic_gold": "requires_human",
        }],
        expected_assertions={"block:b1": {"status_c3": _dim("unparsable")}},
        expected_source_conflict="none",
        expected_four_state="withheld_pending_human_link_gold",
        rationale="没有显式词。结构门可以因位置和唯一性通过，但语义是否成立只与人工链接金标比较。不把这句写成已经证实的模型能力。",
    )


def _t13_hist() -> dict[str, Any]:
    text_c = "上述建议曾经获得批准。"
    return _case(
        case_id="T13-hist",
        core_id="T13",
        source_documents=[{"doc_id": "doc-t13h", "text": text_c}],
        revisions=[{"revision_id": "rev-t13h", "parent_revision_id": "", "role": "current"}],
        evidence_anchors=["block:a1", "block:c1"],
        anchors=[
            _anchor("block:a1", "rev-t13h", "建议将差旅预算调整为 8000 元。", "sec_1"),
            _anchor("block:c1", "rev-t13h", text_c, "sec_1", identity=False),
        ],
        oracle={
            "block:a1": {"attribute_id": "budget_amount", "grain_id": "grain_travel", "has_subject": True, "has_scope": True},
            "block:c1": {"attribute_id": "", "grain_id": "", "has_subject": False, "has_scope": False},
        },
        claim={"text": "差旅预算当前已经批准为 8000 元。"},
        expected_links=[{
            "role": "gold",
            "current_anchor": "block:c1",
            "current_text": text_c,
            "target_anchor": "block:a1",
            "link_type": "explicit_coreference",
            "basis_span": "上述",
            "basis_start": 0,
            "basis_end": 2,
            "structural_expectation": "accept",
            "semantic_gold": "identity_only",
        }],
        expected_update_relations=[{
            "relation": "unknown",
            "via": "historical_mention",
            "requires_identity_link": True,
            "source_anchor": "block:c1",
            "current_text": text_c,
            "basis_span": "曾经获得批准",
            "basis_start": 4,
            "basis_end": 10,
            "updated_dimensions": [],
        }],
        expected_assertions={
            "block:a1": {"numeric_value": _dim("value", "8000"), "status": _dim("value", "suggested")},
        },
        expected_source_conflict="none",
        expected_four_state="paused",
        rationale="“曾经获得批准”可以讨论身份，但不能把历史状态自动当成当前状态，也不能让 A 的金额或建议状态退出。",
    )


def _oracle_key(anchor: dict[str, Any], case: dict[str, Any]) -> str:
    revisions = {item["revision_id"] for item in case["anchors"]}
    anchor_ids = [item["evidence_anchor"] for item in case["anchors"]]
    if len(revisions) > 1 and anchor_ids.count(anchor["evidence_anchor"]) > 1:
        return f"{anchor['revision_id']}/{anchor['evidence_anchor']}"
    return anchor["evidence_anchor"]


def materialize_suite() -> dict[str, Any]:
    cases = []
    for case in _definitions():
        registry = build_registry(case["anchors"], vault_key=EXAMPLE_VAULT_KEY, for_real_data=False)
        by_key = {}
        for anchor in case["anchors"]:
            matched = [
                item for item in registry["candidates"]
                if item["evidence_anchor"] == anchor["evidence_anchor"]
            ]
            # 同一锚点号跨修订时，用 candidate 消息中的 revision 无法从候选反推。
            # 候选不含 revision_id。跨修订用例的 oracle 在导出时按输入顺序另行绑定。
            by_key.setdefault(anchor["evidence_anchor"], []).append(anchor)
        bound = _bind_cross_revision(case, registry)
        case = dict(case)
        case["expected_registry"] = registry
        case["registry_binding"] = bound
        _fill_target_ids(case, registry)
        cases.append(case)
    return {
        "schema": "yin-dun.fixture_suite.v1",
        "authority": "隐盾_第三阶段核心研究方案最终冻结版_v2.md",
        "vault_key_notice": "夹具使用 example-only-not-for-real-data。该密钥不得用于真实数据，也没有写入产品配置。",
        "not_implemented": ["L1", "L2", "L3", "L4", "C3", "C4", "product_pause", "product_precheck"],
        "core_four_state": CORE_FOUR_STATE,
        "cases": cases,
    }


def _bind_cross_revision(case: dict[str, Any], registry: dict[str, Any]) -> list[dict[str, str]]:
    """把 oracle 键绑定到候选。同一锚点号的不同修订靠重新计算候选编号区分。"""
    from experiments.third_stage.registry import build_candidate
    from experiments.third_stage.keys import vault_key_bytes

    key = vault_key_bytes(EXAMPLE_VAULT_KEY, for_real_data=False)
    binding = []
    for anchor in case["anchors"]:
        candidate = build_candidate(anchor, key=key)
        binding.append({
            "oracle_key": _oracle_key(anchor, case),
            "candidate_id": candidate["candidate_id"],
            "evidence_anchor": candidate["evidence_anchor"],
            "revision_id": anchor["revision_id"],
        })
    known = {item["candidate_id"] for item in registry["candidates"]}
    if {item["candidate_id"] for item in binding} != known:
        raise RuntimeError(f"{case['case_id']} 的候选绑定与注册表不一致")
    return binding


def _fill_target_ids(case: dict[str, Any], registry: dict[str, Any]) -> None:
    by_anchor: dict[str, list[dict[str, str]]] = {}
    revision_of = {item["candidate_id"]: item["revision_id"] for item in case.get("registry_binding", [])}
    for candidate in registry["candidates"]:
        by_anchor.setdefault(candidate["evidence_anchor"], []).append(candidate)
    for proposal in list(case["expected_links"]) + list(case["negative_proposals"]):
        target_anchor = proposal.get("target_anchor")
        if not target_anchor:
            continue
        choices = by_anchor.get(target_anchor, [])
        current_revision = ""
        for anchor in case["anchors"]:
            if anchor["evidence_anchor"] == proposal.get("current_anchor"):
                current_revision = anchor["revision_id"]
                break
        same_revision = [
            item for item in choices
            if revision_of.get(item["candidate_id"]) == current_revision
        ] if current_revision else choices
        chosen = same_revision or choices
        if len(chosen) != 1:
            raise RuntimeError(f"{case['case_id']} 无法唯一绑定目标 {target_anchor}")
        proposal["target_candidate_id"] = chosen[0]["candidate_id"]
