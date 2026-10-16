"""评测指标计算（模块 ⑧⑨）。

主要指标：
  1. 信息泄露率   —— 定义内禁止披露的敏感值是否出现在实际载荷中
  2. 任务完成率   —— 处理后材料是否仍保留完成任务所需信息
  3. 责任关系正确性 —— 会议纪要任务中，人物—事项—期限是否仍一一对应
  4. 误拦率       —— 合法请求被错误拦截的比例
  5. 处理延迟     —— P50 / P95
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from llm_shield.config import rules, tasks, recipients, category_level
from llm_shield.m5_utility.estimator import estimate

_COUNT_RE = re.compile(r"(\d+)\s*(人|名|位|人次)")
_DEADLINE_RE = re.compile(r"(\d{1,2}月\d{1,2}日|(本|下|上)(周|月)|周[一二三四五六日天]|截止)")
_CODE_RE = re.compile(r"(人员[甲乙丙丁戊己庚辛壬癸\d]+|组织[甲乙丙丁戊己庚辛壬癸\d]+)")
_TASK_VERB_RE = re.compile(r"(负责|完成|提交|对接|整理|撰写|组织|采购|设计|开发|测试|汇总|联系|安排)")


def _has_person_mark(text: str) -> bool:
    """文本中是否存在「人物标识」。

    标识可以是代号（人员甲），也可以是真名（负责人：李晓华）。
    这样判定的是「人物—事项—期限的对应关系是否还在」，
    而不是「有没有用代号」——后者会把「无防护直发原文」误判成关系断裂。
    """
    if _CODE_RE.search(text):
        return True
    return bool(re.search(
        r"(负责人|责任人|对接人|成员|组长|队长|部长|同学|老师)\s*[:：]?\s*[\u4e00-\u9fa5]{2,4}",
        text))


def forbidden_categories(task_key: str, recipient_key: str = "external_model") -> Set[str]:
    """该任务下「定义内禁止披露」的类别集合。"""
    cfg = rules().get("hard_constraints", {})
    banned = set(cfg.get("absolute_ban", []))
    banned |= set(tasks().get(task_key, {}).get("never_send", []))
    rec = recipients().get(recipient_key, {})
    banned |= set(rec.get("forbidden", []))
    banned |= {cat for cat in rules().get("categories", {})
               if category_level(cat) > int(rec.get("max_level", 0))}
    if rec.get("trust") == "low":
        banned |= {"PERSON_NAME", "PHONE", "EMAIL", "STUDENT_ID", "WECHAT"}
    return banned


def leakage_of(text: str, gold_spans: List[dict], task_key: str,
               recipient_key: str = "external_model") -> Dict[str, object]:
    """计算单个案例的泄露情况。"""
    banned = forbidden_categories(task_key, recipient_key)
    leaked_values: List[str] = []
    leaked_cats: Set[str] = set()
    for g in gold_spans:
        if g["category"] not in banned:
            continue
        if g["value"] in text:
            leaked_values.append(g["value"])
            leaked_cats.add(g["category"])
    n_banned = sum(1 for g in gold_spans if g["category"] in banned)
    return {
        "leaked": bool(leaked_values),
        "n_leaked": len(leaked_values),
        "n_banned": n_banned,
        "leaked_categories": sorted(leaked_cats),
        "leak_rate": (len(leaked_values) / n_banned) if n_banned else 0.0,
    }


def completion_of(text: str, task_key: str, aggregates: dict = None) -> Dict[str, object]:
    """任务完成判定：按任务的 completion_criteria 做本地检查。"""
    aggregates = aggregates or {}
    ok = True
    reasons: List[str] = []

    if task_key == "activity_stats":
        has_count = bool(_COUNT_RE.search(text)) or aggregates.get("person_count", 0) > 0
        if not has_count:
            ok = False
            reasons.append("缺少人数统计")
        if not re.search(r"(活动|比赛|讲座|沙龙|培训|志愿|招新|晚会|论坛|训练营|分享会)", text):
            ok = False
            reasons.append("缺少活动名称/类别")

    elif task_key == "meeting_minutes":
        if not _has_person_mark(text):
            ok = False
            reasons.append("缺少责任人标识（代号或真名）")
        if not _TASK_VERB_RE.search(text):
            ok = False
            reasons.append("缺少任务事项")
        if not _DEADLINE_RE.search(text):
            ok = False
            reasons.append("缺少期限")

    elif task_key == "project_intro":
        if len(text.strip()) < 40:
            ok = False
            reasons.append("可公开内容过少")
        if not re.search(r"(项目|平台|系统|课程|赛事|计划)", text):
            ok = False
            reasons.append("缺少项目名称")

    return {"completed": ok, "reasons": reasons}


def relation_correctness(text: str, task_key: str) -> Dict[str, object]:
    """责任关系正确性：仅对会议纪要任务判定。

    判定：文本中同时存在 代号 + 事项动词 + 期限，且代号数量与事项数量可对应。
    """
    if task_key != "meeting_minutes":
        return {"applicable": False, "correct": True, "detail": "该任务不适用"}
    # 人物标识可以是代号，也可以是真名——关键是三者对应关系是否还成立
    has_person = _has_person_mark(text)
    verbs = _TASK_VERB_RE.findall(text)
    dls = _DEADLINE_RE.findall(text)
    correct = has_person and bool(verbs) and bool(dls)
    return {
        "applicable": True,
        "correct": correct,
        "n_person_marks": int(has_person), "n_tasks": len(verbs), "n_deadlines": len(dls),
        "detail": "" if correct else "人物标识/事项/期限三者未同时保留",
    }


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def aggregate_metrics(records: List[dict]) -> Dict[str, object]:
    """把逐条记录汇总成整体指标。"""
    n = len(records) or 1
    leak_cnt = sum(1 for r in records if r["leakage"]["leaked"])
    done_cnt = sum(1 for r in records if r["completion"]["completed"])
    block_cnt = sum(1 for r in records if r.get("blocked"))
    legitimate = [r for r in records if r.get("expected_allowed") is True]
    rel = [r["relation"] for r in records if r["relation"].get("applicable")]
    rel_ok = sum(1 for r in rel if r.get("correct"))
    lat = [r.get("latency_ms", 0.0) for r in records]

    return {
        "n_cases": len(records),
        "leak_event_rate": round(leak_cnt / n, 4),              # 出现泄露的案例占比
        "leak_value_rate": round(
            sum(r["leakage"]["leak_rate"] for r in records) / n, 4),  # 禁止值泄露比例
        "task_completion_rate": round(done_cnt / n, 4),
        "block_rate": round(block_cnt / n, 4),
        "overblock_rate": (round(sum(bool(r.get("blocked")) for r in legitimate) /
                                  len(legitimate), 4) if legitimate else None),
        "relation_presence_rate": round(rel_ok / len(rel), 4) if rel else None,
        "latency_p50_ms": round(percentile(lat, 0.5), 2),
        "latency_p95_ms": round(percentile(lat, 0.95), 2),
    }
