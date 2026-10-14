"""模型故障、动作拒绝和 API 参数贯通的集成回归；不调用外网。"""
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient

from llm_shield import pipeline
from llm_shield.m6_transform.anonymizer import process_segment
from llm_shield.m6_transform.mapping import MappingTable
from llm_shield.schema import Action, Decision, Material, Segment, ShieldRequest, Span
from llm_shield.server import app


def request(text="负责人：张明，电话13812345678。另有可公开的活动安排。"):
    return ShieldRequest("model-only-test", "student_leader", "meeting_minutes",
                         "external_model", [Material("t", "uploaded", "测试", text)],
                         user_instruction="整理职责分配")


def test_missing_model_stops_even_clean_request(monkeypatch):
    monkeypatch.setattr(pipeline, "get_model", lambda: SimpleNamespace(available=False, reason="缺少权重"))
    gateway = Mock(side_effect=AssertionError("不应建立外发网关"))
    monkeypatch.setattr(pipeline, "EgressGateway", gateway)
    result = pipeline.run_pipeline(request("本次活动公开举办。"))
    assert result.paused and not result.ok
    assert all(b["blocked"] and not b["allowed"] for b in result.boundaries)
    assert not result.display_text and not result.egress_text and not result.model_output
    gateway.assert_not_called()


def test_model_pause_stops_whole_request(monkeypatch):
    monkeypatch.setattr(pipeline, "get_model", lambda: SimpleNamespace(available=True))
    monkeypatch.setattr(pipeline, "necessity_scorer", lambda *args, **kwargs: {"PAUSE": 1.0})
    gateway = Mock(side_effect=AssertionError("剩余公开段也不得发送"))
    monkeypatch.setattr(pipeline, "EgressGateway", gateway)
    result = pipeline.run_pipeline(request())
    assert not result.ok and result.paused and not result.sanitized_text
    assert result.decisions and "模型选择暂停" in result.pause_reason
    gateway.assert_not_called()


def test_forbidden_model_action_is_not_reselected(monkeypatch):
    monkeypatch.setattr(pipeline, "get_model", lambda: SimpleNamespace(available=True))
    monkeypatch.setattr(pipeline, "necessity_scorer", lambda *args, **kwargs: {"RETAIN": 0.9, "DELETE": 0.1})
    result = pipeline.run_pipeline(request(), send_model=False)
    assert result.paused and not result.ok
    assert all(d["action"] != "DELETE" for d in result.decisions)


def test_task_description_reaches_model(monkeypatch):
    monkeypatch.setattr(pipeline, "get_model", lambda: SimpleNamespace(available=True))
    received = []
    def scorer(*args, **kwargs):
        received.append(kwargs)
        return {"DELETE": 1.0}
    monkeypatch.setattr(pipeline, "necessity_scorer", scorer)
    pipeline.preview_only(request())
    assert received and all(k["task_description"] == "整理职责分配" for k in received)


def test_generalize_preserves_entity_coordinates_after_date():
    text = "2026年10月12日，联系人张明，学号2023012345。"
    spans = [Span(text.index(value), text.index(value) + len(value), value, category)
             for value, category in [("张明", "PERSON_NAME"), ("2023012345", "STUDENT_ID")]]
    seg = Segment("s", text, 0, len(text), spans)
    out = process_segment(seg, Decision("s", Action.GENERALIZE, []), "s", [], MappingTable())
    assert "张明" not in out and "2023012345" not in out and "2026年10月" in out
    assert "某同学" in out and "学号已隐藏" in out


def test_api_rejects_unknown_task():
    response = TestClient(app).post("/api/preview", json={
        "identity": "student_leader", "task": "version", "recipient": "external_model",
        "custom_text": "公开活动"})
    assert response.status_code == 400


def test_api_task_description_is_forwarded(monkeypatch):
    import llm_shield.server as server
    received = []
    def preview(req):
        received.append(req.user_instruction)
        return SimpleNamespace(to_dict=lambda: {"ok": True})
    monkeypatch.setattr(server, "preview_only", preview)
    response = TestClient(app).post("/api/preview", json={
        "identity": "student_leader", "task": "meeting_minutes", "recipient": "external_model",
        "custom_text": "公开活动", "task_description": "保留责任对应"})
    assert response.status_code == 200 and received == ["保留责任对应"]
