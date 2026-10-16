from fastapi.testclient import TestClient

from llm_shield.chat import ChatStore, SESSION_TTL_SECONDS
from llm_shield.metrics import observe, snapshot
from llm_shield.m8_audit import observer
from llm_shield.schema import Span
from llm_shield.server import app


def test_expired_session_clears_private_state():
    store = ChatStore()
    session = store.create("student_leader", "meeting_minutes")
    session.messages.append({"role": "user", "content": "safe"})
    session.private_spans.append(Span(0, 2, "张明", "PERSON_NAME"))
    session.mapping.get_or_create(session.session_id, "张明", "PERSON_NAME",
                                  ["甲"], {"person": "人员{code}"})
    session.touched_at -= SESSION_TTL_SECONDS + 1
    assert store.stats()["active_sessions"] == 0
    assert not session.active and not session.messages and not session.private_spans
    assert not session.mapping.export(session.session_id)


def test_placeholder_exemption_requires_this_session_code_at_that_position(monkeypatch):
    payload = "人员甲与甲"
    monkeypatch.setattr(observer, "detect_all", lambda _: [
        Span(2, 3, "甲", "PERSON_NAME"),
        Span(4, 5, "甲", "PERSON_NAME"),
    ])
    hits = observer.check_category_leakage(payload, "external_model",
                                           task_key="meeting_minutes",
                                           identity_key="student_leader",
                                           placeholders={"人员甲"})
    assert len(hits) == 1
    assert len(observer.check_category_leakage(payload, "external_model",
               task_key="meeting_minutes", identity_key="student_leader")) == 2


def test_health_and_metrics_expose_no_content(monkeypatch):
    import llm_shield.server as server

    monkeypatch.setattr(server, "readiness", lambda: {"ready_local": True,
                                                      "real_api_configured": False})
    client = TestClient(app)
    assert client.get("/api/health").json()["ready_local"]
    observe("detect_ms", 12.5)
    metrics = client.get("/api/metrics").json()["latency"]
    assert metrics["detect_ms"]["count"] >= 1
    assert "张明" not in str(metrics)
