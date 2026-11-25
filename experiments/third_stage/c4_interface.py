"""C4 离线模型接口。本轮没有获准模型，调用即拒绝。

不返回 C3 的结果，也不下载、安装或请求外部模型。
"""
from __future__ import annotations

from typing import Any


class C4Unavailable(RuntimeError):
    """C4 尚未执行。"""


def propose_link(context_package: dict[str, Any], *, model_id: str = "") -> dict[str, Any]:
    """未来的离线指令模型只接收 Context Package，并返回可定位的链接提案。"""
    raise C4Unavailable("C4 未获准，不能提案，也不能用规则结果代替")


def propose_assertion(evidence_text: str, *, model_id: str = "") -> dict[str, Any]:
    """未来的状态和指代提取。输入只有当前证据原文，没有披露结论。"""
    raise C4Unavailable("C4 未获准，不能提取，也不能用 C3 输出冒充")


INTERFACE = {
    "input": ["yin-dun.context_package.v1", "current evidence text"],
    "output_link": [
        "link_type",
        "target_candidate_id",
        "basis_span",
        "basis_start",
        "basis_end",
        "link_rationale",
    ],
    "structural_validation": "experiments.third_stage.links.validate_link",
    "reject": ["abstain", "structural_failure", "C4Unavailable"],
}
