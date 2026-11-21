"""模块 ⑥ 本地聚合：统计在本地完成，只把汇总结果交给外部。"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List


def _money_to_float(text: str) -> float:
    """把「1.2万元」「350元」解析为元为单位的浮点数。"""
    m = re.search(r"([¥￥]?)\s*([\d.]+)\s*(万元|元|块)?", text)
    if not m:
        return 0.0
    val = float(m.group(2))
    unit = m.group(3)
    if unit == "万元":
        val *= 10000
    return val


def _band_amount(total: float) -> str:
    """金额区间化：12800 -> 「1万~2万元」，避免暴露精确预算。"""
    if total <= 0:
        return "未披露金额"
    if total < 1000:
        return "1000元以下"
    if total < 10000:
        lower = int(total // 1000 * 1000)
        return f"{lower}~{lower + 1000}元"
    lower_w = int(total // 10000)
    return f"{lower_w}万~{lower_w + 1}万元"


def aggregate(items: List[dict], task_key: str = "") -> Dict[str, Any]:
    """对一批待聚合实体做本地汇总。

    :param items: [{"category": "PERSON_NAME", "value": "张三", "column": "姓名"}, ...]
    :return: {"summary_text": ..., "counts": ..., "details": ...}
    """
    counts: Counter = Counter()
    people: List[str] = []
    amounts: List[float] = []
    orgs: List[str] = []

    for it in items:
        cat, val = it.get("category"), str(it.get("value", ""))
        counts[cat] += 1
        if cat == "PERSON_NAME" and val:
            people.append(val)
        elif cat == "BUDGET" and val:
            amounts.append(_money_to_float(val))
        elif cat == "ORG" and val:
            orgs.append(val)

    uniq_people = sorted(set(people))
    summary_bits: List[str] = []
    if people:
        summary_bits.append(f"涉及人员 {len(uniq_people)} 人（明细未上传）")
    if amounts:
        # 注意：sum(amounts) 已是 float，不能再套一层 sum
        summary_bits.append(f"金额合计约 {_band_amount(sum(amounts))}")
    if orgs:
        summary_bits.append(f"涉及组织 {len(set(orgs))} 个")
    for cat, n in counts.items():
        if cat not in ("PERSON_NAME", "BUDGET", "ORG"):
            summary_bits.append(f"{cat} 字段共 {n} 条（已本地屏蔽）")

    return {
        "summary_text": "；".join(summary_bits) if summary_bits else "无聚合结果",
        "counts": dict(counts),
        "person_count": len(uniq_people),
        "amount_band": _band_amount(sum(amounts)) if amounts else None,
        "org_count": len(set(orgs)),
    }
