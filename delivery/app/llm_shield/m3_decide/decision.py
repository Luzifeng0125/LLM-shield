"""模型直接选择处理动作；安全检查只能放行或暂停，不能替模型重选。"""
from __future__ import annotations

import inspect
import math
from collections.abc import Mapping
from numbers import Real
from typing import Callable, Dict, List, Optional

from ..config import rules
from ..schema import Action, Decision, HardCheck, Segment
from .constraints import action_applicable, check_hard


def _model_scores(scorer, seg, task_key, recipient_key, **context):
    """兼容原有三参数注入函数；推理异常不会触发第二次调用或规则兜底。"""
    parameters = inspect.signature(scorer).parameters
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD
                         for p in parameters.values())
    kwargs = {k: v for k, v in context.items()
              if accepts_kwargs or k in parameters}
    return scorer(seg, task_key, recipient_key, **kwargs)


def _validated_scores(raw) -> Dict[str, float]:
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError("模型未返回动作概率")
    scores = {}
    for key, value in raw.items():
        action = key.value if isinstance(key, Action) else key
        if not isinstance(action, str) or action not in Action._value2member_map_:
            raise ValueError("模型返回未知动作类别")
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("模型概率不是数值")
        value = float(value)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("模型概率必须为有限的 0 到 1 数值")
        scores[action] = value
    if not math.isclose(sum(scores.values()), 1.0, rel_tol=1e-5, abs_tol=1e-6):
        raise ValueError("模型概率之和不为 1")
    return scores


def decide_segment(
    seg: Segment,
    task_key: str,
    recipient_key: str,
    identity_key: str,
    necessity_scorer: Optional[Callable[..., Dict[str, float]]] = None,
    *,
    task_description: str = "",
    context: str = "",
) -> Decision:
    """唯一最高模型概率决定动作；缺失、无效或被安全检查拒绝则暂停。"""
    cats = sorted({s.category for s in seg.spans})
    if not seg.spans:
        return Decision(seg.seg_id, Action.RETAIN, [],
                        reason="该段未识别出敏感片段，原样通过")
    if any(cat not in rules().get("categories", {}) for cat in cats):
        return Decision(seg.seg_id, Action.PAUSE, cats,
                        reason="存在未知敏感类别，暂停外发")
    if necessity_scorer is None:
        return Decision(seg.seg_id, Action.PAUSE, cats,
                        reason="未提供动作模型，暂停外发")
    try:
        scores = _validated_scores(_model_scores(
            necessity_scorer, seg, task_key, recipient_key,
            identity_key=identity_key, task_description=task_description,
            context=context))
    except Exception as exc:
        # 不记录异常正文：外部模型异常可能包含输入材料。
        return Decision(seg.seg_id, Action.PAUSE, cats,
                        reason=f"动作模型不可用或输出无效（{type(exc).__name__}），暂停外发")

    best_score = max(scores.values())
    winners = [a for a, p in scores.items()
               if math.isclose(p, best_score, rel_tol=0.0, abs_tol=1e-12)]
    if len(winners) != 1:
        return Decision(seg.seg_id, Action.PAUSE, cats,
                        reason="模型最高概率并列，无法确定唯一动作，暂停外发",
                        necessity_scores=scores)
    chosen = Action(winners[0])
    if chosen == Action.PAUSE:
        return Decision(seg.seg_id, chosen, cats,
                        reason="模型选择暂停外发", necessity_scores=scores)

    try:
        checks = [HardCheck("ACTION_APPLICABLE",
                            action_applicable(chosen, seg, task_key),
                            f"模型选择的 {chosen.value} 是否可执行")]
        checks += check_hard(chosen, seg, task_key, recipient_key, identity_key)
    except Exception as exc:
        return Decision(seg.seg_id, Action.PAUSE, cats,
                        reason=f"模型动作的安全检查失败（{type(exc).__name__}），暂停外发",
                        necessity_scores=scores)
    failed = [c.rule for c in checks if not c.passed]
    if failed:
        return Decision(seg.seg_id, Action.PAUSE, cats,
                        reason=f"模型选择 {chosen.value}，安全检查拒绝：{', '.join(failed)}；暂停外发",
                        hard_checks=checks, necessity_scores=scores)
    return Decision(seg.seg_id, chosen, cats,
                    reason=f"模型选择 {chosen.value}（概率 {best_score:.3f}），安全检查通过",
                    hard_checks=checks, necessity_scores=scores)


def decide_all(
    segments: List[Segment],
    task_key: str,
    recipient_key: str,
    identity_key: str,
    necessity_scorer: Optional[Callable[..., Dict[str, float]]] = None,
    *,
    task_description: str = "",
    context: str = "",
) -> List[Decision]:
    return [decide_segment(seg, task_key, recipient_key, identity_key,
                           necessity_scorer, task_description=task_description,
                           context=context) for seg in segments]
