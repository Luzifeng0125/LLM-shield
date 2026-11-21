"""Check the complete response, including fields the page does not render."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from llm_shield import pipeline, server
from llm_shield.m7_egress import gateway
from llm_shield.schema import PipelineResult


def test_blocked_generated_answer_cannot_escape_in_other_json_fields(monkeypatch):
    monkeypatch.setattr(pipeline, "get_model", lambda: SimpleNamespace(available=True))
    monkeypatch.setattr(gateway, "chat_with_fallback", lambda *a, **k: {
        "text": "电话13812345678", "engine": "mock", "error": ""})
    response = TestClient(server.app).post("/api/notice/draft", json={
        "activity_name": "校园科技日", "items": ["check_in"]})
    assert response.status_code == 200
    assert "13812345678" not in response.text
    assert not response.json()["model_output"]


def test_public_serializer_drops_raw_diagnostics_even_when_paused():
    result = PipelineResult(False, "s", "meeting_minutes", "student_leader", "external_model",
                            original_text="秘密原文", sanitized_text="秘密原文",
                            model_output="秘密原文", display_text="秘密原文",
                            egress_text="秘密原文", paused=True,
                            spans=[{"text": "秘密原文", "category": "PHONE"}],
                            decisions=[{"text": "秘密原文", "action": "PAUSE"}],
                            aggregates={"秘密原文": 1}, mapping_table={"秘密原文": "人员A"},
                            boundaries=[{"boundary": "B2_VIEW_DISPLAY", "blocked": True,
                                         "allowed": False, "leak_hits": [{"text": "秘密原文"}]}])
    assert "秘密原文" not in str(result.to_dict())


def test_approved_notice_still_returns_publishable_text(monkeypatch):
    monkeypatch.setattr(pipeline, "get_model", lambda: SimpleNamespace(available=True))
    monkeypatch.setattr(gateway, "chat_with_fallback", lambda *a, **k: {
        "text": "请参加校园科技日并按要求签到。", "engine": "mock", "error": ""})
    data = TestClient(server.app).post("/api/notice/draft", json={
        "activity_name": "校园科技日", "items": ["check_in"]}).json()
    assert "校园科技日" in data["display_text"]
    assert data["model_output"] == data["display_text"]


def test_missing_publication_record_fails_closed():
    result = PipelineResult(True, "s", "meeting_minutes", "student_leader", "external_model",
                            model_output="未检查回答", display_text="未检查回答")
    assert "未检查回答" not in str(result.to_dict())
