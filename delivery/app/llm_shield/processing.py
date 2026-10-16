"""Shared local policy path used by chat, preview, and one-shot runs."""
from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Callable, Sequence

from . import config as C
from .m1_access.identity import check_provide, check_read
from .m2_detect.pipeline import DetectionError, build_detectors, detect_and_segment
from .m3_decide.decision import decide_all
from .m4_necessity.model import get_model, necessity_scorer
from .material_processing import MaterialSizeError, prepare_materials
from .metrics import observe_timings
from .schema import Action, Decision, Material, Segment, Span

_SLOTS = threading.BoundedSemaphore(C.max_parallel_analyses())


class ProcessingFailure(RuntimeError):
    def __init__(self, stage: str, reason: str):
        super().__init__(reason)
        self.stage = stage


@dataclass
class Analysis:
    text: str
    spans: list[Span]
    segments: list[Segment]
    decisions: list[Decision]
    timings: dict[str, float]

    @property
    def paused(self) -> Decision | None:
        return next((decision for decision in self.decisions
                     if decision.action == Action.PAUSE), None)


def analyze(
    identity: str,
    task: str,
    recipient: str,
    materials: Sequence[Material],
    *,
    task_description: str = "",
    context: str = "",
    max_source_chars: int | None = None,
    model_loader: Callable = get_model,
    detector_builder: Callable = build_detectors,
    detect: Callable = detect_and_segment,
    scorer: Callable = necessity_scorer,
) -> Analysis:
    """Authorize, detect and decide; no transformation or external side effects."""
    timings: dict[str, float] = {}
    if not isinstance(C.tasks().get(task), dict):
        raise ProcessingFailure("task", "未知任务，不能确定外发策略")

    started = time.perf_counter()
    access = check_read(identity, list(materials))
    if not access.ok or access.denied_docs:
        raise ProcessingFailure("access", access.reason or "包含无权读取的材料")
    allowed, reason = check_provide(identity, recipient)
    if not allowed:
        raise ProcessingFailure("provide", reason)
    timings["access_ms"] = (time.perf_counter() - started) * 1000

    if not _SLOTS.acquire(blocking=False):
        raise ProcessingFailure("capacity", "本地分析任务繁忙，请稍后重试")
    try:
        return _analyze_authorized(access.allowed_materials, identity, task, recipient,
                                   task_description, context, max_source_chars,
                                   model_loader, detector_builder, detect, scorer, timings)
    finally:
        _SLOTS.release()


def _analyze_authorized(materials, identity, task, recipient, task_description, context,
                        max_source_chars, model_loader, detector_builder, detect,
                        scorer, timings) -> Analysis:
    model = model_loader()
    if not model.available:
        raise ProcessingFailure("model", "本地决策模型不可用：" + getattr(model, "reason", ""))

    started = time.perf_counter()
    try:
        detectors = detector_builder()
        prepared = prepare_materials(materials, detect=detect,
                                     detectors=detectors,
                                     max_source_chars=max_source_chars)
    except MaterialSizeError as exc:
        raise ProcessingFailure("size", "材料为空或超过容量上限") from exc
    except DetectionError as exc:
        raise ProcessingFailure("detect", str(exc)) from exc
    timings["detect_ms"] = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    decisions = decide_all(prepared.segments, task, recipient, identity,
                           necessity_scorer=scorer,
                           task_description=task_description, context=context)
    timings["decide_ms"] = (time.perf_counter() - started) * 1000
    observe_timings(timings)
    return Analysis(prepared.text, prepared.spans, prepared.segments, decisions, timings)
