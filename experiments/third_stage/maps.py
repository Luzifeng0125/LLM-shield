"""冻结的结构映射。

这些表只服务 R0 的身份槽位。它们不是 C3 状态词表，也不读取披露结论。
中心词零次或多次命中时不猜测属性。
"""
from __future__ import annotations

# 长词在匹配时优先。短词若完全落在已命中的长词内部，不再另计。
ATTRIBUTE_HEADWORDS = (
    ("参加人数", "participant_count"),
    ("活动人数", "participant_count"),
    ("差旅预算", "budget_amount"),
    ("截止日期", "deadline"),
    ("活动时间", "event_time"),
    ("公开事实", "public_fact"),
    ("负责人", "person_role"),
    ("人数", "participant_count"),
    ("预算", "budget_amount"),
    ("地点", "location"),
    ("事项", "task_item"),
    ("期限", "deadline"),
)

# 精确表面形式。多个不同口径同时出现则留空。
GRAIN_SURFACES = (
    ("不含工作人员", "grain_excluding_staff"),
    ("全体", "grain_all"),
    ("差旅", "grain_travel"),
)

CLOSED_GRAIN_IDS = frozenset(grain_id for _, grain_id in GRAIN_SURFACES)
GRAIN_BY_SURFACE = {surface: grain_id for surface, grain_id in GRAIN_SURFACES}

# 表格列标识或表头到属性。不一致时不猜测。
COLUMN_TO_ATTRIBUTE = {
    "participant_count": "participant_count",
    "budget_amount": "budget_amount",
    "location": "location",
    "人数": "participant_count",
    "预算金额": "budget_amount",
    "地点": "location",
}

# 父节标题到范围。只接受整段标题相等，不在正文里搜索。
SECTION_SCOPES = {
    "春季招新": ("activity", "spring-recruit"),
}

EXPLICIT_COREFERENCE = ("上述", "该预算", "此项")

FORBIDDEN_KEYS = frozenset({
    "disclosure",
    "disclosure_text",
    "claim",
    "claim_text",
    "claim_assertion",
    "gold",
    "gold_label",
    "four_state",
    "four_state_gold",
    "link_gold",
    "c3",
    "c4",
    "c3_output",
    "c4_output",
    "model_output",
    "numeric_value",
    "unit",
    "status",
    "polarity",
    "valid_time",
    "amount",
})
