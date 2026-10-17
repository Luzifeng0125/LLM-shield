"""Shared preparation of materials for the preview, run, and chat flows.

Each material is detected with its own table metadata. Coordinates are then
translated into the joined text consumed by decisions and transformations.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Sequence

from .m1_access.loader import flatten_material
from .m2_detect.pipeline import DetectionError, detect_and_segment
from .m2_detect.gliner_ner import GLiNERDetector
from .schema import Material, Segment, Span


@dataclass
class PreparedMaterials:
    text: str
    spans: list[Span]
    segments: list[Segment]


class MaterialSizeError(ValueError):
    """The joined source exceeds a caller's accepted input size."""


class _CachedDetector:
    name = "gliner"

    def __init__(self, spans: list[Span]):
        self.spans = spans

    def detect(self, text, columns=None, rows=None):
        return self.spans


def split_mixed_segments(segments: Sequence[Segment]) -> list[Segment]:
    """Give different entity categories separate policy decisions in one sentence.

    Each new segment owns a disjoint slice of the original text and one span.
    The original sentence remains in ``context`` for the local action model.
    """
    result: list[Segment] = []
    for segment in segments:
        ordered = sorted(segment.spans, key=lambda span: span.start)
        if len({span.category for span in ordered}) <= 1:
            result.append(segment)
            continue
        for index, span in enumerate(ordered):
            start = segment.start if index == 0 else span.start
            end = ordered[index + 1].start if index + 1 < len(ordered) else segment.end
            if span.end > end:
                raise DetectionError("敏感实体边界重叠，已暂停处理")
            result.append(replace(segment, text=segment.text[start - segment.start:end - segment.start],
                                  start=start, end=end, spans=[span],
                                  column=span.column or segment.column,
                                  row_index=span.row_index if span.row_index is not None
                                  else segment.row_index))
    return result


def prepare_materials(
    materials: Sequence[Material],
    *,
    detect: Callable = detect_and_segment,
    detectors=None,
    max_source_chars: int | None = None,
) -> PreparedMaterials:
    """Flatten and detect each document without losing its table context."""
    pieces = [flatten_material(material) for material in materials]
    if max_source_chars is not None and (
        not pieces or sum(map(len, pieces)) > max_source_chars
    ):
        raise MaterialSizeError("material input exceeds the allowed size")
    model_detector = next((item for item in detectors or []
                           if isinstance(item, GLiNERDetector)), None)
    model_spans = None
    if model_detector is not None and len(pieces) > 1:
        try:
            model_spans = model_detector.detect_many(pieces)
            if len(model_spans) != len(pieces):
                raise ValueError("incomplete detector result")
        except Exception:
            raise DetectionError("GLiNER 识别失败，已暂停处理") from None
    spans: list[Span] = []
    segments: list[Segment] = []
    offset = 0
    for index, (material, piece) in enumerate(zip(materials, pieces)):
        document_detectors = detectors
        if model_spans is not None:
            document_detectors = [item for item in detectors if item is not model_detector]
            document_detectors.append(_CachedDetector(model_spans[index]))
        found, parts = detect(piece, columns=material.columns, rows=material.rows,
                              detectors=document_detectors)
        parts = split_mixed_segments(parts)
        if index < len(pieces) - 1 and parts:
            parts[-1].text += "\n"
            parts[-1].end += 1
        shifted = [replace(span, start=span.start + offset, end=span.end + offset)
                   for span in found]
        spans.extend(shifted)
        for part in parts:
            part.spans = [span for span in shifted
                          if offset + part.start <= span.start and span.end <= offset + part.end]
            part.start += offset
            part.end += offset
            part.seg_id = f"seg_{len(segments)}"
            segments.append(part)
        offset += len(piece) + 1
    return PreparedMaterials("\n".join(pieces), spans, segments)
