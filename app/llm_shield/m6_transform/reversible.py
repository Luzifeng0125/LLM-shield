"""联系通知的可逆占位。

只处理最终阅读者确实需要、并且有权查看原文的姓名和电话。
其余敏感信息照旧删除。映射留在本地，恢复沿用 can_restore。
"""
from __future__ import annotations

import re
from typing import Dict, List, Sequence, Tuple

from ..config import category_level, recipients
from ..m1_access.identity import can_restore
from ..schema import Span
from .mapping import MappingTable

CONTACT_NOTICE_TASK = "contact_notice"
REVERSIBLE_CATEGORIES = ("PERSON_NAME", "PHONE")
_REMOVED_UNLESS_REVERSIBLE = {
    "PERSON_NAME", "PHONE", "EMAIL", "WECHAT", "STUDENT_ID", "ID_CARD",
    "BANK_CARD", "API_KEY", "DORM", "GRADE", "SENSITIVE_ATTR", "BUDGET",
}
_BROKEN_TOKEN = re.compile(r"\[(?:PERSON|CONTACT)_[^\]]*|(?<!\[)(?:PERSON|CONTACT)_\d+\]?")


def viewer_may_see_original(identity_key: str, viewer_key: str, category: str) -> bool:
    """最终阅读者能否看到这一类原文。外部模型不在此列。"""
    if not can_restore(identity_key, viewer_key):
        return False
    recipient = recipients().get(viewer_key) or {}
    if category in set(recipient.get("forbidden") or []):
        return False
    return category_level(category) <= int(recipient.get("max_level", 0))


def reversible_categories(identity_key: str, viewer_key: str) -> Tuple[str, ...]:
    return tuple(category for category in REVERSIBLE_CATEGORIES
                 if viewer_may_see_original(identity_key, viewer_key, category))


def mask_necessary(text: str, spans: Sequence[Span], session_id: str, mapping: MappingTable,
                   categories: Sequence[str]) -> Tuple[str, List[str]]:
    """把必要字段换成占位符，并把其余敏感片段从模型输入里删掉。"""
    allowed = set(categories)
    chosen = [span for span in spans if span.category in allowed]
    issued: List[str] = []
    tokens: Dict[int, str] = {}
    for span in sorted(chosen, key=lambda item: item.start):
        token = mapping.stable_token(session_id, span.text, span.category)
        if token:
            tokens[id(span)] = token
            if token not in issued:
                issued.append(token)
    pieces = sorted(
        [span for span in spans if span.category in _REMOVED_UNLESS_REVERSIBLE],
        key=lambda item: item.start,
        reverse=True,
    )
    out = text
    for span in pieces:
        token = tokens.get(id(span), "")
        out = out[:span.start] + token + out[span.end:]
    return out, issued


def assess_reply(reply: str, issued: Sequence[str], raw_values: Sequence[str]) -> Dict[str, object]:
    """占位符必须整段保留。丢失的不补回，损坏或夹带原文时不恢复。"""
    if any(value and value in reply for value in raw_values):
        return {"ok": False, "reason": "回复夹带原始敏感信息", "present": []}
    stripped = reply
    for code in sorted(issued, key=len, reverse=True):
        stripped = stripped.replace(code, "")
    if _BROKEN_TOKEN.search(stripped):
        return {"ok": False, "reason": "占位符已被破坏", "present": []}
    if not issued:
        return {"ok": True, "reason": "", "present": []}
    pattern = re.compile("|".join(re.escape(code) for code in sorted(issued, key=len, reverse=True)))
    found = pattern.findall(reply)
    seen: List[str] = []
    for code in found:
        if code not in seen:
            seen.append(code)
    expected = [code for code in issued if code in reply]
    if seen != expected:
        return {"ok": False, "reason": "占位符顺序与发出时不一致", "present": []}
    return {"ok": True, "reason": "", "present": expected}


def restore_reply(mapping: MappingTable, session_id: str, reply: str, *,
                  allowed: bool, issued: Sequence[str], raw_values: Sequence[str]) -> Tuple[str, Dict[str, object]]:
    """只恢复校验通过、且接收方有权查看的占位符。"""
    assessment = assess_reply(reply, issued, raw_values)
    if not allowed or not assessment["ok"]:
        return reply, assessment
    restored = reply
    present = list(assessment["present"])
    backward = mapping._backward.get(session_id, {})
    for code in sorted(present, key=len, reverse=True):
        original = backward.get(code)
        if original:
            restored = restored.replace(code, original)
    return restored, assessment
