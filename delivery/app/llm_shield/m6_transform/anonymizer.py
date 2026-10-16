"""模块 ⑥ 信息转换：按决策结果执行 删除 / 本地聚合 / 泛化 / 代号替换 / 受控保留。

关键点：
- 转换完全在本地完成，原文不落盘、不进日志；
- 代号来自会话隔离的映射表（m6_transform.mapping），同一会话内稳定；
- 本地聚合只把汇总结果带出去，明细留在本机。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..config import rules
from ..m3_decide.constraints import GENERALIZABLE
from ..schema import Action, Decision, Segment, Span
from .aggregate import aggregate, _band_amount, _money_to_float
from .mapping import get_table

# 日期泛化：精确到日 -> 精确到月
_DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?")
_DATE_CN_RE = re.compile(r"(\d{1,2})月(\d{1,2})日")

# 泛化替换表
GENERIC_VALUES = {
    "PERSON_NAME": "某同学",
    "ORG": "某学生组织",
    "LOCATION": "校内某场所",
    "DORM": "校内宿舍",
    "GRADE": "成绩已泛化",
    "STUDENT_ID": "学号已隐藏",
    "PHONE": "***********",
    "EMAIL": "***@***",
    "WECHAT": "***",
}

# 删除后仅剩这些字符则视为空壳，整段丢弃
_RESIDUAL_CHARS = "，。；：、,;: \t\n「」（）()【】"

# 删除敏感值后留下的空标签，如「主办：。」「手机号：」——一并清掉，
# 否则脱敏文本会充满无意义空壳，可读性很差。
_EMPTY_LABEL_RE = re.compile(
    r"[\u4e00-\u9fa5A-Za-z0-9]{1,8}\s*[:：]\s*(?=[。；;\n，,]|$)")


def _drop_empty_labels(text: str) -> str:
    """反复清理「标签：」后无内容的结构，直到稳定。"""
    for _ in range(4):
        new = _EMPTY_LABEL_RE.sub("", text)
        if new == text:
            break
        text = new
    # 合并因清理产生的连续分隔符
    text = re.sub(r"[；;]\s*[；;]+", "；", text)
    text = re.sub(r"[，,]\s*[，,]+", "，", text)
    text = re.sub(r"；\s*(?=\n|$)", "", text)
    return text


def _generalize_value(span: Span) -> str:
    """按类别生成泛化后的值。金额做区间化，其余用通用占位。"""
    if span.category == "BUDGET":
        return _band_amount(_money_to_float(span.text))
    return GENERIC_VALUES.get(span.category, "已泛化")


def _clean_residual(text: str) -> str:
    """删除敏感片段后清理空标签与残留标点。

    例：「主办：校团委志愿服务中心。」→「主办：。」→「」
    """
    text = _drop_empty_labels(text)
    return "" if text.strip(_RESIDUAL_CHARS) == "" else text


def process_segment(
    seg: Segment,
    decision: Decision,
    session_id: str,
    agg_items: List[dict],
    mapping=None,
) -> str:
    """把单个决策单元转换为可外发文本。"""
    mapping = mapping or get_table()
    cfg = rules()
    pseudo = cfg.get("pseudonym", {})
    prefix_pool = pseudo.get("prefix_pool", list("甲乙丙丁戊己庚辛壬癸"))
    templates = {"person": pseudo.get("person_template", "人员{code}"),
                 "org": pseudo.get("org_template", "组织{code}")}

    text = seg.text
    spans = sorted(seg.spans, key=lambda s: s.start)

    # ---- 暂停外发 ----
    if decision.action == Action.PAUSE:
        return ""

    # ---- 受控保留：原样输出 ----
    if decision.action == Action.RETAIN:
        return text

    # ---- 本地聚合：收集明细后删除，只留汇总（汇总由上层附加）----
    if decision.action == Action.LOCAL_AGGREGATE:
        for s in spans:
            agg_items.append({"category": s.category, "value": s.text, "column": s.column})
        out = text
        for s in reversed(spans):
            a, b = s.start - seg.start, s.end - seg.start
            out = out[:a] + out[b:]
        return _clean_residual(out)

    # ---- 泛化：先按原坐标替换实体，再降低日期粒度，避免坐标位移 ----
    # 注意：不可泛化的类别（如证件号）在此处直接删除，
    # 与 constraints.disclosed_categories() 的判定保持一致。
    if decision.action == Action.GENERALIZE:
        out = text
        for s in reversed(spans):
            a, b = s.start - seg.start, s.end - seg.start
            if s.category in GENERALIZABLE:
                out = out[:a] + _generalize_value(s) + out[b:]
            else:
                out = out[:a] + out[b:]
        out = _DATE_RE.sub(lambda m: f"{m.group(1)}年{int(m.group(2))}月", out)
        out = _DATE_CN_RE.sub(lambda m: f"{int(m.group(1))}月", out)
        return _clean_residual(out)

    # ---- 代号替换：可代号化的替换，其余按删除处理 ----
    if decision.action == Action.PSEUDONYMIZE:
        out = text
        for s in reversed(spans):
            a, b = s.start - seg.start, s.end - seg.start
            if s.category in ("PERSON_NAME", "ORG"):
                code = mapping.get_or_create(session_id, s.text, s.category,
                                             prefix_pool, templates)
                out = out[:a] + code + out[b:]
            else:
                out = out[:a] + out[b:]
        return _clean_residual(out)

    # ---- 删除 ----
    out = text
    for s in reversed(spans):
        a, b = s.start - seg.start, s.end - seg.start
        out = out[:a] + out[b:]
    return _clean_residual(out)


def apply_decisions(
    text: str,
    segments: List[Segment],
    decisions: List[Decision],
    session_id: str,
    mapping=None,
) -> Dict[str, Any]:
    """把全部决策应用到原文，返回转换结果。"""
    mapping = mapping or get_table()
    agg_items: List[dict] = []
    paused_segments: List[str] = []
    pause_reason = ""

    parts: List[str] = []
    for seg, dec in zip(segments, decisions):
        if dec.action == Action.PAUSE:
            paused_segments.append(seg.seg_id)
            if not pause_reason:
                pause_reason = dec.reason
            continue
        parts.append(process_segment(seg, dec, session_id, agg_items, mapping))

    sanitized = "".join(parts)
    # 压掉连续空行
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized).strip()

    # 本地聚合结果（只发汇总）
    agg_result = aggregate(agg_items) if agg_items else {}
    if agg_result:
        block = "\n\n【本地聚合结果（明细未上传）】\n" + agg_result["summary_text"]
        sanitized = sanitized + block

    return {
        "sanitized_text": sanitized,
        "aggregates": agg_result,
        "aggregate_items": len(agg_items),
        "mapping": mapping.export(session_id),
        "paused_segments": paused_segments,
        "pause_reason": pause_reason,
        "paused": bool(paused_segments),
    }
