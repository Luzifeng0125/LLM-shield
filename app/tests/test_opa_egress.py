import json

import httpx
import pytest

from llm_shield.m7_egress import gateway, policy


@pytest.mark.parametrize("response, sends", [
    ({"result": True}, True),
    ({"result": False}, False),
    ({"result": 1}, False),
    ({}, False),
    (None, False),
])
def test_opa_gates_generation_using_only_policy_metadata(monkeypatch, response, sends):
    calls = []

    def authorize(request):
        assert str(request.url) == "http://127.0.0.1:8181/v1/data/shield/egress/allow"
        assert json.loads(request.content) == {"input": {
            "identity": "student_leader", "task": "meeting_minutes",
            "recipient": "external_model", "operation": "model_input",
        }}
        if response is None:
            raise httpx.ConnectError("internal diagnostics")
        return httpx.Response(200, json=response)

    def generate(*args):
        calls.append(args)
        return {"text": "公开答复", "engine": "real", "error": ""}

    monkeypatch.setenv("SHIELD_EGRESS_POLICY", "opa")
    monkeypatch.setenv("SHIELD_OPA_PORT", "8181")
    client = httpx.Client
    monkeypatch.setattr(policy.httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(authorize), **kw))
    monkeypatch.setattr(gateway, "chat_with_fallback", generate)
    monkeypatch.setattr(gateway, "inspect_payload", lambda *a, **k: {
        "leaked": False, "leaked_categories": [], "leak_hits": [],
    })
    result = gateway.EgressGateway().send_to_model("meeting_minutes", "公开内容", "student_leader")
    assert result["allowed"] is sends
    assert bool(calls) is sends
    assert "internal diagnostics" not in str(result)
