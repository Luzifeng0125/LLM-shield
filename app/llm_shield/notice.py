"""Local roster inspection and a separate, roster-free notice request.

No roster state, identifiers, or person codes are passed to the draft function.
These are two distinct API schemas, rather than a redaction of the same input.
"""
from __future__ import annotations

from collections import Counter

from .m1_access.identity import check_read
from .m2_detect.pipeline import detect_and_segment
from .schema import Material, ShieldRequest

NOTICE_TASK = "activity_notice"
NOTICE_ITEMS = {
    "check_in": "请按活动安排完成签到；具体时间、地点及方式以组织者后续通知为准。",
    "join_group": "请按组织者通过原有渠道提供的方式加入活动通知群，及时查看后续安排。",
    "verify_contact": "请通过原有私下渠道核对姓名、性别、学号、年级、专业和联系方式；如有变更请私下反馈，不要在公开群内发送个人资料。",
}


def review_roster(identity: str, text: str) -> dict:
    """Inspect locally; never instantiate a gateway or call a generation model."""
    material = Material("local-roster", "uploaded", "", text)
    access = check_read(identity, [material])
    if not access.ok:
        raise PermissionError("当前身份无权核对该材料")
    if not text.strip() or len(text) > 24000:
        raise ValueError("请输入不超过 24000 字符的名单")
    spans, _ = detect_and_segment(text)
    return {
        "ok": True, "local_only": True, "external_model_called": False,
        "spans": [span.to_dict() for span in spans],
        "counts": dict(Counter(span.category for span in spans)),
        "note": "识别结果仅供本机核对，不证明字段真实或人员对应关系正确。",
    }


def notice_brief(activity_name: str, items: list[str]) -> str:
    title = activity_name.strip()
    if not title or len(title) > 80 or any(ord(c) < 32 or c in "\u2028\u2029\x7f" for c in title):
        raise ValueError("活动名称须为 1–80 个字符的单行公开名称")
    if not items or len(items) > len(NOTICE_ITEMS) or any(item not in NOTICE_ITEMS for item in items):
        raise ValueError("请选择有效通知事项")
    if len(set(items)) != len(items):
        raise ValueError("通知事项不能重复")
    lines = ["活动名称：" + title, "通知事项："]
    lines += [NOTICE_ITEMS[key] for key in NOTICE_ITEMS if key in items]
    lines.append("尚未提供活动时间、地点、截止日期、群链接和联系人，请勿编造。")
    return "\n".join(lines)


def notice_request(identity: str, activity_name: str, items: list[str]) -> ShieldRequest:
    """The request contains public fields only; no roster parameter exists."""
    brief = notice_brief(activity_name, items)
    return ShieldRequest(
        "notice-draft", identity, NOTICE_TASK, "external_model",
        [Material("public-notice-brief", "uploaded", "", brief)],
        user_instruction="只生成面向参与者的通用通知，不列出个人、人员代号或统计明细。",
    )
