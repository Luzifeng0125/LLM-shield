"""Bound large uploaded tables before the local privacy and model pipeline.

Selection happens locally. The selected rows still pass through the same access,
detection, decision and egress checks as an ordinary chat turn.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import replace

from .m1_access.loader import flatten_material
from .schema import Material


_COUNT_PATTERNS = [
    re.compile(r"^(?:请|帮我|麻烦)?(?:统计|计算|查询|数一下)?(?:一下)?"
               r"(?P<value>[^，。？?]{1,40}?)(?P<field>专业|学院|校区)"
               r"(?:的)?(?:有|共有)?(?:多少|几)(?:个|名|位)?人[？?。]?$"),
    re.compile(r"^(?:请|帮我|麻烦)?(?:统计|计算|查询)?(?:一下)?"
               r"(?P<field>专业|学院|校区)(?:为|是|等于)"
               r"(?P<value>[^，。？?]{1,40}?)(?:的)?(?:有|共有)?"
               r"(?:多少|几)(?:个|名|位)?人[？?。]?$"),
]


def _normalized(value: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")))


def exact_count_for_chat(materials: list[Material], question: str) -> tuple[str, str] | None:
    """Answer a narrow category count from the entire authorized table locally.

    The caller checks access and the output boundary before returning the result.
    No row values or names are included in the answer or conversation history.
    """
    tables = [m for m in materials if m.rows is not None and m.columns]
    if len(tables) != 1:
        return None
    match = next((m for pattern in _COUNT_PATTERNS
                  if (m := pattern.fullmatch(question.strip()))), None)
    if match is None:
        return None
    table = tables[0]
    field = match.group("field")
    if field not in table.columns:
        return None
    value = match.group("value").strip(' \t“”"「」')
    target = _normalized(value)
    if not target:
        return None
    count = sum(_normalized(row.get(field, "")) == target for row in table.rows)
    if count == 0:
        return None
    safe_question = f"按{field}列统计{value}的人数（本机全表精确统计）"
    answer = (f"{value}{field}共有 {count} 人"
              f"（全表 {len(table.rows)} 条数据记录，不含表头；本机精确统计）。")
    return safe_question, answer


def _terms(question: str) -> set[str]:
    words = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]{2,}", question.lower())
    terms = {word for word in words if len(word) >= 2}
    for word in words:
        if re.search(r"[\u4e00-\u9fff]", word):
            terms.update(word[i:i + 2] for i in range(len(word) - 1))
    return terms - {"这份", "文件", "表格", "多少", "什么", "请问", "一下", "信息", "关于"}


def select_for_chat(materials: list[Material], question: str,
                    *, max_chars: int = 24000) -> list[Material]:
    """Keep a bounded, question-relevant excerpt and state its coverage."""
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
