"""模块 ⑧ 三边界观测：以「实际载荷」判断受限信息是否到达无权方。

三个边界：
  边界1 B1_MODEL_INPUT   —— 发送给模型的请求
  边界2 B2_VIEW_DISPLAY  —— 展示给用户的结果
  边界3 B3_TOOL_EGRESS   —— 提交给工具接收端的内容

判定方式（两种互补，取并集）：
  1) 值级：原始材料中被判定为敏感的「值」是否原样出现在载荷里（最可靠）
  2) 类别级：对载荷重新跑一遍识别器，检查是否残留接收方禁止的类别
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from ..config import category_level, identities, recipients, rules, tasks
from ..m3_decide.constraints import DIRECT_IDENTIFIERS
from ..m2_detect.pipeline import detect_all
from ..schema import Span


def check_value_leakage(payload: str, original_spans: List[Span],
                        allowed_values: Optional[Set[str]] = None,
                        *, recipient_key: Optional[str] = None,
                        task_key: Optional[str] = None,
                        identity_key: Optional[str] = None) -> List[dict]:
    """值级泄露检测：原始敏感值是否原样出现在待发送内容中。"""
    allowed = allowed_values or set()
    hits: List[dict] = []
    seen = set()
    for s in original_spans:
        value = s.text.strip()
        key = (value, s.category)
        if not value or key in seen:
            continue
        # 允许保留只证明模型选择了 RETAIN，不能覆盖当前边界的访问限制。
        restricted = (_restriction(s.category, recipient_key, task_key, identity_key)
                      if recipient_key else "")
        if value in allowed and recipient_key and not restricted:
            continue
        if value in payload:
            seen.add(key)
            hits.append({
                "type": "VALUE", "category": s.category,
                "value_masked": _mask(value),
                "position": payload.find(value),
                "reason": restricted or "原始敏感值未经当前边界授权保留",
            })
    return hits


# 已区间化的聚合金额是合法的本地统计输出，不是原始敏感值。
# 架构原文：「统计类任务：本地汇总，只发必要统计结果」——
# 若不剔除，形如「1万~2万元」的汇总会被识别成 BUDGET，
# 进而把整条合规请求误判成泄露并拦掉。
_AGG_SAFE_RE = re.compile(
    r"\d+\s*万\s*~\s*\d+\s*万?元|\d+\s*~\s*\d+\s*元|1000元以下")

# Only server-generated codes from the current session may suppress a model's
# category false positive. User text that merely looks like a code is untrusted.
_CODE_RE = re.compile(r"(?:人员|组织)(?:[甲乙丙丁戊己庚辛壬癸]|[0-9]+)")


def _generated_code_ranges(payload: str, generated_pseudonyms: Optional[Set[str]]):
    ranges = []
    for code in generated_pseudonyms or set():
        if not isinstance(code, str) or not _CODE_RE.fullmatch(code):
            continue
        category = "PERSON_NAME" if code.startswith("人员") else "ORG"
        for match in re.finditer(re.escape(code) + r"(?![0-9甲乙丙丁戊己庚辛壬癸])", payload):
            ranges.append((match.start(), match.end(), category))
    return ranges


def _restriction(category: str, recipient_key: str,
                 task_key: Optional[str] = None,
                 identity_key: Optional[str] = None) -> str:
    """原始类别的披露限制，同时用于原值匹配和重新识别，白名单不参与。"""
    rec = recipients().get(recipient_key)
    if not isinstance(rec, dict):
        return "未知接收方（默认策略 deny）"
    if category not in rules().get("categories", {}):
        return "未知敏感类别（默认策略 deny）"
    if category in rules().get("hard_constraints", {}).get("absolute_ban", []):
        return f"全局禁止外发 {category}"
    if task_key is not None:
        task = tasks().get(task_key)
        if not isinstance(task, dict):
            return "未知任务（默认策略 deny）"
        if category in task.get("never_send", []):
            return f"当前任务禁止外发 {category}"
    if category in rec.get("forbidden", []):
        return f"当前接收方禁止接收 {category}"
    if rec.get("trust") == "low" and category in DIRECT_IDENTIFIERS:
        return f"低信任接收方禁止直接标识符原值 {category}"
    max_level = int(rec.get("max_level", 1))
    if identity_key is not None:
        ident = identities().get(identity_key)
        if not isinstance(ident, dict):
            return "未知身份（默认策略 deny）"
        max_level = min(max_level, int(ident.get("max_level", 1)))
    if category_level(category) > max_level:
        return f"敏感级别 L{category_level(category)} 超过披露上限 L{max_level}"
    return ""


def check_category_leakage(payload: str, recipient_key: str,
                           *, task_key: Optional[str] = None,
                           identity_key: Optional[str] = None,
                           generated_pseudonyms: Optional[Set[str]] = None,
                           placeholders: Optional[Set[str]] = None) -> List[dict]:
    """类别级泄露检测：对载荷重新识别，看是否残留接收方禁止的类别。"""
    if not payload:
        return []

    # 已有聚合区间可豁免接收方的精确金额限制，但不能绕过任务禁止预算项。
    task = tasks().get(task_key, {}) if task_key is not None else {}
    budget_banned = (isinstance(task, dict) and "BUDGET" in task.get("never_send", []))
    scanned = (payload if budget_banned else
               _AGG_SAFE_RE.sub(lambda match: " " * len(match.group(0)), payload))

    hits: List[dict] = []
    code_ranges = _generated_code_ranges(payload, set(generated_pseudonyms or ()) | set(placeholders or ()))
    for s in detect_all(scanned):
        if any(category == s.category and start <= s.start < s.end <= end
               for start, end, category in code_ranges):
            continue
        reason = _restriction(s.category, recipient_key, task_key, identity_key)
        if reason:
            hits.append({
                "type": "CATEGORY", "category": s.category,
                "value_masked": _mask(s.text),
                "position": s.start, "length": s.end - s.start,
                "reason": reason,
            })
    return hits


def _mask(value: str) -> str:
    """审计输出一律掩码，绝不把敏感原文写进日志。"""
    if len(value) <= 2:
        return "*" * len(value)
    return value[0] + "*" * (len(value) - 2) + value[-1]


def inspect_payload(payload: str, recipient_key: str,
                    original_spans: List[Span] = None,
                    allowed_values: Optional[Set[str]] = None,
                    *, task_key: Optional[str] = None,
                    identity_key: Optional[str] = None,
                    generated_pseudonyms: Optional[Set[str]] = None,
                    placeholders: Optional[Set[str]] = None) -> Dict[str, object]:
    """综合判定一个载荷是否发生泄露。"""
    original_spans = original_spans or []
    invalid_context = (
        not isinstance(recipients().get(recipient_key), dict)
        or (task_key is not None and not isinstance(tasks().get(task_key), dict))
        or (identity_key is not None and not isinstance(identities().get(identity_key), dict))
    )
    if invalid_context:
        hits = [{"type": "POLICY", "category": "UNKNOWN_CONTEXT",
                 "reason": "未知任务、身份或接收方（默认策略 deny）"}]
    else:
        hits = check_value_leakage(
            payload, original_spans, allowed_values, recipient_key=recipient_key,
            task_key=task_key, identity_key=identity_key)
        hits += check_category_leakage(payload, recipient_key, task_key=task_key,
                                       identity_key=identity_key,
                                       generated_pseudonyms=set(generated_pseudonyms or ()) | set(placeholders or ()))
    categories = sorted({h["category"] for h in hits})
    return {
        "leaked": bool(hits),
        "leaked_categories": categories,
        "leak_hits": hits,
        "n_hits": len(hits),
    }
