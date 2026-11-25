"""C3 规则提取。证据通道和结论通道共用同一套词表，但每次只看一段文本。

这里不读取另一通道的文本，也不输出 supports 或 contradicts。
「核准」保持 unparsable，不加入可映射词表。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from experiments.third_stage.links import l2_text
from experiments.third_stage.maps import ATTRIBUTE_HEADWORDS, GRAIN_SURFACES
from experiments.third_stage.registry import _table_attribute, _table_grain, _unique_attribute, _unique_grain

STATUS_REQUIRED = frozenset({"task_item", "budget_amount"})
QUANTITY_ATTRIBUTES = frozenset({"participant_count", "budget_amount"})

# 长词优先。未获批准一类不能映射到唯一业务状态。
STATUS_PHRASES: tuple[tuple[str, str, str | None], ...] = (
    ("尚未批准", "value", "not_yet_approved"),
    ("还未批准", "value", "not_yet_approved"),
    ("未获批准", "unparsable", None),
    ("没有批准", "unparsable", None),
    ("正在审批", "value", "pending"),
    ("等待审批", "value", "pending"),
    ("已经批准", "value", "approved"),
    ("尚未达到", "polarity", "neg"),
    ("没有达到", "polarity", "neg"),
    ("还未达到", "polarity", "neg"),
    ("未达到", "polarity", "neg"),
    ("已否决", "value", "rejected"),
    ("已驳回", "value", "rejected"),
    ("已完成", "value", "completed"),
    ("已落实", "value", "completed"),
    ("已同意", "value", "approved"),
    ("已批准", "value", "approved"),
    ("未批准", "unparsable", None),
    ("不超过", "polarity", "neg"),
    ("核准", "unparsable", None),
    ("建议", "value", "suggested"),
    ("考虑", "value", "suggested"),
    ("计划", "value", "planned"),
    ("准备", "value", "planned"),
    ("申请", "value", "requested"),
    ("提请", "value", "requested"),
    ("批准", "value", "approved"),
    ("通过", "value", "approved"),
    ("取消", "value", "cancelled"),
    ("不足", "polarity", "neg"),
    ("未满", "polarity", "neg"),
    ("拟", "value", "suggested"),
)

MONTHS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
}
HISTORICAL_MARKERS = ("曾经", "此前", "当时", "原先", "历史上")


def _dim(kind: str, value: str | None = None, rule_id: str = "", start: int | None = None, end: int | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"kind": kind, "rule_id": rule_id}
    if kind == "value":
        item["value"] = value or ""
    if start is not None and end is not None:
        item["start"] = start
        item["end"] = end
    return item


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        for index in range(start, end):
            chars[index] = " "
    return "".join(chars)


def _status_mention(text: str, phrase: str, index: int) -> bool:
    """指代后面的“建议”，以及“按计划”里的“计划”，不是状态谓词。"""
    if phrase == "建议" and text[max(0, index - 2):index] == "上述":
        return False
    if phrase == "计划" and index > 0 and text[index - 1] == "按":
        return False
    return True


def _find_phrases(text: str) -> list[tuple[int, int, str, str, str | None]]:
    occupied: list[tuple[int, int]] = []
    found = []
    for phrase, kind, value in STATUS_PHRASES:
        start = 0
        while True:
            index = text.find(phrase, start)
            if index < 0:
                break
            end = index + len(phrase)
            if any(not (end <= left or index >= right) for left, right in occupied):
                start = index + 1
                continue
            if kind != "polarity" and not _status_mention(text, phrase, index):
                start = end
                continue
            occupied.append((index, end))
            found.append((index, end, phrase, kind, value))
            start = end
    return found


def _dates(text: str) -> tuple[dict[str, Any], list[tuple[int, int]]]:
    matches: list[tuple[int, int, int | None, int]] = []
    for match in re.finditer(r"(\d{4})年(\d{1,2})月", text):
        matches.append((match.start(), match.end(), int(match.group(1)), int(match.group(2))))
    for match in re.finditer(r"(十二|十一|十|九|八|七|六|五|四|三|二|一)月", text):
        span = (match.start(), match.end())
        if any(not (span[1] <= left or span[0] >= right) for left, right, _, _ in matches):
            continue
        matches.append((span[0], span[1], None, MONTHS[match.group(1)]))
    if not matches:
        return _dim("unmentioned", rule_id="c3.time.absent"), []
    if len(matches) > 1:
        return _dim("unparsable", rule_id="c3.time.multiple"), [(item[0], item[1]) for item in matches]
    _, _, year, month = matches[0]
    token = f"{year:04d}-{month:02d}" if year else f"month:{month}"
    return _dim("value", token, "c3.time", matches[0][0], matches[0][1]), [(matches[0][0], matches[0][1])]


def _number(text: str, masked: str) -> dict[str, Any]:
    numbers = [(match.start(), match.end(), match.group(0)) for match in re.finditer(r"\d+", masked)]
    distinct = {value for _, _, value in numbers}
    if not distinct:
        return _dim("unmentioned", rule_id="c3.number.absent")
    if len(distinct) > 1:
        return _dim("unparsable", rule_id="c3.number.multiple")
    start, end, value = numbers[0]
    return _dim("value", str(int(value)), "c3.number", start, end)


def _unit(text: str) -> dict[str, Any]:
    """单位取紧挨数字的那一个，不取“人数”中心词里的“人”。"""
    match = re.search(r"\d+\s*(万元|元|人)", text)
    if not match:
        return _dim("unmentioned", rule_id="c3.unit.absent")
    unit = match.group(1)
    return _dim("value", unit, "c3.unit", match.end() - len(unit), match.end())


def _surface_span(text: str, surfaces: tuple[tuple[str, str], ...], target: str) -> tuple[int, int] | None:
    for surface, mapped in sorted(surfaces, key=lambda item: len(item[0]), reverse=True):
        if mapped != target or surface not in text:
            continue
        index = text.find(surface)
        return index, index + len(surface)
    return None


def _attribute(text: str, status: dict[str, Any]) -> dict[str, Any]:
    head = _unique_attribute(text)
    if head:
        span = _surface_span(text, ATTRIBUTE_HEADWORDS, head)
        if span:
            return _dim("value", head, "c3.attribute.headword", span[0], span[1])
        return _dim("value", head, "c3.attribute.headword")
    counted = re.search(r"\d+\s*人", text)
    if counted and "预算" not in text:
        return _dim("value", "participant_count", "c3.attribute.count_unit", counted.end() - 1, counted.end())
    if status.get("kind") == "value" and status.get("value") in {"planned", "completed"} and "完成" in text:
        index = text.find("完成")
        return _dim("value", "task_item", "c3.attribute.completion", index, index + 2)
    return _dim("unmentioned", rule_id="c3.attribute.absent")


def _status(found: list[tuple[int, int, str, str, str | None]], attribute: str) -> dict[str, Any]:
    statuses = [item for item in found if item[3] in {"value", "unparsable"}]
    if any(item[3] == "unparsable" for item in statuses):
        hit = next(item for item in statuses if item[3] == "unparsable")
        return _dim("unparsable", rule_id="c3.status.unparsable", start=hit[0], end=hit[1])
    values = {item[4] for item in statuses if item[3] == "value"}
    known = bool(attribute)
    if len(values) > 1:
        return _dim("unparsable", rule_id="c3.status.contradiction")
    if len(values) == 1:
        value = next(iter(values))
        span = next(item for item in statuses if item[4] == value)
        if known and attribute not in STATUS_REQUIRED:
            return _dim("not_applicable", rule_id="c3.status.not_required")
        return _dim("value", value, f"c3.status.{value}", span[0], span[1])
    if known and attribute not in STATUS_REQUIRED:
        return _dim("not_applicable", rule_id="c3.status.not_required")
    if known and attribute in STATUS_REQUIRED:
        return _dim("unmentioned", rule_id="c3.status.absent")
    return _dim("unmentioned", rule_id="c3.status.absent")


def _polarity(found: list[tuple[int, int, str, str, str | None]]) -> dict[str, Any]:
    negatives = [item for item in found if item[3] == "polarity"]
    if negatives:
        start, end, _, _, _ = negatives[0]
        return _dim("value", "neg", "c3.polarity.neg", start, end)
    return _dim("value", "affirm", "c3.polarity.affirm")


def extract_text(text: str) -> dict[str, Any]:
    """只根据这一段文本做规则提取。调用方不得把结论和证据拼进同一次调用。"""
    normalized = l2_text(text)
    found = _find_phrases(normalized)
    time_dim, date_spans = _dates(normalized)
    masked = _mask(normalized, date_spans)
    number = _number(normalized, masked)
    unit = _unit(normalized)
    polarity = _polarity(found)
    # 属性先用中心词和数量单位判断；完成类句子在状态词出现时落到事项。
    provisional = _status(found, "budget_amount")
    attribute = _attribute(normalized, provisional if provisional.get("kind") == "value" else {"kind": "unmentioned"})
    attribute_id = attribute.get("value", "") if attribute["kind"] == "value" else ""
    status = _status(found, attribute_id)
    grain_id = _unique_grain(normalized)
    grain_span = _surface_span(normalized, GRAIN_SURFACES, grain_id) if grain_id else None
    if grain_span:
        grain = _dim("value", grain_id, "c3.grain", grain_span[0], grain_span[1])
    elif grain_id:
        grain = _dim("value", grain_id, "c3.grain")
    else:
        grain = _dim("unmentioned", rule_id="c3.grain.absent")
    dimensions = {
        "subject": _dim("unmentioned", rule_id="c3.subject.absent"),
        "attribute": attribute,
        "context_scope": _dim("unmentioned", rule_id="c3.scope.absent"),
        "grain": grain,
        "numeric_value": number,
        "unit": unit,
        "valid_time": time_dim,
        "polarity": polarity,
        "status": status,
    }
    return {
        "text": normalized,
        "dimensions": dimensions,
        "historical": any(marker in normalized for marker in HISTORICAL_MARKERS),
        "quote_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    }


def apply_table(extraction: dict[str, Any], table: dict[str, Any] | None) -> dict[str, Any]:
    """表格的列和口径格属于这条证据本身，不从结论或其他单元格补值。"""
    if not table:
        return extraction
    attribute_id = _table_attribute(table)
    if attribute_id and extraction["dimensions"]["attribute"]["kind"] != "value":
        extraction["dimensions"]["attribute"] = _dim("value", attribute_id, "c3.attribute.table")
        extraction["dimensions"]["status"] = _status([], attribute_id)
    grain_id = _table_grain(table)
    if grain_id:
        extraction["dimensions"]["grain"] = _dim("value", grain_id, "c3.grain.table")
    unit = extraction["dimensions"]["unit"]
    header = str(table.get("header") or "")
    column = str(table.get("column_id") or "")
    if unit["kind"] != "value" and (header == "人数" or column == "participant_count"):
        extraction["dimensions"]["unit"] = _dim("value", "人", "c3.unit.table")
    if unit["kind"] != "value" and (header == "预算金额" or column == "budget_amount"):
        extraction["dimensions"]["unit"] = _dim("value", "元", "c3.unit.table")
    return extraction


def locate(extraction: dict[str, Any], *, doc_id: str, revision_id: str, anchor: str) -> dict[str, Any]:
    spans = {}
    for name, item in extraction["dimensions"].items():
        if "start" in item:
            spans[name] = {
                "start": item["start"],
                "end": item["end"],
                "text": extraction["text"][item["start"]:item["end"]],
            }
    return {
        "doc_id": doc_id,
        "revision_id": revision_id,
        "anchor": anchor,
        "text": extraction["text"],
        "quote_sha256": extraction["quote_sha256"],
        "spans": spans,
    }
