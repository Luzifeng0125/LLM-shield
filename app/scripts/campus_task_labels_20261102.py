"""可执行监督标签。只供离线训练和诊断，不参与在线决策。

历史人工标签不在这里改写。训练目标是：任务需要的动作若能通过现有硬约束就选它，
不能安全完成就暂停。用户原话决定需要哪一种动作，不要求用户写出字段级方案。
"""
from __future__ import annotations

from llm_shield.config import campus_workflows, recipients
from llm_shield.m3_decide.constraints import feasible_actions
from llm_shield.schema import Action, Segment, Span

FAMILIES = (
    "plain",
    "duty_who",
    "place_only",
    "count_org",
    "money_exact",
    "money_magnitude",
    "money_drop",
    "grade_omit",
)

# 训练和留出各两句。诊断材料里的收据、发票、账单、原数字、原数、粗略印象不在这里。
ASKS = {
    "plain": {
        "train": "按这项任务整理成可发送的文本。",
        "valid": "按原有任务处理成待发送稿。",
    },
    "duty_who": {
        "train": "写清谁负责哪一项。",
        "valid": "写清谁承担哪一项。",
    },
    "place_only": {
        "train": "把集合地点写具体。",
        "valid": "集合地点要写明。",
    },
    "count_org": {
        "train": "只统计人数，并保留机构名称。",
        "valid": "统计人数，并写上机构名称。",
    },
    "money_exact": {
        "train": "负责人与事项要对应，开支按精确数字原样保留。",
        "valid": "人员与事项要对应，费用按精确数字原样保留。",
    },
    "money_magnitude": {
        "train": "负责人与事项要对应，费用保留粗略量级。",
        "valid": "人员与事项要对应，开支保留粗略量级。",
    },
    "money_drop": {
        "train": "负责人与事项要对应，不要写入费用。",
        "valid": "人员与事项要对应，费用不要写入。",
    },
    "grade_omit": {
        "train": "整理补交提醒，不需要分数和学号。",
        "valid": "补交提醒不需要分数。",
    },
}

SPAN_TEXT = {
    "PERSON_NAME": "赵启明负责签到。",
    "PHONE": "联系电话13911110001。",
    "EMAIL": "邮箱zhao@example.edu。",
    "ORG": "主办方是读书会。",
    "LOCATION": "地点在文理楼。",
    "DORM": "住在梅园1号楼。",
    "BUDGET": "费用是8600元。",
    "GRADE": "成绩是76分。",
    "STUDENT_ID": "学号2024110001。",
    "ID_CARD": "证件110101199001011234。",
    "BANK_CARD": "卡号6222020000000000111。",
    "API_KEY": "密钥sk-test-aaaa。",
    "WECHAT": "微信wx_alpha。",
    "SENSITIVE_ATTR": "患有慢性胃病。",
}

TASKS = (
    "activity_notice",
    "activity_stats",
    "meeting_minutes",
    "project_intro",
    "class_coordination",
    "coursework_grades",
    "awards_financial_aid",
    "campus_services",
)
RECIPIENTS = ("external_model", "viewer_teacher", "viewer_peer", "egress_tool_public")
IDENTITIES = ("student_leader", "external_partner")

# 校准池历史动作保持原样。executable 只是本轮训练目标。c06 没有接收方，不进入训练。
CALIBRATION_LEDGER = (
    {"unit_id": "c01-u1", "family": "duty_who", "task_key": "class_coordination",
     "category": "PERSON_NAME", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "RETAIN", "executable": "PSEUDONYMIZE"},
    {"unit_id": "c01-u2", "family": "duty_who", "task_key": "class_coordination",
     "category": "PERSON_NAME", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "RETAIN", "executable": "PSEUDONYMIZE"},
    {"unit_id": "c01-u3", "family": "duty_who", "task_key": "class_coordination",
     "category": "LOCATION", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "DELETE", "executable": "DELETE"},
    {"unit_id": "c01-u4", "family": "duty_who", "task_key": "class_coordination",
     "category": "PHONE", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "DELETE", "executable": "DELETE"},
    {"unit_id": "c01-u5", "family": "duty_who", "task_key": "class_coordination",
     "category": "PERSON_NAME", "recipient_id": "viewer_teacher", "identity_key": "student_leader",
     "historical": "RETAIN", "executable": "RETAIN"},
    {"unit_id": "c02-u1", "family": "place_only", "task_key": "activity_notice",
     "category": "PERSON_NAME", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "DELETE", "executable": "DELETE"},
    {"unit_id": "c02-u2", "family": "place_only", "task_key": "activity_notice",
     "category": "LOCATION", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "RETAIN", "executable": "RETAIN"},
    {"unit_id": "c02-u3", "family": "place_only", "task_key": "activity_notice",
     "category": "EMAIL", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "DELETE", "executable": "DELETE"},
    {"unit_id": "c03-u1", "family": "count_org", "task_key": "activity_stats",
     "category": "PERSON_NAME", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "LOCAL_AGGREGATE", "executable": "LOCAL_AGGREGATE"},
    {"unit_id": "c03-u2", "family": "count_org", "task_key": "activity_stats",
     "category": "PERSON_NAME", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "LOCAL_AGGREGATE", "executable": "LOCAL_AGGREGATE"},
    {"unit_id": "c03-u3", "family": "count_org", "task_key": "activity_stats",
     "category": "ORG", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "RETAIN", "executable": "RETAIN"},
    {"unit_id": "c03-u4", "family": "count_org", "task_key": "activity_stats",
     "category": "PHONE", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "DELETE", "executable": "DELETE"},
    {"unit_id": "c04-u1", "family": "money_magnitude", "task_key": "meeting_minutes",
     "category": "PERSON_NAME", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "RETAIN", "executable": "PSEUDONYMIZE"},
    {"unit_id": "c04-u2", "family": "money_magnitude", "task_key": "meeting_minutes",
     "category": "PERSON_NAME", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "RETAIN", "executable": "PSEUDONYMIZE"},
    {"unit_id": "c04-u3", "family": "money_magnitude", "task_key": "meeting_minutes",
     "category": "BUDGET", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "GENERALIZE", "executable": "PAUSE"},
    {"unit_id": "c04-u4", "family": "money_magnitude", "task_key": "meeting_minutes",
     "category": "SENSITIVE_ATTR", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "DELETE", "executable": "DELETE"},
    {"unit_id": "c05-u1", "family": "plain", "task_key": "project_intro",
     "category": "PERSON_NAME", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "DELETE", "executable": "DELETE"},
    {"unit_id": "c05-u2", "family": "plain", "task_key": "project_intro",
     "category": "ORG", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "RETAIN", "executable": "RETAIN"},
    {"unit_id": "c05-u3", "family": "plain", "task_key": "project_intro",
     "category": "BUDGET", "recipient_id": "external_model", "identity_key": "student_leader",
     "historical": "DELETE", "executable": "DELETE"},
    {"unit_id": "c06-u1", "family": "", "task_key": "class_coordination",
     "category": "PERSON_NAME", "recipient_id": "", "identity_key": "student_leader",
     "historical": "DELETE", "executable": ""},
)


