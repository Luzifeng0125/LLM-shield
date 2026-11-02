"""模块 ⑤ 本地任务效用估计：预测处理后的材料是否缺少完成任务所需信息。

作用：在转换完成后做一次「任务还能不能完成」的本地自检，
把风险提示给用户（例：代号替换后负责人无法区分 → 提示可能影响责任对应关系）。
本模块只提示，不参与硬约束判定，也不得推翻决策结果。
"""
from __future__ import annotations

import re
import math
from numbers import Real
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
    """Local presence checks only, never an action or permission override."""
    aggregates = aggregates or {}
    decisions = decisions or []
    checks, warnings, notes = {}, [], []

    def check(key, passed, failure):
        checks[key] = {"status": "pass" if passed else "fail", "detail": "已找到对应信息" if passed else failure}
        if not passed:
            warnings.append(failure)

    if task_key == 'activity_stats':
        number = aggregates.get('person_count')
        valid_number = (isinstance(number, Real) and not isinstance(number, bool)
                        and math.isfinite(number) and number >= 0)
        check('COUNT', bool(_COUNT_RE.search(sanitized_text)) or valid_number,
              '未找到明确人数，请核对统计范围与口径；不能把缺失人数当成0。')
        check('EVENT_NAME', bool(re.search(r'(活动|比赛|讲座|沙龙|培训|志愿|招新|晚会|论坛)', sanitized_text)),
              '未识别到活动名称或类别，请补充已确认的活动主体。')
        notes.append('找到数字不代表口径正确；仍需区分记录数、人次和去重人数。')
    elif task_key == 'meeting_minutes':
        retained_name = any(d.action.value == 'RETAIN' and 'PERSON_NAME' in d.categories for d in decisions)
        codes = set(_CODE_RE.findall(sanitized_text))
        check('PERSON_ROLE', bool(codes) or retained_name,
              '未找到可区分的负责人标识，需核对任务责任关系。')
        check('TASK_ITEM', bool(_TASK_VERB_RE.search(sanitized_text)), '未识别到任务事项动作。')
        check('DEADLINE', bool(_DEADLINE_RE.search(sanitized_text)), '未找到明确期限，请补充已确认的时间约束。')
        if any(d.action.value == 'PSEUDONYMIZE' for d in decisions):
            notes.append('已采用会话内稳定代号；单一负责人可使用一个代号，仍需核对事项与期限是否对应。')
    elif task_key == 'project_intro':
        check('PUBLIC_FACT', len(sanitized_text.strip()) >= 30, '可用于介绍的内容过少，请核对是否缺少必要事实。')
        check('PROJECT_NAME', bool(re.search(r'(项目|平台|系统|课程|赛事|计划|活动)', sanitized_text)),
              '未识别到项目主体，请补充已确认的名称或类别。')
    elif task_key == 'activity_notice':
        check('PUBLIC_FACT', bool(sanitized_text.strip()), '请补充已确认的活动名称与通知事项，再整理通知。')
    else:
        checks['TASK'] = {'status':'not_applicable','detail':'该任务尚无本地完整性检查规则'}
        return {'completeness':None,'evaluated':False,'warnings':[], 'notes':['当前任务未评估完整性。'],
                'checks':checks,'task':task_key,'scope':'local_completeness_hint_not_human_utility'}
    completeness = sum(c['status'] == 'pass' for c in checks.values()) / len(checks)
    return {'completeness':round(completeness, 3),'evaluated':True,'warnings':warnings,
            'notes':notes,'checks':checks,'task':task_key,'scope':'local_completeness_hint_not_human_utility'}
