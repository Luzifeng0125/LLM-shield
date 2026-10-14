"""模块 ① 资料加载与身份检查。

架构要求：
- 按身份返回有权读取的材料（无权内容在入模前拒绝）
- 分别检查「能否读取」与「能否向指定接收方提供」
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from ..config import identities, recipients
from ..schema import Material


@dataclass
class AccessResult:
    ok: bool = True
    reason: str = ""
    allowed_materials: List[Material] = field(default_factory=list)
    denied_docs: List[str] = field(default_factory=list)


def check_read(identity_key: str, materials: List[Material]) -> AccessResult:
    """检查 1：该身份能否读取这些材料。无权材料直接从输入中剔除。"""
    ident = identities().get(identity_key)
    if ident is None:
        return AccessResult(False, f"未知身份: {identity_key}")

    readable = set(ident.get("readable", []))
    allowed, denied = [], []
    for m in materials:
        if m.doc_type in readable:
            allowed.append(m)
        else:
            denied.append(m.doc_id)

    if not allowed:
        return AccessResult(
            False,
            f"身份「{ident.get('name', identity_key)}」无权读取任何所提交材料"
            f"（被拒: {', '.join(denied) or '无'}）",
            [], denied,
        )
    reason = f"已按身份过滤，剔除无权材料 {len(denied)} 份" if denied else "全部材料有权读取"
    return AccessResult(True, reason, allowed, denied)


def check_provide(identity_key: str, recipient_key: str) -> Tuple[bool, str]:
    """检查 2：该身份能否向指定接收方提供内容（与「能否读取」分开判定）。"""
    ident = identities().get(identity_key)
    if ident is None:
        return False, f"未知身份: {identity_key}"
    rec = recipients().get(recipient_key)
    if rec is None:
        # 未知接收方 → 一律拒绝（模块 ⑦）
        return False, f"未知接收方: {recipient_key}（默认策略 deny）"

    allowed = set(ident.get("can_send_to", []))
    if recipient_key not in allowed:
        return False, (
            f"身份「{ident.get('name', identity_key)}」未被授权向"
            f"「{rec.get('name', recipient_key)}」提供内容"
        )
    return True, f"授权通过：{ident.get('name')} → {rec.get('name')}"


def identity_max_level(identity_key: str) -> int:
    return int(identities().get(identity_key, {}).get("max_level", 1))


def can_restore(identity_key: str, recipient_key: str) -> bool:
    """模块 ⑥ 授权恢复：身份与接收方都允许，才能把代号还原为真实姓名。"""
    ident = identities().get(identity_key, {})
    rec = recipients().get(recipient_key, {})
    return bool(ident.get("can_restore", False)) and bool(rec.get("can_restore", False))
