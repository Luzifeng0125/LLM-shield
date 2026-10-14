"""模块 ③ 硬约束检查。

架构要求：
  (1) 满足硬约束：排除违反目的限制 / 权限 / 禁止项的方案
  硬约束不可被效用评分抵消 —— 这里的判定只返回 通过/不通过，不产出分数。
"""
from __future__ import annotations

from typing import List, Optional

from ..config import (
    category_level,
    identities,
    recipients,
    rules,
    tasks,
)
from ..m1_access.identity import check_provide, identity_max_level
from ..schema import Action, HardCheck, Segment

# 不披露原文的动作：任何情况下都允许（它们不会把原文带给接收方）
SAFE_ACTIONS = {Action.DELETE, Action.LOCAL_AGGREGATE}
# 会产生某种形式披露的动作：必须逐条过硬约束
DISCLOSING_ACTIONS = {Action.GENERALIZE, Action.PSEUDONYMIZE, Action.RETAIN}

ALL_ACTIONS = [
    Action.DELETE, Action.LOCAL_AGGREGATE, Action.GENERALIZE,
    Action.PSEUDONYMIZE, Action.RETAIN, Action.PAUSE,
]

# 可泛化的类别（泛化后残留信息不足以定位到个人）
GENERALIZABLE = {"LOCATION", "ORG", "PERSON_NAME", "BUDGET", "DORM", "GRADE",
                 "STUDENT_ID", "PHONE", "EMAIL", "WECHAT"}
# 可做代号替换的类别
PSEUDONYMIZABLE = {"PERSON_NAME", "ORG"}
# 支持本地聚合的类别（用于计数/求和）
AGGREGATABLE = {"PERSON_NAME", "BUDGET", "GRADE", "STUDENT_ID", "DORM", "PHONE", "EMAIL"}

# 低信任边界不得收到可直接识别个人的原始值；代号/泛化结果不属于原始值。
DIRECT_IDENTIFIERS = {"PERSON_NAME", "PHONE", "EMAIL", "STUDENT_ID", "WECHAT",
                      "ID_CARD", "BANK_CARD", "API_KEY"}


def _task_cfg(task_key: str) -> dict:
    value = tasks().get(task_key)
    return value if isinstance(value, dict) else {}


def _recipient_cfg(recipient_key: str) -> dict:
    value = recipients().get(recipient_key)
    return value if isinstance(value, dict) else {}


def disclosed_categories(action: Action, seg: Segment) -> set:
    """该动作实际会「带出去」的类别集合。

    这是硬约束判定的关键：判定对象必须是动作执行后真正残留的信息，
    而不是片段里原本有哪些类别。
    例：代号替换会把手机号一并删除（手机号不在可代号化类别内），
        那么手机号就不应再参与该动作的接收方禁令检查，
        否则会把「代号替换」误杀成「暂停外发」。
    """
    cats = {s.category for s in seg.spans}
    if action in SAFE_ACTIONS:
        return set()                      # 删除/本地聚合不披露原文
    if action == Action.PSEUDONYMIZE:
        return cats & PSEUDONYMIZABLE     # 其余类别在转换时被删除
    if action == Action.GENERALIZE:
        return cats & GENERALIZABLE       # 其余类别在转换时被删除
    return cats                           # 受控保留：全部原样带出


def action_applicable(action: Action, seg: Segment, task_key: str) -> bool:
    """动作在该片段上是否「技术上可执行」。

    注意：只判断可行性，不做安全性判断（安全性在 check_hard 里）。
    """
    cats = {s.category for s in seg.spans}
    if action == Action.PSEUDONYMIZE:
        return bool(cats & PSEUDONYMIZABLE)
    if action == Action.GENERALIZE:
        return bool(cats & GENERALIZABLE)
    if action == Action.LOCAL_AGGREGATE:
        # 只有存在可聚合实体、且任务确实需要统计性输出时才可行
        if not (cats & AGGREGATABLE):
            return False
        task = _task_cfg(task_key)
        need_stat = any(k in ("COUNT", "PERSON_ROLE", "PUBLIC_FACT")
                        for k in task.get("must_retain", []))
        return need_stat
    return True


