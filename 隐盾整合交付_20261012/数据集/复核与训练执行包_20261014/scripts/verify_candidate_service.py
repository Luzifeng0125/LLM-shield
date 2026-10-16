"""Exercise the opt-in candidate through the real ASGI endpoints, without network calls."""
from __future__ import annotations

import argparse
import faulthandler
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[3] / "app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "scripts"))


def verify(args):
    faulthandler.dump_traceback_later(60, exit=True)
    if args.out.exists():
        raise ValueError("Use a new output file")
    import torch
    torch.set_num_threads(4)
    from start_reviewed_candidate import preflight
    readiness = preflight(args.model.resolve(), args.device)
    print("Model preflight passed", flush=True)
    from fastapi.testclient import TestClient
    from llm_shield.server import app
    from llm_shield.m7_egress.gateway import EgressGateway
    from llm_shield.m7_egress.llm_client import OpenAICompatLLM
    from unittest.mock import patch
    request = {"session_id": "reviewed-candidate-service-smoke", "identity": "student_leader",
               "task": "meeting_minutes", "recipient": "external_model",
               "custom_text": "事项：招新推文终稿，负责人：李晓华，期限：2026年3月22日，联系电话：13923456789。",
               "send_model": True}
    with patch.object(OpenAICompatLLM, "chat_messages", side_effect=AssertionError("External API forbidden")) as external:
        with TestClient(app) as client:
            print("ASGI lifespan started", flush=True)
            page = client.get("/")
            assert page.status_code == 200
            response = client.post("/api/run", json=request)
            print("ASGI pipeline request returned", flush=True)
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["ok"] and not result["paused"], result.get("pause_reason")
            assert "13923456789" not in result["sanitized_text"]
            assert "李晓华" not in result["sanitized_text"]
            assert "模拟" in result["model_output"]
            assert len(result["boundaries"]) == 3
            denied = client.post("/api/run", json={**request, "recipient": "unknown-recipient"})
            assert denied.status_code == 400
            # The unchanged segment policy has a known applicability mistake on
            # this phrasing. Preserve the finding and check that it fails closed.
            mixed_response = client.post("/api/run", json={**request,
                "session_id": "reviewed-candidate-known-policy-limitation",
                "custom_text": "负责人张明负责海报，周五交稿；联系电话13923456789。"})
            assert mixed_response.status_code == 200
            mixed = mixed_response.json()
            assert mixed["paused"] and not mixed["ok"]
            assert not mixed["model_output"] and not mixed["display_text"] and not mixed["egress_text"]
            assert all(boundary["blocked"] for boundary in mixed["boundaries"])
        gateway = EgressGateway()
        blocked = gateway.precheck("external_model", "student_leader", "负责人张明，电话13923456789",
                                   task_key="meeting_minutes")
        clean = gateway.precheck("external_model", "student_leader", "人员甲负责整理纪要。",
                                 task_key="meeting_minutes")
        assert not blocked["allowed"] and clean["allowed"]
        assert external.call_count == 0
    report = {"status": "passed", "preflight": readiness,
              "home_http_status": page.status_code, "run_http_status": response.status_code,
              "unknown_recipient_status": denied.status_code,
              "sensitive_raw_payload_blocked": not blocked["allowed"],
              "pseudonym_payload_allowed": clean["allowed"], "external_model_calls": 0,
              "pipeline_result": result,
              "known_segment_policy_limitation": {
                  "action_inapplicable_paused_safely": True, "result": mixed,
                  "note": "Old segment policy selected an inapplicable pseudonym action; request-level v2 is not integrated."},
              "scope": "Synthetic software fixture via ASGI, not gold quality or real-provider acceptance."}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    faulthandler.cancel_dump_traceback_later()
    print(json.dumps({key: value for key, value in report.items()
                      if key not in {"pipeline_result", "known_segment_policy_limitation"}}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    verify(parser.parse_args())
