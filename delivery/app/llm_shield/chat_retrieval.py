"""Bound large uploaded tables before the local privacy and model pipeline.

Selection happens locally. The selected rows still pass through the same access,
detection, decision and egress checks as an ordinary chat turn.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import replace

from . import config as C
from .m1_access.loader import flatten_material
from .m2_detect.entity_rules import COLUMN_CATEGORY_HINTS
from .schema import Material


_COUNT_PATTERNS = [
    re.compile(r"^(?:请|帮我|麻烦)?(?:统计|计算(?!机)|查询|数一下)?(?:一下)?"
               r"(?P<value>[^，。？?]{1,40}?)(?P<field>专业|学院|校区)"
               r"(?:的)?(?:有|共有)?(?:多少|几)(?:个|名|位)?人[？?。]?$"),
    re.compile(r"^(?:请|帮我|麻烦)?(?:统计|计算|查询)?(?:一下)?"
               r"(?P<field>专业|学院|校区)(?:为|是|等于)"
               r"(?P<value>[^，。？?]{1,40}?)(?:的)?(?:有|共有)?"
               r"(?:多少|几)(?:个|名|位)?人[？?。]?$"),
]


def _normalized(value: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value if value is not None else "")))


def exact_count_for_chat(materials: list[Material], question: str) -> tuple[str, str] | None:
    """Answer a narrow category count from the entire authorized table locally.

    The caller checks access and the output boundary before returning the result.
    No row values or names are included in the answer or conversation history.
    """
    tables = [m for m in materials if m.rows is not None and m.columns]
    if not tables:
        return None
    match = next((m for pattern in _COUNT_PATTERNS
                  if (m := pattern.fullmatch(question.strip()))), None)
    if match is None:
        return None
    if len(tables) != 1:
        return '本机分类统计请求', '当前包含多张表，尚未确定合并及去重口径；请先选择一张表，不能据此确认人数。'
    table = tables[0]
    field = match.group("field")
    matching_columns = [c for c in table.columns if _normalized(c) == field]
    if len(matching_columns) != 1:
        return '本机分类统计请求', '统计字段缺失或无法唯一对应，请先核对表头；当前不能据此确认人数。'
    column = matching_columns[0]
    value = match.group("value").strip(' \t“”"「」')
    target = _normalized(value)
    if not target:
        return None
    if any(not isinstance(row, dict) for row in table.rows):
        return '本机分类统计请求', '记录结构不一致，请先核对表格；当前不能据此确认人数。'
    count = sum(_normalized(row.get(column, "")) == target for row in table.rows)
    safe_question = f"按{field}列统计{value}的匹配记录（本机全表精确统计）"
    answer = (f"{value}{field}匹配 {count} 条记录"
              f"（全表 {len(table.rows)} 条数据记录，不含表头；按记录计数，未按身份去重，"
              "未确认一行一人，不能据此确认人数）。")
    return safe_question, answer


def _terms(question: str) -> set[str]:
    words = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]{2,}", question.lower())
    terms = {word for word in words if len(word) >= 2}
    for word in words:
        if re.search(r"[\u4e00-\u9fff]", word):
            terms.update(word[i:i + 2] for i in range(len(word) - 1))
    return terms - {"这份", "文件", "表格", "多少", "什么", "请问", "一下", "信息", "关于"}


_METADATA_QUERY = re.compile(
    r"(?:请|帮我)?(?:概述|介绍|查看|列出|告诉我|看看)?(?:一下)?"
    r"(?:这份|这个|本|该)?(?:文件|表格|材料|表)(?:里|中)?(?:有|包含)?"
    r"(?:哪些|什么)(?:字段|列名|列|表头|信息)[。？?！!]*")


def project_fields(material: Material, question: str, *, task_key: str = "",
                   task_description: str = "") -> Material:
    """Project explicit fields and hard-forbidden columns before row retrieval.

    This is a data boundary, not a replacement policy for model-selected actions.
    Ambiguous semantic requests retain their columns for ordinary model analysis.
    """
    if material.rows is None or not material.columns:
        return material
    columns = list(material.columns)
    if _METADATA_QUERY.fullmatch(question.strip()):
        return replace(material, text=f"【表格字段：{'、'.join(columns)}；数据记录共 {len(material.rows)} 行（不含表头）。本次未读取行明细。】",
                       rows=[], columns=columns)
    selected = columns
    explicit_projection = False
    request = task_description + "\n" + question
    matches = list(re.finditer(r"只(?:需要?|保留|查看|提取|输出|列出)\s*([^。！？?!\n]+)", request))
    for match in matches:
        expression = re.sub(r"(?:这些)?(?:字段|列)(?:即可|就行)?$|(?:即可|就行)$", "", match[1].strip())
        names = [part.strip(' “\"”「」') for part in re.split(r"[、,，]|以及|和|与|及", expression)]
        if names and all(name in columns for name in names):
            selected = [column for column in columns if column in names]
            explicit_projection = True
            break
    if task_key:
        forbidden = (set(C.rules().get("hard_constraints", {}).get("absolute_ban", []))
                     | set(C.tasks().get(task_key, {}).get("never_send", []))
                     | set(C.recipients().get("external_model", {}).get("forbidden", [])))
        hints = {_normalized(key).lower(): value for key, value in COLUMN_CATEGORY_HINTS.items()}
        selected = [column for column in selected
                    if hints.get(_normalized(column).lower()) not in forbidden]
    if selected == columns and not explicit_projection:
        return material
    note = f"【本轮仅处理表格字段：{'、'.join(selected) or '无'}；未使用其他列或附带正文。】"
    return replace(material, text=note, columns=selected,
                   rows=[{column: row.get(column, "") for column in selected} for row in material.rows])


def select_for_chat(materials: list[Material], question: str,
                    *, max_chars: int = 24000, task_key: str = "",
                    task_description: str = "") -> list[Material]:
    """Keep a bounded, question-relevant excerpt and state its coverage."""
    materials = [project_fields(m, question, task_key=task_key, task_description=task_description)
                 for m in materials]
    if (sum(len(flatten_material(m)) for m in materials) <= max_chars
            and all(not m.rows or (len(m.rows) <= 30 and len(flatten_material(m)) <= 6000)
                    for m in materials)):
        return materials
    tables = [m for m in materials if m.rows and m.columns]
    if not tables:
        return materials
    budget = max(1500, (max_chars - len(question) - 1000) // len(tables))
    terms = _terms(question)
    selected: list[Material] = []
    for material in materials:
        if (not material.rows or not material.columns
                or (len(material.rows) <= 30 and len(flatten_material(material)) <= min(budget, 6000))):
            selected.append(material)
            continue
        columns = material.columns
        ranked = []
        for index, row in enumerate(material.rows):
            content = "；".join(f"{col}: {value}" for col in columns
                               if (value := str(row.get(col, "") or "").strip()))
            value_text = " ".join(str(row.get(col, "")) for col in columns).lower()
            score = sum(len(term) ** 2 for term in terms if term in value_text)
            ranked.append((index, content, score))
        ranked.sort(key=lambda item: (-item[2], item[0]))
        header = (f"【表格检索片段：数据记录共 {len(material.rows)} 行（不含表头）；"
                  f"字段：{'、'.join(str(col) for col in columns)}。"
                  "以下仅为匹配问题的部分行；没有匹配时不附明细。"
                  "不得把片段当作全表，也不得据此推断全表统计。】\n")
        available = max(0, budget - len(material.title) - len(header) - len(material.text))
        chosen = []
        used = 0
        for index, content, score in ranked:
            if score <= 0 or len(chosen) >= 5:
                break
            cost = len(content) + 1
            if used + cost <= available:
                chosen.append(index)
                used += cost
        chosen.sort()
        selected.append(replace(material, text=header + material.text,
                                rows=[material.rows[i] for i in chosen]))
    return selected
