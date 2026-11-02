"""把精确金额收成任务需要的量级。解析不到数字时不编造。"""
from __future__ import annotations

import re
from typing import Optional

_MONEY = re.compile(r"([¥￥])?\s*(\d+(?:\.\d+)?)\s*(万元|元|块)?")


def parse_yuan(text: str) -> Optional[float]:
    if not isinstance(text, str) or not text.strip():
        return None
    match = _MONEY.search(text)
    if match is None:
        return None
    value = float(match.group(2))
    if match.group(3) == "万元":
        value *= 10000
    if value <= 0:
        return None
    return value


def magnitude_phrase(text: str) -> Optional[str]:
    """12800 元收成「约一万元」。原文没有数字时返回空，不估算。"""
    value = parse_yuan(text)
    if value is None:
        return None
    if value < 100:
        return "不足百元"
    if value < 1000:
        return "数百元"
    if value < 10000:
        return "数千元"
    if value < 20000:
        return "约一万元"
    if value < 100000:
        return "约数万元"
    if value < 200000:
        return "约十万元"
    return "约数十万元"


def amount_precision(user_task: str) -> str:
    """只看用户任务里的明确说法，不看标注员写的必要事实。"""
    if not isinstance(user_task, str) or not user_task.strip():
        return "unspecified"
    if any(token in user_task for token in ("精确", "核算", "到分", "原样金额")):
        return "exact"
    if any(token in user_task for token in ("大概", "大致", "量级", "什么水平", "粗略")):
        return "magnitude"
    return "unspecified"
