"""The roster is never part of the notice generation request."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from llm_shield import notice, pipeline, server
from llm_shield.chat import ChatError, ChatStore
from llm_shield.m2_detect.pipeline import DetectionError
from llm_shield.m7_egress import gateway, llm_client
from llm_shield.schema import Segment, Span


@pytest.fixture
def client():
    return TestClient(server.app)


def test_local_review_never_calls_generation(client, monkeypatch):
    outside = Mock(side_effect=AssertionError("No generation during local review"))
    monkeypatch.setattr(gateway, "chat_with_fallback", outside)
    monkeypatch.setattr(server, "run_pipeline", outside)
    result = client.post("/api/notice/review", json={"text": "测试电话13812345678，邮箱demo@example.com"})
    assert result.status_code == 200
    data = result.json()
    assert data["local_only"] and not data["external_model_called"]
    assert data["counts"]["PHONE"] == data["counts"]["EMAIL"] == 1
    outside.assert_not_called()


def test_private_review_state_cannot_reach_subsequent_draft(client, monkeypatch):
    roster = "本地未识别私密内容。"
    monkeypatch.setattr(notice, "detect_and_segment", lambda text: ([], []))
    assert client.post("/api/notice/review", json={"text": roster}).status_code == 200
    requests = []
    def run(req, send_model=True):
        requests.append(req)
        return SimpleNamespace(to_dict=lambda: {"ok": True})
    monkeypatch.setattr(server, "run_pipeline", run)
    response = client.post("/api/notice/draft", json={"activity_name": "校园科技日", "items": ["check_in"]})
    assert response.status_code == 200
    request = requests[0]
    assert request.task == "activity_notice" and len(request.materials) == 1
    assert roster not in repr(request) and "签到" in request.materials[0].text


@pytest.mark.parametrize("key", ["text", "custom_text", "roster", "doc_ids", "messages", "task_description", "recipient"])
def test_draft_rejects_private_material_channels(client, monkeypatch, key):
    run = Mock(side_effect=AssertionError("invalid schema"))
    monkeypatch.setattr(server, "run_pipeline", run)
    response = client.post("/api/notice/draft", json={"activity_name": "校园科技日", "items": ["check_in"], key: "private"})
    assert response.status_code == 422
    run.assert_not_called()


@pytest.mark.parametrize("items", [[], ["unknown"], ["check_in", "check_in"]])
def test_invalid_items_do_not_generate(client, monkeypatch, items):
    run = Mock(side_effect=AssertionError("invalid items"))
    monkeypatch.setattr(server, "run_pipeline", run)
    response = client.post("/api/notice/draft", json={"activity_name": "校园科技日", "items": items})
    assert response.status_code in (400, 422)
    run.assert_not_called()


@pytest.mark.parametrize("title", [" ", "活动\n名单", "活动\u2028内容", "活动\x00"])
def test_invalid_title_does_not_generate(client, monkeypatch, title):
    monkeypatch.setattr(server, "run_pipeline", Mock(side_effect=AssertionError("invalid title")))
    assert client.post("/api/notice/draft", json={"activity_name": title, "items": ["check_in"]}).status_code == 400


def test_generic_generation_paths_cannot_accept_notice_rosters(client):
    for path in ("/api/run", "/api/preview"):
        response = client.post(path, json={"identity": "student_leader", "task": "activity_notice",
                              "recipient": "external_model", "custom_text": "名单"})
        assert response.status_code == 400
    with pytest.raises(ChatError, match="通知入口"):
        ChatStore().create("student_leader", "activity_notice")


def test_local_detection_failure_is_generic_and_no_generation(client, monkeypatch):
    def fail(text):
        raise DetectionError("private exception")
    monkeypatch.setattr(notice, "detect_and_segment", fail)
    response = client.post("/api/notice/review", json={"text": "测试材料"})
    assert response.status_code == 503 and "private exception" not in response.text


def test_review_requires_read_permission(client):
    response = client.post("/api/notice/review", json={"identity": "unknown", "text": "测试材料"})
    assert response.status_code == 403


def test_mock_notice_only_uses_selected_items():
    brief = notice.notice_brief("校园科技日", ["join_group"])
    text = llm_client.MockLLM().chat(gateway.SYSTEM_PROMPTS["activity_notice"], brief)
    assert "校园科技日" in text and notice.NOTICE_ITEMS["join_group"] in text
    assert notice.NOTICE_ITEMS["check_in"] not in text and "模拟" in text
    assert "另行通知" in text


def test_notice_keeps_model_pause_and_does_not_substitute_action(monkeypatch):
    monkeypatch.setattr(pipeline, "get_model", lambda: SimpleNamespace(available=True))
    monkeypatch.setattr(pipeline, "necessity_scorer", lambda *a, **k: {"PAUSE": 1.0})
    span = Span(0, 2, "张三", "PERSON_NAME")
    monkeypatch.setattr(pipeline, "detect_and_segment", lambda *a, **k: ([span], [Segment("s", "张三", 0, 2, [span])]))
    outside = Mock(side_effect=AssertionError("model paused"))
    monkeypatch.setattr(pipeline, "EgressGateway", outside)
    result = pipeline.run_pipeline(notice.notice_request("student_leader", "校园科技日", ["check_in"]))
    assert result.paused and not result.ok
    outside.assert_not_called()


def test_unsafe_generated_notice_is_not_displayed(monkeypatch):
    monkeypatch.setattr(pipeline, "get_model", lambda: SimpleNamespace(available=True))
    monkeypatch.setattr(gateway, "chat_with_fallback", lambda *a, **k: {"text": "电话13812345678", "engine": "mock", "error": ""})
    result = pipeline.run_pipeline(notice.notice_request("student_leader", "校园科技日", ["check_in"]))
    assert not result.display_text and not result.egress_text
    assert all(b["blocked"] for b in result.boundaries[1:])