def boundary_of(recipient_key: str) -> str:
    rec = recipients().get(recipient_key)
    kind = rec.get("type") if isinstance(rec, dict) else ""
    return {
        "EXTERNAL_MODEL": "external_generation",
        "VIEWER": "authorized_local_delivery",
        "EGRESS_TOOL": "public_release",
    }.get(str(kind), "unknown")


def _needs(task_key: str) -> dict:
    workflows = campus_workflows().get("workflows", {})
    direct = workflows.get(task_key)
    if isinstance(direct, dict) and direct.get("needs"):
        return direct["needs"]
    for spec in workflows.values():
        if isinstance(spec, dict) and spec.get("reuses") == task_key and spec.get("needs"):
            return spec["needs"]
    return {}


def _segment(category: str) -> Segment:
    text = SPAN_TEXT[category]
    span = Span(0, len(text), text, category, 1.0, detector="task_supervision")
    return Segment("supervision", text, 0, len(text), [span], context=text)


def name_link_intent(recipient_key: str) -> str:
    rec = recipients().get(recipient_key)
    rec = rec if isinstance(rec, dict) else {}
    if rec.get("type") == "VIEWER" and rec.get("trust") == "high" and rec.get("can_restore"):
        return "raw"
    return "code"


def plain_intent(task_key: str, category: str, recipient_key: str) -> str:
    spec = _needs(task_key).get(category) or {}
    kind = spec.get("kind")
    required_on = spec.get("required_on") or []
    boundary = boundary_of(recipient_key)
    if required_on and boundary not in required_on:
        return "delete"
    if kind == "link_person":
        return name_link_intent(recipient_key)
    if kind == "aggregate_count":
        return "count"
    if kind == "public_fact":
        return "keep"
    if kind == "contact" and boundary == "authorized_local_delivery":
        return "raw"
    if kind in {"drop", "amount", "contact", None}:
        if task_key == "project_intro" and category in {"ORG", "LOCATION"}:
            return "keep"
        return "delete"
    return "delete"


def intent_for(family: str, task_key: str, category: str, recipient_key: str) -> str:
    if family == "plain":
        return plain_intent(task_key, category, recipient_key)
    if family == "duty_who":
        return name_link_intent(recipient_key) if category == "PERSON_NAME" else "delete"
    if family == "place_only":
        return "keep" if category == "LOCATION" else "delete"
    if family == "count_org":
        if category == "PERSON_NAME":
            return "count"
        if category == "ORG":
            return "keep"
        return "delete"
    if family in {"money_exact", "money_magnitude", "money_drop"}:
        if category == "BUDGET":
            return {"money_exact": "raw", "money_magnitude": "magnitude", "money_drop": "delete"}[family]
        if category == "PERSON_NAME":
            return name_link_intent(recipient_key)
        if category in {"LOCATION", "ORG"}:
            return "keep"
        return "delete"
    if family == "grade_omit":
        return name_link_intent(recipient_key) if category == "PERSON_NAME" else "delete"
    raise KeyError(family)


def executable_action(family: str, task_key: str, category: str,
                      recipient_key: str, identity_key: str) -> str:
    """需要的动作能通过硬约束就用它；不能安全完成则暂停。"""
    if category not in SPAN_TEXT:
        raise KeyError(category)
    intent = intent_for(family, task_key, category, recipient_key)
    feasible = {item.value for item in feasible_actions(
        _segment(category), task_key, recipient_key, identity_key)}
    preferred = {
        "delete": Action.DELETE.value,
        "raw": Action.RETAIN.value,
        "keep": Action.RETAIN.value,
        "code": Action.PSEUDONYMIZE.value,
        "magnitude": Action.GENERALIZE.value,
        "count": Action.LOCAL_AGGREGATE.value,
    }[intent]
    if preferred in feasible:
        return preferred
    return Action.PAUSE.value


def check_ledger() -> list[dict]:
    mismatches = []
    for row in CALIBRATION_LEDGER:
        if not row["recipient_id"]:
            continue
        got = executable_action(
            row["family"], row["task_key"], row["category"], row["recipient_id"], row["identity_key"])
        if got != row["executable"]:
            mismatches.append({**row, "got": got})
    return mismatches
