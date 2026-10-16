"""Replay every generated person code through the real local pipeline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "scripts"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--action-model", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ner-decoding", choices=("greedy", "bio_viterbi"), default="greedy")
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Use a new report path")
    import torch
    torch.set_num_threads(4)
    from start_reviewed_candidate import preflight
    preflight(args.model.resolve(), "cuda" if torch.cuda.is_available() else "cpu", args.action_model, args.ner_decoding)
    from llm_shield.config import rules
    from llm_shield.m6_transform.mapping import MappingTable, get_table
    from llm_shield.m7_egress.llm_client import OpenAICompatLLM
    from llm_shield.pipeline import run_pipeline
    from llm_shield.schema import Material, ShieldRequest
    results = []
    pool = rules()["pseudonym"]["prefix_pool"]
    fixtures = [
        ("mixed_sentence", "事项：招新推文终稿，负责人：李晓华，期限：2026年3月22日，联系电话：13923456789。"),
        ("separate_phone", "负责人张明负责海报，周五交稿；联系电话13923456789。"),
    ]
    with patch.object(OpenAICompatLLM, "chat_messages", side_effect=AssertionError("External API forbidden")) as external:
        for index, code in enumerate(pool):
            ordered = [code] + [other for other in pool if other != code]
            for kind, text in fixtures:
                session = f"candidate-code-{index}-{kind}"
                get_table().clear_session(session)
                with patch.object(MappingTable, "_pool_for_session", return_value=ordered):
                    result = run_pipeline(ShieldRequest(
                        session, "student_leader", "meeting_minutes", "external_model",
                        [Material("fixture", "uploaded", "", text)])).to_dict()
                passed = (result["ok"] and not result["paused"]
                          and all(not boundary["blocked"] for boundary in result["boundaries"]))
                for field in ("sanitized_text", "model_output", "egress_text"):
                    passed = passed and all(value not in result[field] for value in ("13923456789", "李晓华", "张明"))
                results.append({"code": code, "fixture": kind, "passed": bool(passed), "result": result})
        assert external.call_count == 0
    report = {"scope": "Generated pseudonym integration regression, not human gold", "external_calls": 0,
              "ner_decoding": args.ner_decoding,
              "passed": sum(item["passed"] for item in results), "total": len(results), "cases": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "total": report["total"],
                      "failures": [{"code": item["code"], "fixture": item["fixture"],
                                    "reason": item["result"]["pause_reason"],
                                    "boundaries": item["result"]["boundaries"]}
                                   for item in results if not item["passed"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
