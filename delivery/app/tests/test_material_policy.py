import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from llm_shield import chat, material_policy, processing, server
from llm_shield.m1_access import file_loader, loader
from llm_shield.m7_egress import gateway
from llm_shield.schema import Material


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(file_loader, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(loader, "UPLOAD_DIR", tmp_path)
    return tmp_path


def test_upload_defaults_to_expiring_current_purpose(uploads):
    response = TestClient(server.app).post("/api/upload", data={"task": "activity_stats"},
        files={"file": ("synthetic.txt", "虚构活动记录".encode(), "text/plain")})
    assert response.status_code == 200
    data = response.json()
    material = loader.load_material(data["doc_id"])
    assert material.allowed_purposes == ["activity_stats"]
    assert material.storage_mode == "temporary"
    assert material.expires_at - material.created_at == 1800


def test_expired_material_not_readable_or_listed_and_cleanup_preserves_other_files(uploads):
    for mode in ("temporary", "library", "legacy"):
        file_loader.save_upload(Material(mode, "uploaded", mode, "虚构材料",
            storage_mode=mode, expires_at=1 if mode == "temporary" else None))
    with pytest.raises(FileNotFoundError):
        loader.load_material("temporary")
    assert "temporary" not in [m["doc_id"] for m in loader.list_materials(False)]
    assert file_loader.cleanup_expired_uploads() == 1
    assert (uploads / "library.json").exists() and (uploads / "legacy.json").exists()


def test_other_task_is_rejected_before_model_or_external_processing():
    source = Material("source", "uploaded", "", "虚构材料", allowed_purposes=["activity_stats"])
    model = Mock(side_effect=AssertionError("must not load model"))
    with pytest.raises(processing.ProcessingFailure, match="未获准"):
        processing.analyze("student_leader", "meeting_minutes", "external_model", [source], model_loader=model)
    model.assert_not_called()


def test_retrieval_and_local_statistics_cannot_bypass_source_purpose():
    session = chat.ChatStore().create("student_leader", "activity_stats")
    source = Material("table", "uploaded", "", "", [{"专业": "计算机"}], ["专业"],
                      allowed_purposes=["meeting_minutes"])
    question = Material("chat-input", "uploaded", "", "计算机专业有多少人")
    assert chat.send_turn(session, [source, question])["paused"]
    assert not session.messages


def test_local_statistics_do_not_reappear_in_next_external_history(monkeypatch):
    monkeypatch.setattr(chat, "get_model", lambda: SimpleNamespace(available=True))
    monkeypatch.setattr(chat, "necessity_scorer", lambda *a, **k: {"DELETE": 1.0})
    calls = []
    def generate(messages):
        calls.append(messages)
        return {"text": "请补充公开的总结要点。", "engine": "mock", "error": ""}
    monkeypatch.setattr(gateway, "chat_messages_with_fallback", generate)
    session = chat.ChatStore().create("student_leader", "activity_stats")
    result = chat.send_turn(session, [
        Material("table", "uploaded", "", "", [{"专业": "网络空间安全"}], ["专业"]),
        Material("chat-input", "uploaded", "", "帮我统计网络空间安全专业有多少人")])
    assert result["engine"] == "local"
    assert chat.send_turn(session, [Material("chat-input", "uploaded", "", "请提供总结提纲。")])["ok"]
    assert len(calls) == 1 and "匹配 1 条记录" not in str(calls)
    assert "本机全表精确统计" not in str(calls)
    assert len(session.messages) == 4


def test_source_expiry_invalidates_session_private_state():
    store = chat.ChatStore()
    session = store.create("student_leader", "meeting_minutes")
    session.material_policies["expired"] = Material("expired", "uploaded", "", "", expires_at=1)
    session.messages = [{"role": "user", "content": "旧的派生材料"}]
    with pytest.raises(chat.ChatError):
        store.get(session.session_id)
    assert not session.messages and not session.material_policies


def test_source_deletion_invalidates_derived_history(uploads, monkeypatch):
    store = chat.ChatStore()
    monkeypatch.setattr(server, "STORE", store)
    session = store.create("student_leader", "meeting_minutes")
    source = Material("source", "uploaded", "", "虚构材料")
    file_loader.save_upload(source)
    session.material_policies["source"] = source
    session.messages = [{"role": "user", "content": "派生记录"}]
    assert TestClient(server.app).delete("/api/upload/source").json()["ok"]
    assert not session.messages and not session.active
    assert not (uploads / "source.json").exists()


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "2030"])
def test_invalid_expiry_is_not_treated_as_unlimited(value):
    assert material_policy.is_expired(value)
