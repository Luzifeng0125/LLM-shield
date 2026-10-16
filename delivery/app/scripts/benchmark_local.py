"""Measure local processing without calling an external model or writing payloads."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm_shield.processing import analyze  # noqa: E402
from llm_shield.m6_transform.anonymizer import apply_decisions  # noqa: E402
from llm_shield.m6_transform.mapping import MappingTable  # noqa: E402
from llm_shield.schema import Material  # noqa: E402


def cases():
    short = Material("short", "uploaded", "", "负责人张明，电话13812345678。周五交稿。")
    return {
        "short": ([short], ""),
        "three_materials": ([short, Material("a", "uploaded", "", "会议安排周五讨论。"),
                             Material("b", "uploaded", "", "活动场地在第一教学楼。")], ""),
        "long_context": ([Material("long", "uploaded", "", "本周例会讨论活动安排。" * 180)],
                         "已处理的公开会议摘要。" * 120),
    }


def measure(materials, context, repeats):
    values = []
    detect_values = []
    decide_values = []
    for _ in range(repeats):
        started = time.perf_counter()
        analysis = analyze("student_leader", "meeting_minutes", "external_model",
                           materials, context=context)
        detect_values.append(analysis.timings["detect_ms"])
        decide_values.append(analysis.timings["decide_ms"])
        if not analysis.paused:
            apply_decisions(analysis.text, analysis.segments, analysis.decisions,
                            "benchmark", MappingTable())
        values.append((time.perf_counter() - started) * 1000)
    values.sort()
    return {"runs": repeats, "median_ms": round(statistics.median(values), 2),
            "max_ms": round(values[-1], 2),
            "detect_median_ms": round(statistics.median(detect_values), 2),
            "decide_median_ms": round(statistics.median(decide_values), 2),
            "paused": bool(analysis.paused)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100:
        parser.error("repeats must be between 1 and 100")
    scenarios = cases()
    # Separate model loading from the measured steady-state requests.
    measure(*scenarios["short"], 1)
    result = {name: measure(materials, context, args.repeats)
              for name, (materials, context) in scenarios.items()}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