def check_hard(action: Action, seg: Segment, task_key: str,
               recipient_key: str, identity_key: str) -> List[HardCheck]:
    """对单个动作执行全部硬约束检查。"""
    checks: List[HardCheck] = []

    if action == Action.PAUSE:
        return [HardCheck("PAUSE", True, "暂停外发")]

    # 配置顶层还含有 version 字段，不能仅检查 key 存在就认定为有效上下文。
    known_task = bool(_task_cfg(task_key))
    known_recipient = bool(_recipient_cfg(recipient_key))
    known_identity = isinstance(identities().get(identity_key), dict)
    checks.extend([
        HardCheck("KNOWN_TASK", known_task, "任务已定义" if known_task else "未知任务，暂停处理"),
        HardCheck("KNOWN_RECIPIENT", known_recipient,
                  "接收方已定义" if known_recipient else "未知接收方，暂停处理"),
        HardCheck("KNOWN_IDENTITY", known_identity,
                  "身份已定义" if known_identity else "未知身份，暂停处理"),
    ])
    if not all(check.passed for check in checks):
        return checks
    authorized, why = check_provide(identity_key, recipient_key)
    checks.append(HardCheck("PERMISSION", authorized, why))
    if not authorized:
        return checks

    # 不披露原文的动作不产生泄露风险，直接放行
    if action in SAFE_ACTIONS:
        checks.append(HardCheck("NO_DISCLOSURE", True,
                               f"{action.value} 不披露原文，天然满足硬约束"))
        return checks

    cfg = rules().get("hard_constraints", {})
    task = _task_cfg(task_key)
    rec = _recipient_cfg(recipient_key)

    absolute_ban = set(cfg.get("absolute_ban", []))
    never_send = set(task.get("never_send", []))
    rec_forbidden = set(rec.get("forbidden", []))
    rec_max_level = int(rec.get("max_level", 1))
    ident_max_level = identity_max_level(identity_key)
    low_thr = float(cfg.get("low_confidence_threshold", 0.6))
    low_ban_level = int(cfg.get("low_confidence_ban_level", 4))

    # 只对该动作「真正会带出去」的类别做检查
    disclosed = disclosed_categories(action, seg)

    unknown = sorted(disclosed - set(rules().get("categories", {})))
    checks.append(HardCheck("KNOWN_CATEGORY", not unknown,
                            f"未知敏感类别 {unknown}" if unknown else "敏感类别已定义"))

    raw_identifiers = sorted(disclosed & DIRECT_IDENTIFIERS) if action == Action.RETAIN else []
    low_trust_hit = raw_identifiers if rec.get("trust") == "low" else []
    checks.append(HardCheck(
        "LOW_TRUST_IDENTIFIERS", not low_trust_hit,
        f"低信任接收方禁止直接标识符原值 {low_trust_hit}" if low_trust_hit
        else "未向低信任接收方保留直接标识符原值"))

    # --- (1) 绝对禁止项 ---
    hit = sorted(disclosed & absolute_ban)
    checks.append(HardCheck(
        "ABSOLUTE_BAN", not hit,
        f"命中绝对禁止类别 {hit}" if hit else "未命中绝对禁止类别"))

    # --- (2) 目的限制（任务 never_send）---
    hit = sorted(disclosed & never_send)
    checks.append(HardCheck(
        "PURPOSE_LIMIT", not hit,
        f"任务「{task.get('name', task_key)}」禁止外发 {hit}" if hit
        else f"符合任务「{task.get('name', task_key)}」的目的限制"))

    # --- (3) 接收方限制 ---
    hit = sorted(disclosed & rec_forbidden)
    checks.append(HardCheck(
        "RECEIVER_BAN", not hit,
        f"接收方「{rec.get('name', recipient_key)}」禁止接收 {hit}" if hit
        else f"接收方「{rec.get('name', recipient_key)}」允许"))

    # --- (4) 权限级别（身份 ∩ 接收方 取更严）---
    max_level = min(ident_max_level, rec_max_level)
    over = sorted({c for c in disclosed if category_level(c) > max_level})
    checks.append(HardCheck(
        "PERMISSION_LEVEL", not over,
        f"类别 {over} 的敏感级别超过允许上限 L{max_level}" if over
        else f"敏感级别均在允许上限 L{max_level} 内"))

    # --- (5) 低置信 + 高风险 ---
    risky = sorted({s.category for s in seg.spans
                    if s.category in disclosed
                    and s.confidence < low_thr
                    and category_level(s.category) >= low_ban_level})
    checks.append(HardCheck(
        "LOW_CONFIDENCE", not risky,
        f"类别 {risky} 置信度低于 {low_thr} 且属高风险，禁止上传" if risky
        else "无低置信高风险项"))

    return checks


def feasible_actions(seg: Segment, task_key: str, recipient_key: str,
                     identity_key: str) -> List[Action]:
    """返回通过全部硬约束、且技术上可行的动作集合。"""
    out: List[Action] = []
    for action in ALL_ACTIONS:
        if action == Action.PAUSE:
            continue
        if not action_applicable(action, seg, task_key):
            continue
        if all(c.passed for c in check_hard(action, seg, task_key, recipient_key, identity_key)):
            out.append(action)
    return out
