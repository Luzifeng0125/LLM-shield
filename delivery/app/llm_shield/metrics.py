"""Bounded, content-free latency observations for local diagnostics."""
from __future__ import annotations

import math
import threading
from collections import defaultdict, deque

_SAMPLES: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=500))
_LOCK = threading.Lock()
_STAGES = {"access_ms", "detect_ms", "decide_ms", "transform_ms",
           "model_ms", "total_ms", "chat_total_ms", "chat_model_ms"}


def observe(stage: str, milliseconds: float) -> None:
    if stage not in _STAGES or not math.isfinite(milliseconds) or milliseconds < 0:
        return
    with _LOCK:
        _SAMPLES[stage].append(milliseconds)


def observe_timings(timings: dict[str, float]) -> None:
    for stage, milliseconds in timings.items():
        observe(stage, milliseconds)


def snapshot() -> dict:
    with _LOCK:
        samples = {stage: sorted(values) for stage, values in _SAMPLES.items() if values}
    return {stage: {"count": len(values),
                    "p50_ms": round(values[(len(values) - 1) // 2], 2),
                    "p95_ms": round(values[math.ceil(len(values) * .95) - 1], 2)}
            for stage, values in samples.items()}
