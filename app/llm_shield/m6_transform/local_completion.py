"""会议纪要里，任务需要的金额量级只在本地保留。

任务必要性可以是泛化，当前外发边界仍然不能接收预算。
泛化短语不进入外部请求，也不进入映射表。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..campus_v11.magnitude import parse_yuan
from ..config import rules
from ..m2_detect.entity_rules import COMPOUND_SURNAMES, SENSITIVE_WORDS, SURNAMES, EntityDetector
from ..m3_decide.constraints import check_hard
from ..schema import Action, Segment, Span

_THOUSAND_ASK = ("千元这一档", "千元量级", "精确到千元", "到千元档", "千元档")
_CN = "零一二三四五六七八九"
_SURNAME = "[" + "".join(sorted(SURNAMES)) + "]"
_NAME = r"(?:" + "|".join(COMPOUND_SURNAMES) + r"|" + _SURNAME + r")[\u4e00-\u9fff]{1,2}"
_DUTY_NAME = re.compile(_NAME + r"(?=认领|负责)")
_HEALTH = re.compile(r"服用|降压药|" + "|".join(map(re.escape, SENSITIVE_WORDS)))
_SENTENCE = re.compile(r"[^。！？；\n]*[。！？；\n]?")


@dataclass
class MeetingBudgetPlan:
    blocked: bool
    reason: str = ""
    necessity_action: str = "GENERALIZE"
    boundary_action: str = "WITHHOLD"
    phrase: str = ""
    label: str = ""
    amount_texts: tuple = ()
    names: tuple = ()
    presented: bool = False
    external_text: str = ""
    held_locally: bool = False
    notes: list = field(default_factory=list)

    def record(self) -> dict:
        """给结果对象的动作记录。不包含金额原文和泛化短语。"""
        return {
            "necessity_action": self.necessity_action,
            "boundary_action": self.boundary_action,
            "held_locally": self.held_locally,
            "phrase_sent_to_model": False,
            "presented": self.presented,
            "blocked": self.blocked,
        }


def requests_thousand_magnitude(user_task: str) -> bool:
    return isinstance(user_task, str) and any(token in user_task for token in _THOUSAND_ASK)


def thousand_phrase(text: str) -> str | None:
    """6400 元收成「约六千元」。解析不到，或不在一千到九千元这一档时，不编造。"""
    value = parse_yuan(text)
    if value is None:
        return None
    thousands = int(value // 1000)
    if not 1 <= thousands <= 9:
        return None
    return f"约{_CN[thousands]}千元"


def boundary_allows_generalized_budget(identity: str, recipient: str, task: str) -> bool:
    """复用现有硬约束。泛化后的预算仍然是预算，禁止接收的边界不会放行。"""
    span = Span(0, 5, "6400元", "BUDGET", 1.0)
    segment = Segment("budget", "6400元", 0, 5, [span])
    checks = check_hard(Action.GENERALIZE, segment, task, recipient, identity)
    return bool(checks) and all(item.passed for item in checks)


def _fee_label(text: str, amount: str) -> str:
    index = text.find(amount)
    if index < 0:
        return "费用"
    prefix = text[max(0, index - 8):index]
    match = re.search(r"([\u4e00-\u9fff]{2,6})[是为：:]$", prefix)
    return match.group(1) if match else "费用"


def _duty_names(text: str) -> list[str]:
    found = []
    for match in _DUTY_NAME.finditer(text):
        name = match.group(0)
        if name in EntityDetector._PERSON_STOPWORDS or name in found:
            continue
        found.append(name)
    return found


def _code_names(text: str, names: list[str], session_id: str, mapping) -> str:
    pseudo = rules().get("pseudonym", {})
    pool = pseudo.get("prefix_pool", list("甲乙丙丁戊己庚辛壬癸"))
    templates = {"person": pseudo.get("person_template", "人员{code}")}
    replacements = [(name, mapping.get_or_create(session_id, name, "PERSON_NAME", pool, templates))
                    for name in names]
    for name, _code in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        text = text.replace(name, _code)
    return text


def _drop_health(text: str) -> str:
    pieces = []
    for match in _SENTENCE.finditer(text):
        sentence = match.group(0)
        if sentence and not _HEALTH.search(sentence):
            pieces.append(sentence)
    return "".join(pieces)


def _strip_amounts(text: str, amounts: tuple, phrase: str) -> str:
    for amount in sorted(amounts, key=len, reverse=True):
        text = text.replace(amount, "")
    if phrase:
        text = text.replace(phrase, "")
    text = re.sub(r"\d+\s*~\s*\d+\s*元", "", text)
    text = re.sub(r"[。]{2,}", "。", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def plan_meeting_budget(text: str, spans: list, user_task: str, task_key: str,
                        session_id: str, mapping) -> MeetingBudgetPlan | None:
    """只处理会议纪要里明确要求千元量级的金额。其它任务保持原流程。"""
    if task_key != "meeting_minutes" or not requests_thousand_magnitude(user_task):
        return None
    amounts = []
    for span in spans:
        if getattr(span, "category", "") == "BUDGET" and thousand_phrase(span.text):
            amounts.append(span.text)
    if not amounts:
        for match in re.finditer(r"[¥￥]?\s*\d+(?:\.\d+)?\s*(?:万元|元|块)", text or ""):
            raw = match.group(0).strip()
            if thousand_phrase(raw):
                amounts.append(raw)
    phrases = [thousand_phrase(amount) for amount in amounts]
    if not amounts or any(phrase is None for phrase in phrases):
        return MeetingBudgetPlan(
            True, "任务要求把金额交代到千元量级，但本地没有解析出可泛化的金额，不能删掉后宣称完成。")
    if len(set(phrases)) != 1:
        return MeetingBudgetPlan(True, "同一请求里有多档金额，本地补全无法确定该回填哪一档。")
    names = _duty_names(text)
    detected = [span.text for span in spans if getattr(span, "category", "") == "PERSON_NAME"]
    for name in detected:
        if name not in names:
            names.append(name)
    needs_people = isinstance(user_task, str) and ("对上" in user_task or "人员" in user_task)
    if needs_people and not names:
        return MeetingBudgetPlan(
            True, "任务要求人员和事项对应，现有文本里没有可代号化的人员，已暂停，避免把姓名原样交给外部模型。")
    return MeetingBudgetPlan(
        False, necessity_action="GENERALIZE", boundary_action="WITHHOLD",
        phrase=phrases[0], label=_fee_label(text, amounts[0]),
        amount_texts=tuple(dict.fromkeys(amounts)), names=tuple(names), held_locally=True)


def seal_external_text(plan: MeetingBudgetPlan, sanitized: str, session_id: str, mapping) -> MeetingBudgetPlan:
    """外部载荷只保留代号和事项。金额原文、泛化短语和映射表都不进入。"""
    if plan.blocked:
        return plan
    text = _code_names(sanitized, list(plan.names), session_id, mapping)
    text = _drop_health(text)
    text = _strip_amounts(text, plan.amount_texts, plan.phrase)
    leaked = [name for name in plan.names if name and name in text]
    leaked += [amount for amount in plan.amount_texts if amount and amount in text]
    if plan.phrase and plan.phrase in text:
        leaked.append(plan.phrase)
    if leaked or any(str(value) in text for value in mapping.export(session_id).values() if plan.phrase == value):
        plan.blocked = True
        plan.reason = "外部载荷仍含金额或未经代号化的人员，已暂停。"
        plan.external_text = ""
        return plan
    exported = " ".join(mapping.export(session_id).values())
    if plan.phrase and plan.phrase in exported:
        plan.blocked = True
        plan.reason = "泛化金额不能写入映射表。"
        plan.external_text = ""
        return plan
    plan.external_text = text
    return plan


def covers_budget_pause(plan: MeetingBudgetPlan, decisions: list, segments: list) -> bool:
    paused = [(decision, segment) for decision, segment in zip(decisions, segments)
              if decision.action == Action.PAUSE]
    if not paused:
        return False
    for decision, segment in paused:
        if not segment.spans or any(span.category != "BUDGET" for span in segment.spans):
            return False
        if not any(span.text in plan.amount_texts for span in segment.spans):
            return False
    return True


def strip_held(text: str, plan: MeetingBudgetPlan) -> str:
    """外发和未授权展示都不能带上金额原文或泛化短语。"""
    return _strip_amounts(text or "", plan.amount_texts, plan.phrase)


def present_amount(reply: str, plan: MeetingBudgetPlan, allowed: bool) -> str:
    """模型返回后才在本地补金额，而且只在展示边界允许时补。"""
    text = _strip_amounts(reply or "", plan.amount_texts, "" if allowed else plan.phrase)
    plan.presented = False
    if not allowed or plan.blocked or not plan.phrase:
        return text
    line = f"{plan.label}：{plan.phrase}"
    if plan.phrase in text:
        plan.presented = True
        return text
    plan.presented = True
    return (text.rstrip() + "\n" + line).strip()

