"""Check truthful stage states and aggregate-only evaluation publication."""
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from llm_shield import chat, server, evaluation_report
from llm_shield.m7_egress import gateway


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SHIELD_USE_GLINER", "false")
    store = chat.ChatStore()
    monkeypatch.setattr(server, "STORE", store)
    monkeypatch.setattr(chat, "get_model", lambda: SimpleNamespace(available=True))
    def scorer(seg, *args, **kwargs):
        action = "PSEUDONYMIZE" if any(s.category == "PERSON_NAME" for s in seg.spans) else "DELETE"
        return {action: 1.0}
    monkeypatch.setattr(chat, "necessity_scorer", scorer)
    monkeypatch.setattr(gateway, "chat_messages_with_fallback", lambda *args: {
        "text": "已整理公开的分工安排。", "engine": "mock", "error": ""})
    return TestClient(server.app)


def turn(client, text="负责人：张明。电话13900001234。请整理会议纪要。"):
    sid = client.post("/api/chat/sessions", json={"task": "meeting_minutes"}).json()["session_id"]
    return client.post(f"/api/chat/{sid}/messages", json={"text": text}).json()


def test_success_trace_has_no_source_values_or_false_real_api_claim(client):
    result = turn(client)
    assert result["ok"]
    states = {item["id"]: item for item in result["stages"]}
    assert all(item["status"] == "passed" for key, item in states.items() if key != "utility")
    assert states["utility"]["status"] == "warning"
    assert "未调用真实 API" in states["output"]["detail"]
    assert "概率不是准确率" in states["policy"]["detail"]
    assert "张明" not in str(result["stages"]) and "13900001234" not in str(result)


def test_missing_model_does_not_claim_detection_was_run(client, monkeypatch):
    monkeypatch.setattr(chat, "get_model", lambda: SimpleNamespace(available=False, reason="missing"))
    result = turn(client)
    assert result["paused"]
    states = {item["id"]: item["status"] for item in result["stages"]}
    assert states["access"] == "passed" and states["policy"] == "blocked"
    assert states["detect"] == states["transform"] == states["gateway"] == "not_run"


def test_failed_probability_is_reported_as_model_failure(client, monkeypatch):
    def failed(*args, **kwargs):
        raise RuntimeError("PRIVATE_SOURCE_CANARY")
    monkeypatch.setattr(chat, "necessity_scorer", failed)
    result = turn(client)
    assert result["paused"] and "PRIVATE_SOURCE_CANARY" not in str(result)
    states = {item["id"]: item["status"] for item in result["stages"]}
    assert states["policy"] == "blocked" and states["gateway"] == "not_run"


def test_evaluation_api_omits_per_case_text(client, monkeypatch, tmp_path):
    metrics = {key: 1 for key in ("precision", "recall", "f1", "tp", "fp", "fn")}
    report = {
        "created_utc": "2026-11-02T08:00:00+00:00", "profile": "official_baseline",
        "cloud_api_called": False, "default_models_promoted": False, "environment": {},
        "parsing": {}, "necessity": {}, "historical_human31": {}, "limitations": [],
        "ner": {"dataset": "synthetic", "sha256": "x", "documents": 1, "gold_entities": 1,
                "scope": "fixture", "segmentation": {}, "configurations": {
                    "fused": {"scope": "all", "total_ms": 1, "latency": {}, "modes": {
                        "strict": {"overall": metrics, "macro_f1": 1, "per_category": {
                            "PERSON_NAME": {**metrics, "missed": ["PRIVATE_SOURCE_CANARY"]}}}}}}},
        "safeguards": {key: {"passed": 1, "total": 1, "checks": [{"text": "PRIVATE_SOURCE_CANARY"}]}
                       for key in ("constraints", "transformation", "utility", "boundaries")}}
    target = tmp_path / "summary.json"
    target.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(evaluation_report, "REPORT", target)
    monkeypatch.setattr(evaluation_report, "readiness", lambda: {"ready_local": True})
    monkeypatch.setattr(evaluation_report, "get_model", lambda: SimpleNamespace(metadata={"feature_version": 3}))
    result = client.get("/api/evaluation")
    assert result.status_code == 200 and result.json()["report_available"]
    assert "PRIVATE_SOURCE_CANARY" not in result.text
    assert client.get("/evaluation").status_code == 200
