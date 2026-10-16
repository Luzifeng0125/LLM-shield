"""识别流水线：组合多个识别器 → 重叠合并 → 切分为决策单元（Segment）。"""
from __future__ import annotations

import re
from dataclasses import replace
from functools import lru_cache
from typing import List, Optional, Tuple

from .. import config as cfg
from ..config import category_level
from ..schema import Segment, Span
from .base import Detector
from .campus_ner import CampusNERDetector
from .entity_rules import EntityDetector
from .regex_rules import RegexDetector
from .reviewed_ner import ReviewedNERDetector

# 句子切分符
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？；;!?\n])")


class DetectionError(RuntimeError):
    """识别服务异常或结果无效；错误说明不含材料原文。"""


@lru_cache(maxsize=1)
def _reviewed_detector(model_dir: str, device: str) -> ReviewedNERDetector:
    if device not in {"cpu", "cuda"}:
        raise DetectionError("人工 gold NER 设备配置必须是 cpu 或 cuda")
    detector = ReviewedNERDetector(model_dir, device=device)
    if not detector.available:
        raise DetectionError("已启用的人工 gold NER 模型不可用，已暂停处理")
    return detector


def build_detectors(use_campus_ner: Optional[bool] = None) -> List[Detector]:
    """构建识别器链。

    :param use_campus_ner: 是否接入 ★ 领域预训练 NER。
        传 None 时按配置决定（config.use_campus_ner()，默认关闭）——
        领域模型推理约 576ms/2000字，会超出「规则+识别路径 P95 ≤ 500ms」的指标，
        因此默认走规则底座，需要时再显式开启。
    """
    if use_campus_ner is None:
        use_campus_ner = cfg.use_campus_ner()

    detectors: List[Detector] = [RegexDetector(), EntityDetector()]
    reviewed_path, reviewed_device = cfg.reviewed_ner_settings()
    if reviewed_path:
        detectors.append(_reviewed_detector(reviewed_path, reviewed_device))
    if use_campus_ner:
        ner = CampusNERDetector()
        if not ner.available:
            raise DetectionError("已启用的领域识别模型不可用，已暂停处理")
        detectors.append(ner)
    return detectors


def merge_spans(spans: List[Span], text: Optional[str] = None) -> List[Span]:
    """合并重叠片段。

    规则：
    - 同类别重叠 → 取并集，置信度取高；
    - 跨类别重叠 → 对整个重叠区间采用更严格类别，绝不丢弃区间两端的原文。
    - 合并后的 text 始终对应原始字符区间；不修改识别器提供的对象。
    """
    if not spans:
        return []
    spans = [replace(span) for span in spans]
    for span in spans:
        if (not isinstance(span.start, int) or not isinstance(span.end, int)
                or span.start < 0 or span.end <= span.start
                or (text is not None and span.end > len(text))):
            raise DetectionError("识别结果的位置无效，已暂停处理")
        if text is not None:
            span.text = text[span.start:span.end]
        elif len(span.text) != span.end - span.start:
            raise DetectionError("识别结果的文本长度与位置不一致，已暂停处理")
    spans.sort(key=lambda s: (s.start, -(s.end - s.start)))
    merged: List[Span] = [spans[0]]

    bans = set(cfg.rules().get("hard_constraints", {}).get("absolute_ban", []))
    direct = {"PERSON_NAME", "PHONE", "EMAIL", "STUDENT_ID", "WECHAT"}

    def priority(span: Span):
        return (span.category in bans, category_level(span.category),
                span.category in direct, span.confidence, span.end - span.start)

    for cur in spans[1:]:
        last = merged[-1]
        if cur.start >= last.end:
            merged.append(cur)
            continue
        # 存在重叠
        start, end = last.start, max(last.end, cur.end)
        union_text = (text[start:end] if text is not None else
                      last.text + cur.text[max(0, last.end - cur.start):])
        winner = max((last, cur), key=priority)
        merged[-1] = replace(winner, start=start, end=end, text=union_text,
                             confidence=max(last.confidence, cur.confidence))
    return merged


def detect_all(text: str, columns=None, rows=None,
               detectors: Optional[List[Detector]] = None) -> List[Span]:
    """跑完所有识别器并合并结果。"""
    detectors = detectors if detectors is not None else build_detectors()
    if not detectors:
        raise DetectionError("没有可用识别器，已暂停处理")
    all_spans: List[Span] = []
    for d in detectors:
        try:
            all_spans.extend(d.detect(text, columns=columns, rows=rows))
        except Exception:
            # 不能把识别失败等同于“没有敏感信息”；异常消息也可能包含输入原文。
            raise DetectionError("敏感信息识别器执行失败，已暂停处理") from None
    try:
        return merge_spans(all_spans, text)
    except DetectionError:
        raise
    except Exception:
        raise DetectionError("敏感信息识别结果无效，已暂停处理") from None


def segmentize(text: str, spans: Optional[List[Span]] = None) -> List[Segment]:
    """把正文切成决策单元（按句/换行）。"""
    segments: List[Segment] = []
    pos = 0
    for piece in _SENT_SPLIT_RE.split(text):
        if not piece:
            continue
        start = pos
        end = pos + len(piece)
        segments.append(Segment(
            seg_id=f"seg_{len(segments)}",
            text=piece, start=start, end=end,
        ))
        pos = end
    if not segments:
        segments.append(Segment("seg_0", text, 0, len(text)))
    if spans:
        # 列值、跨行实体可能包含句号/换行，不能被切成没有任何 span 的“干净”片段。
        joined: List[Segment] = []
        for segment in segments:
            if joined and any(span.start < segment.start < span.end for span in spans):
                previous = joined[-1]
                previous.end = segment.end
                previous.text = text[previous.start:previous.end]
            else:
                segment.seg_id = f"seg_{len(joined)}"
                joined.append(segment)
        segments = joined
    return segments


def attach_spans(segments: List[Segment], spans: List[Span], context_window: int = 30) -> None:
    """把全局坐标的 Span 挂到所属 Segment 上，并填充局部上下文。"""
    if any(not any(segment.start <= span.start and span.end <= segment.end
                   for segment in segments) for span in spans):
        raise DetectionError("敏感实体未完整归属处理片段，已暂停处理")
    for seg in segments:
        seg.spans = [s for s in spans if s.start >= seg.start and s.end <= seg.end]
        left = max(0, seg.start - context_window)
        right = min(len(seg.text) + seg.start + context_window, seg.start + len(seg.text) + context_window)
        seg.context = seg.text  # 上下文默认取本段文本（调用方可注入前后段）


def detect_and_segment(text: str, columns=None, rows=None,
                       detectors=None) -> Tuple[List[Span], List[Segment]]:
    """识别 + 分段，返回 (全局 spans, segments)。"""
    spans = detect_all(text, columns=columns, rows=rows, detectors=detectors)
    segments = segmentize(text, spans)
    attach_spans(segments, spans)
    return spans, segments
