"""Compare local span replacement with the Presidio anonymizer on fixed files."""

from __future__ import annotations

import argparse
from importlib.metadata import version
import json
from pathlib import Path
from time import perf_counter

from llm_shield.m2_detect.pipeline import detect_all


def compare(text: str, engine, recognizer_result, operator_config) -> dict:
    spans = sorted(detect_all(text), key=lambda span: span.start)
    marker = "[REDACTED]"
    if any(a.end > b.start for a, b in zip(spans, spans[1:])):
        raise ValueError("识别片段重叠，无法同口径对照")
    start = perf_counter()
    local = text
    for span in reversed(spans):
        local = local[:span.start] + marker + local[span.end:]
    local_ms = (perf_counter() - start) * 1000

    results = [recognizer_result(entity_type=span.category, start=span.start,
                                 end=span.end, score=span.confidence) for span in spans]
    start = perf_counter()
    processed = engine.anonymize(text, results, {
        "DEFAULT": operator_config("replace", {"new_value": marker}),
    }).text
    return {"characters": len(text), "spans": len(spans), "identical_output": local == processed,
            "local_ms": round(local_ms, 3), "presidio_ms": round((perf_counter() - start) * 1000, 3)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", type=Path, nargs="*", help="可选的获准本机 UTF-8 文本")
    args = parser.parse_args()
    try:
        from presidio_anonymizer import AnonymizerEngine
        from presidio_anonymizer.entities import OperatorConfig, RecognizerResult
    except ImportError:
        parser.error("请先安装 requirements-presidio.txt")

    engine = AnonymizerEngine()
    samples = [f.read_text(encoding="utf-8") for f in args.files] or [
        "负责人：张明。联系电话：13812345678。下周一准备海报。",
        "邮箱：synthetic@example.invalid；周五提交物料清单。",
    ]
    results = [compare(text, engine, RecognizerResult, OperatorConfig) for text in samples]
    print(json.dumps({"presidio_version": version("presidio-anonymizer"), "samples": results}, ensure_ascii=False))
    return int(any(not row["identical_output"] for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
