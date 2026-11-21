"""模块 ② 敏感信息识别 —— 检测器抽象接口。

设计目的：识别器可插拔。
首版默认用「正则规则 + 校园词典 + 上下文启发式」（零依赖、P95 远低于 500ms）；
后续训练出 RoBERTa-campus 后，只需实现同样的 Detector 接口注册进来即可热替换，
决策层及之后的模块无需改动。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ..schema import Span


class Detector(ABC):
    """识别器基类。"""

    name: str = "base"

    @abstractmethod
    def detect(
        self,
        text: str,
        columns: Optional[List[str]] = None,
        rows: Optional[List[dict]] = None,
    ) -> List[Span]:
        """在文本中检测敏感片段。

        :param text:    待检测正文
        :param columns: 结构化表格列名（可选，用于列名判定）
        :param rows:    结构化表格行（可选）
        :return:        Span 列表，位置相对于传入的 text
        """
        raise NotImplementedError

    # ---- 工具方法：供子类复用 ----

    @staticmethod
    def _context_hit(text: str, start: int, end: int, words, window: int = 12) -> bool:
        """判断片段前后 window 字内是否出现上下文触发词。"""
        left = text[max(0, start - window): start]
        right = text[end: end + window]
        return any(w in left or w in right for w in words)

    @staticmethod
    def _clip(text: str, start: int, end: int) -> tuple[int, int]:
        return max(0, start), min(len(text), end)
