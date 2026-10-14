"""模块 ⑤ 本地任务效用估计：预测处理后的材料是否缺少完成任务所需信息。

作用：在转换完成后做一次「任务还能不能完成」的本地自检，
把风险提示给用户（例：代号替换后负责人无法区分 → 提示可能影响责任对应关系）。
本模块只提示，不参与硬约束判定，也不得推翻决策结果。
"""
from __future__ import annotations

import re
from typing import Dict, List

from ..config import tasks
from ..schema import Decision

# 人数相关表达
_COUNT_RE = re.compile(r"(\d+)\s*(人|名|位|人次|人参加|人参与)")
# 任务事项动词
_TASK_VERB_RE = re.compile(r"(负责|完成|提交|对接|整理|撰写|组织|采购|设计|开发|测试|汇总|联系|安排)")
# 期限表达
_DEADLINE_RE = re.compile(r"(\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2}|(本|下|上)(周|月)|周[一二三四五六日天]|截止)")
# 代号
_CODE_RE = re.compile(r"(人员[甲乙丙丁戊己庚辛壬癸]|组织[甲乙丙丁戊己庚辛壬癸]|人员\d+|组织\d+)")


def _check_activity_stats(text: str, agg: dict) -> List[str]:
    warns = []
    has_count = bool(_COUNT_RE.search(text)) or agg.get("person_count", 0) > 0
    if not has_count:
        warns.append("未找到人数统计信息，活动统计任务可能缺少关键指标（COUNT）")
    if not re.search(r"(活动|比赛|讲座|沙龙|培训|志愿|招新|晚会|论坛)", text):
        warns.append("未识别到活动名称/类别，总结文案可能缺少主体")
    return warns


def _check_meeting_minutes(text: str, agg: dict) -> List[str]:
    warns = []
    codes = set(_CODE_RE.findall(text))
    if not codes:
        warns.append("未找到任何人员代号，任务分派可能丢失责任人（PERSON_ROLE）")
    elif len(codes) == 1:
        warns.append("仅存在单一代号，多人场景下可能无法区分责任对应关系")
    if not _TASK_VERB_RE.search(text):
        warns.append("未识别到任务事项动作，纪要可能缺少可执行项（TASK_ITEM）")
    if not _DEADLINE_RE.search(text):
        warns.append("未保留期限表达，任务分派将缺少时间约束（DEADLINE）")
    return warns


def _check_project_intro(text: str, agg: dict) -> List[str]:
    warns = []
    if len(text.strip()) < 30:
        warns.append("可用于对外介绍的内容过少，可能过度删除已获准公开的事实")
    if not re.search(r"(项目|平台|系统|课程|赛事|计划|活动)", text):
        warns.append("未识别到项目名称，对外介绍缺少主体")
    return warns


_CHECKS = {
    "activity_stats": _check_activity_stats,
    "meeting_minutes": _check_meeting_minutes,
    "project_intro": _check_project_intro,
}


def estimate(sanitized_text: str, task_key: str, aggregates: dict = None,
             decisions: List[Decision] = None) -> Dict[str, object]:
    """返回 {"completeness": 0~1, "warnings": [...], "checks": {...}}"""
    aggregates = aggregates or {}
    warnings: List[str] = []
    fn = _CHECKS.get(task_key)
    if fn:
        warnings = fn(sanitized_text, aggregates)

    # 决策层面的风险提示
    decisions = decisions or []
    pseudo_count = sum(1 for d in decisions if d.action.value == "PSEUDONYMIZE")
    if pseudo_count and task_key == "meeting_minutes":
        # 检查是否存在「同一代号对应多个真实姓名」的歧义风险（由映射表保证不会，这里仅提示）
        warnings.append("已使用会话内稳定代号替换姓名，负责人/事项/期限的对应关系由本地映射表保持")

    total_checks = 3
    completeness = max(0.0, 1.0 - len(warnings) / total_checks)
    return {
        "completeness": round(completeness, 3),
        "warnings": warnings,
        "task": task_key,
    }
