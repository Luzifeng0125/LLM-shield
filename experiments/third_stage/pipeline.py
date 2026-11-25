"""把 R0、上下文包、C3、L3 和 L4 串成一次可重复的实验运行。

不接入产品六动作，不调用 C4，也不把规则输出写成模型输出。
"""
from __future__ import annotations

import json

from experiments.third_stage.cases import materialize_suite
from experiments.third_stage.l4 import verify_case


def run_suite() -> list[dict]:
    suite = materialize_suite()
    results = []
    for case in suite["cases"]:
        outcome = verify_case(case)
        results.append({
            "case_id": case["case_id"],
            "expected_four_state": case["expected_four_state"],
            "expected_source_conflict": case["expected_source_conflict"],
            "four_state": outcome["four_state"],
            "source_conflict": outcome["source_conflict"],
            "reasons": outcome["reasons"],
            "disposition": outcome["disposition"],
            "assertion_diffs": assertion_diffs(case, outcome),
            "outcome": outcome,
        })
    return results


def assertion_diffs(case: dict, outcome: dict) -> list[str]:
    expected = case.get("expected_assertions") or {}
    if not expected:
        return []
    diffs = []
    current = [item for item in outcome["assertions"] if item["role"] == "current"]
    by_anchor = {item["evidence_location"]["anchor"]: item for item in current}
    for key, fields in expected.items():
        if key == "subject":
            for item in current:
                actual = item["dimensions"]["subject"]
                if not _same(actual, fields):
                    diffs.append(f"subject {item['evidence_location']['anchor']}: {actual} != {fields}")
            continue
        if key == "current":
            targets = current
        else:
            targets = [by_anchor[key]] if key in by_anchor else []
            if not targets:
                diffs.append(f"缺少锚点 {key}")
                continue
        for item in targets:
            for field, expected_dim in fields.items():
                actual_field = "status" if field == "status_c3" else field
                actual = item["dimensions"].get(actual_field)
                if actual is None or not _same(actual, expected_dim):
                    diffs.append(
                        f"{item['evidence_location']['anchor']}.{field}: {actual} != {expected_dim}"
                    )
    return diffs


def _same(actual: dict, expected: dict) -> bool:
    if actual.get("kind") != expected.get("kind"):
        return False
    if expected.get("kind") == "value" and actual.get("value") != expected.get("value"):
        return False
    return True


def main() -> None:
    rows = []
    for item in run_suite():
        rows.append({
            "case_id": item["case_id"],
            "expected": item["expected_four_state"],
            "actual": item["four_state"],
            "conflict": item["source_conflict"],
            "expected_conflict": item["expected_source_conflict"],
            "reasons": item["reasons"],
            "disposition": item["disposition"],
            "diffs": item["assertion_diffs"],
        })
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
