"""模块 ⑥ 代号映射表：会话内稳定、会话间隔离。

架构要求：
- 需保留人物关系时，同一会话同一人物使用一致稳定代号
- 本地保存「原始姓名—代号」对应表（仅内存，不写普通日志，不外发）
- 不同会话映射隔离，避免同名代号错误关联
- 恢复姓名须结合本会话对应表 + 接收权限
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional


class MappingTable:
    """会话隔离的代号映射表。纯内存，不落盘、不进日志。"""

    def __init__(self, scope: str = "session"):
        self.scope = scope
        # session_id -> {原名 -> 代号}
        self._forward: Dict[str, Dict[str, str]] = {}
        # session_id -> {代号 -> 原名}
        self._backward: Dict[str, Dict[str, str]] = {}
        # session_id -> 已用代号序号
        self._counters: Dict[str, int] = {}

    # ------------------------------------------------------------ 代号分配

    @staticmethod
    def _pool_for_session(session_id: str, prefix_pool: List[str]) -> List[str]:
        """按会话派生代号池顺序：同一会话内稳定，不同会话之间代号不可互相推导。

        这样即使两个会话都从「甲」开始，也无法通过代号反推是否指向同一个人。
        """
        pool = list(prefix_pool)
        random.Random(hash(session_id) & 0xFFFFFFFF).shuffle(pool)
        return pool

    def _next_code(self, session_id: str, prefix_pool, template: str) -> str:
        idx = self._counters.get(session_id, 0)
        self._counters[session_id] = idx + 1
        pool = self._pool_for_session(session_id, prefix_pool)
        if idx < len(pool):
            code = pool[idx]
        else:
            code = f"{idx + 1}"
        return template.format(code=code)

    def get_or_create(self, session_id: str, real_value: str, category: str,
                      prefix_pool, templates: Dict[str, str]) -> str:
        """为某个实体分配（或复用）稳定代号。同一会话内同一实体永远得到同一代号。"""
        fwd = self._forward.setdefault(session_id, {})
        key = f"{category}::{real_value}"
        if key in fwd:
            return fwd[key]

        if category == "PERSON_NAME":
            template = templates.get("person", "人员{code}")
        elif category == "ORG":
            template = templates.get("org", "组织{code}")
        else:
            template = "代号{code}"

        code = self._next_code(session_id, prefix_pool, template)
        fwd[key] = code
        self._backward.setdefault(session_id, {})[code] = real_value
        return code

    # ------------------------------------------------------------ 授权恢复

    def restore(self, session_id: str, code: str, allowed: bool) -> Optional[str]:
        """把代号还原为原始值。

        :param allowed: 由 m1_access.identity.can_restore() 判定，
                        身份与接收方必须同时允许才能恢复。
        跨会话 / 未知代号 / 越权 → 返回 None（不执行恢复）。
        """
        if not allowed:
            return None
        bwd = self._backward.get(session_id)
        if not bwd:
            return None
        return bwd.get(code)

    def restore_text(self, session_id: str, text: str, allowed: bool) -> str:
        """批量恢复文本中的代号。"""
        if not allowed:
            return text
        bwd = self._backward.get(session_id, {})
        result = text
        for code, real in sorted(bwd.items(), key=lambda kv: -len(kv[0])):
            result = result.replace(code, real)
        return result

    # ------------------------------------------------------------ 管理

    def export(self, session_id: str) -> Dict[str, str]:
        """导出某会话的映射（供前端「对照」面板展示，不落盘）。"""
        return dict(self._forward.get(session_id, {}))

    def clear_session(self, session_id: str) -> None:
        self._forward.pop(session_id, None)
        self._backward.pop(session_id, None)
        self._counters.pop(session_id, None)


# 全局单例（内存态）
_TABLE: Optional[MappingTable] = None


def get_table() -> MappingTable:
    global _TABLE
    if _TABLE is None:
        _TABLE = MappingTable()
    return _TABLE
