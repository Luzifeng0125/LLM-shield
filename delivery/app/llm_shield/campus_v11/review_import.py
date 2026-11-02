"""接收校园复核返还。

用户有效返还默认按人工审核接收。缺少独立初答时仍接收，但标记为 AI 辅助，
不补造时间、复核人或盲审过程。测试池材料不能因此变成训练标签。
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Mapping, Optional

from ..schema import Action

SCHEMA = "campus-review-return-v1.1"
POLICY_VERSION = "campus-min-disclosure-v1.1"
TRAIN_ROLES = {"calibration"}
FRESH_ROLES = {"pilot", "N", "D", "C"}
ACTIONS = {action.value for action in Action}


class ImportError(ValueError):
    """返还文件不能按协议接收。"""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def import_return(
    payload: Mapping[str, Any],
    *,
    user_returned: bool,
    original_bytes: bytes,
    original_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """``user_returned`` 只记录调用方断言，函数本身不能证明文件来自真人。"""
    if not user_returned:
        raise ImportError("工具或 AI 自写文件不适用默认人审；只有用户返还的该轮结果才能导入")
    if payload.get("schema") != SCHEMA or payload.get("policy_version") != POLICY_VERSION:
        raise ImportError("返还文件的协议版本不符")
    role = payload.get("pack_role")
    if role not in TRAIN_ROLES | FRESH_ROLES:
        raise ImportError("未知材料池")
    digest = _sha256(original_bytes)
    if original_sha256 is not None and original_sha256 != digest:
        raise ImportError("原件哈希不符，不接收")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ImportError("返还文件没有题目")

    accepted = []
    incomplete = []
    for item in items:
        if not isinstance(item, Mapping) or not isinstance(item.get("decision_key"), str):
            raise ImportError("题目缺少 decision_key")
        final = item.get("final_answer")
        initial = item.get("initial_answer")
        action = None if not isinstance(final, Mapping) else final.get("canonical_action")
        record = {
            "decision_key": item["decision_key"],
            "initial_answer": initial if isinstance(initial, Mapping) else None,
            "final_answer": final if isinstance(final, Mapping) else None,
            "ai_suggestion_seen": item.get("ai_suggestion_seen") if isinstance(item.get("ai_suggestion_seen"), bool) else None,
            "reviewer": "not_recorded",
            "timestamps": "not_recorded",
        }
        if action not in ACTIONS:
            record["status"] = "incomplete"
            record["provenance"] = "not_received"
            record["train_eligible"] = False
            incomplete.append(record)
            continue
        if not isinstance(final, Mapping) or not str(final.get("required_facts") or "").strip():
            record["status"] = "incomplete"
            record["provenance"] = "not_received"
            record["train_eligible"] = False
            incomplete.append(record)
            continue
        independent = isinstance(initial, Mapping) and initial.get("canonical_action") in ACTIONS
        if independent:
            provenance = "human_initial_then_final"
        else:
            provenance = "human_assisted_not_independent"
        record.update({
            "status": "accepted",
            "provenance": provenance,
            "independent_first_answer": independent,
            "train_eligible": role in TRAIN_ROLES,
            "fresh_test_isolated": role in FRESH_ROLES,
        })
        accepted.append(record)
    return {
        "schema": "campus-review-import-v1.1",
        "policy_version": POLICY_VERSION,
        "pack_role": role,
        "provenance_basis": "caller_asserted_user_return",
        "original_sha256": digest,
        "accepted": accepted,
        "incomplete": incomplete,
        "train_keys": [item["decision_key"] for item in accepted if item["train_eligible"]],
        "fresh_keys_blocked_from_training": [item["decision_key"] for item in accepted if item.get("fresh_test_isolated")],
        "fabricated_review_metadata": False,
    }
