from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient

from llm_shield import server
from llm_shield.schema import PipelineResult


def test_recipient_export_is_bound_to_approved_version(monkeypatch):
    def pipeline(request, send_model):
        assert send_model is False
        allowed = request.recipient != "viewer_peer"
        result = PipelineResult(allowed, request.session_id, request.task,
                                request.identity, request.recipient)
        result.original_text = "必须留在受控侧的原稿"
        result.display_text = "老师版内容"
        result.egress_text = request.materials[0].text
        result.boundaries = [{"recipient": request.recipient, "allowed": allowed,
                              "blocked_reason": "接收方无权查看"}]
        return result

    monkeypatch.setattr(server, "run_pipeline", pipeline)
    client = TestClient(server.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50123))
    assert client.get("/recipient-review").status_code == 200
    body = {"identity": "student_leader", "task": "meeting_minutes", "custom_text": "公开稿",
            "recipients": ["viewer_teacher", "viewer_peer", "egress_tool_public"]}
    response = client.post("/api/recipient-review", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    teacher, peer, public = data["versions"]
    assert teacher["text"] == "老师版内容" and not teacher["approval"]
    assert not peer["allowed"] and not peer["text"]
    assert "必须留在受控侧的原稿" not in str(data)
    export = body | {"recipients": ["egress_tool_public"], "review_id": data["review_id"],
                     "approval": public["approval"]}
    response = client.post("/api/recipient-review/export", json=export)
    assert response.status_code == 200
    assert [p.text for p in Document(BytesIO(response.content)).paragraphs] == ["公开稿"]
    changed = export | {"custom_text": "改动后内容"}
    assert client.post("/api/recipient-review/export", json=changed).status_code == 409
    assert client.post("/api/recipient-review/export", json=export | {
        "recipients": ["viewer_teacher"]}).status_code == 409
