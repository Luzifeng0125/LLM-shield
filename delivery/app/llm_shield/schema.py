"""隐盾核心数据结构定义。

所有模块之间只通过这些 dataclass 交换数据，
保证「识别 → 决策 → 转换 → 外发 → 观测」各环节解耦、可单独替换。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Action(str, Enum):
    """模块 ③ 的六种候选动作。"""
    DELETE = "DELETE"
    LOCAL_AGGREGATE = "LOCAL_AGGREGATE"
    GENERALIZE = "GENERALIZE"
    PSEUDONYMIZE = "PSEUDONYMIZE"
    RETAIN = "RETAIN"
    PAUSE = "PAUSE"


class RecipientType(str, Enum):
    """模块 ⑦ 的三类接收方，对应三个观测边界。"""
    EXTERNAL_MODEL = "EXTERNAL_MODEL"   # 边界1：发送给模型的请求
    VIEWER = "VIEWER"                   # 边界2：展示给用户的结果
    EGRESS_TOOL = "EGRESS_TOOL"         # 边界3：提交给工具接收端


class Boundary(str, Enum):
    B1_MODEL_INPUT = "B1_MODEL_INPUT"
    B2_VIEW_DISPLAY = "B2_VIEW_DISPLAY"
    B3_TOOL_EGRESS = "B3_TOOL_EGRESS"


# ---------------------------------------------------------------- 识别层


@dataclass
class Span:
    """一个敏感信息片段（模块 ② 的输出单元）。"""
    start: int
    end: int
    text: str
    category: str
    confidence: float = 1.0
    detector: str = "rule"
    rule_id: str = ""
    # 结构化表格上下文（若有）
    column: Optional[str] = None
    row_index: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start": self.start, "end": self.end, "text": self.text,
            "category": self.category, "confidence": round(self.confidence, 3),
            "detector": self.detector, "rule_id": self.rule_id,
            "column": self.column, "row_index": self.row_index,
        }


@dataclass
class Segment:
    """决策单元：一段文本 + 其上命中的敏感片段。"""
    seg_id: str
    text: str
    start: int
    end: int
    spans: List[Span] = field(default_factory=list)
    column: Optional[str] = None
    row_index: Optional[int] = None
    # 局部上下文（前后各 N 字），供必要性模型使用
    context: str = ""

    def top_category(self) -> Optional[str]:
        """返回本片段中级别最高（以置信度优先）的敏感类别。"""
        if not self.spans:
            return None
        return max(self.spans, key=lambda s: s.confidence).category


# ---------------------------------------------------------------- 决策层


@dataclass
class HardCheck:
    """一条硬约束的判定结果。"""
    rule: str          # ABSOLUTE_BAN / PURPOSE_LIMIT / PERMISSION / RECEIVER_BAN / LOW_CONF
    passed: bool
    detail: str = ""


@dataclass
class Decision:
    """模块 ③ 对单个 Segment 的决策结果。"""
    seg_id: str
    action: Action
    categories: List[str]
    reason: str = ""
    hard_checks: List[HardCheck] = field(default_factory=list)
    necessity_scores: Dict[str, float] = field(default_factory=dict)
    utility_warning: str = ""
    fallback: bool = False   # True 表示从首选动作降级而来

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seg_id": self.seg_id, "action": self.action.value,
            "categories": self.categories, "reason": self.reason,
            "hard_checks": [{"rule": h.rule, "passed": h.passed, "detail": h.detail}
                            for h in self.hard_checks],
            "necessity_scores": {k: round(v, 3) for k, v in self.necessity_scores.items()},
            "utility_warning": self.utility_warning, "fallback": self.fallback,
        }


# ---------------------------------------------------------------- 输入/输出


@dataclass
class Material:
    """输入材料（虚构演示用）。"""
    doc_id: str
    doc_type: str        # activity_roster / meeting_minutes / project_plan ...
    title: str
    text: str
    rows: Optional[List[Dict[str, str]]] = None   # 结构化表格行
    columns: Optional[List[str]] = None


@dataclass
class ShieldRequest:
    """一次完整请求。"""
    session_id: str
    identity: str            # student_leader / course_member / external_partner
    task: str                # activity_stats / meeting_minutes / project_intro
    recipient: str           # recipients.yaml 中的 key
    materials: List[Material]
    user_instruction: str = ""


@dataclass
class BoundaryRecord:
    """模块 ⑧ 三边界观测记录：以实际载荷判断是否泄露。"""
    boundary: Boundary
    recipient: str
    recipient_type: RecipientType
    payload: str
    leaked_categories: List[str] = field(default_factory=list)
    leak_hits: List[Dict[str, Any]] = field(default_factory=list)
    blocked: bool = False
    blocked_reason: str = ""
    allowed: bool = True
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "boundary": self.boundary.value, "recipient": self.recipient,
            "recipient_type": self.recipient_type.value,
            "leaked_categories": self.leaked_categories,
            "leak_hits": self.leak_hits, "blocked": self.blocked,
            "blocked_reason": self.blocked_reason, "allowed": self.allowed,
            "latency_ms": round(self.latency_ms, 2),
        }


@dataclass
class PipelineResult:
    """端到端流水线结果，直接返回给前端展示。"""
    ok: bool
    session_id: str
    task: str
    identity: str
    recipient: str
    access_ok: bool = True
    access_reason: str = ""
    original_text: str = ""
    sanitized_text: str = ""
    model_output: str = ""
    display_text: str = ""
    egress_text: str = ""
    spans: List[Dict[str, Any]] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    aggregates: Dict[str, Any] = field(default_factory=dict)
    mapping_table: Dict[str, str] = field(default_factory=dict)
    boundaries: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    timings: Dict[str, float] = field(default_factory=dict)
    paused: bool = False
    pause_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "session_id": self.session_id, "task": self.task,
            "identity": self.identity, "recipient": self.recipient,
            "access_ok": self.access_ok, "access_reason": self.access_reason,
            "original_text": self.original_text, "sanitized_text": self.sanitized_text,
            "model_output": self.model_output, "display_text": self.display_text,
            "egress_text": self.egress_text, "spans": self.spans,
            "decisions": self.decisions, "aggregates": self.aggregates,
            "mapping_table": self.mapping_table, "boundaries": self.boundaries,
            "warnings": self.warnings, "timings": {k: round(v, 2) for k, v in self.timings.items()},
            "paused": self.paused, "pause_reason": self.pause_reason,
        }
