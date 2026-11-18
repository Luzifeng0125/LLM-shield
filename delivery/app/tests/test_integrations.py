"""Integration contracts, local-only diagnostics and external side-effect boundaries."""
import json
from uuid import uuid4

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from llm_shield import integration_api as api, integration_guards as guards, integration_tools as tools
from llm_shield import integrations
from llm_shield.m1_access import file_loader, loader
from llm_shield.m7_egress import llm_client
from llm_shield.processing import Analysis
from llm_shield.schema import Action, Decision, Material, Segment, Span
from llm_shield.server import app


@pytest.fixture
def settings(monkeypatch, tmp_path):
    path = tmp_path / "integrations.yaml"
    monkeypatch.setenv("SHIELD_INTEGRATIONS_CONFIG", str(path))

    def write(**values):
        path.write_text(yaml.safe_dump({"version": 1, **values}), encoding="utf-8")

    write()
    return write


def local_client():
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 12345))


def transport(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))


def test_config_is_strict_and_diagnostics_are_local(settings):
    assert local_client().get("/integrations").status_code == 200
    assert local_client().get("/api/integrations").json()["knowledge_sources"] == 0
    remote = TestClient(app, base_url="http://127.0.0.1", client=("192.0.2.1", 12345))
    assert remote.get("/api/integrations").status_code == 403
    settings(unknown=True)
    assert local_client().get("/api/integrations").status_code == 503


def test_optional_implementations_execute_without_network():
    pytest.importorskip("nemoguardrails")
    pytest.importorskip("presidio_analyzer")
    from llm_shield.m2_detect.presidio_adapter import PresidioDetector

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("No network permitted"))
        assert guards.nemo_denial("公开内容", ("绕过权限",)) == ""
        assert guards.nemo_denial("绕过权限", ("绕过权限",))
        config = integrations.Presidio(enabled=True, patterns=[integrations.Pattern(
            name="campus-id", category="STUDENT_ID", regex=r"JNU-[0-9]{8}")])
        spans = PresidioDetector(config).detect("编号 JNU-20260001")
        assert [(s.start, s.end, s.text, s.rule_id) for s in spans] == [
            (3, 15, "JNU-20260001", "campus-id")]


def test_presidio_and_nemo_are_on_the_normal_pipeline(settings, monkeypatch):
    pytest.importorskip("nemoguardrails")
    pytest.importorskip("presidio_analyzer")
    from llm_shield.m2_detect.pipeline import build_detectors, detect_all
    from llm_shield.m7_egress import gateway

    settings(presidio={"enabled": True, "patterns": [
        {"name": "custom-id", "category": "STUDENT_ID", "regex": "JNU-[0-9]{8}"}]},
        nemo={"enabled": True, "deny_phrases": ["绕过权限"]})
    spans = detect_all("编号 JNU-20260001", detectors=build_detectors(use_gliner=False))
    assert any(span.detector == "presidio" and span.text == "JNU-20260001" for span in spans)
    monkeypatch.setattr(gateway, "inspect_payload", lambda *a, **k: {
        "leaked": False, "leak_hits": [], "leaked_categories": []})
    guard = gateway.EgressGateway()
    assert guard.precheck("external_model", "student_leader", "公开稿", task_key="meeting_minutes")["allowed"]
    assert not guard.precheck("external_model", "student_leader", "绕过权限", task_key="meeting_minutes")["allowed"]


@pytest.mark.parametrize("reply,allowed", [
    ({"action": "enforce", "flagged": False}, True),
    ({"action": "enforce", "flagged": True}, False),
    ({"action": "detect", "flagged": False}, False),
    ({"action": "enforce", "flagged": 0}, False),
    ({}, False),
])
def test_lakera_is_explicit_and_fail_closed(settings, monkeypatch, reply, allowed):
    settings(lakera={"enabled": True, "approved_for_checked_content": True})
    monkeypatch.setenv("SHIELD_LAKERA_API_KEY", "synthetic-key")
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == "https://api.lakera.ai/v2/guard"
        assert json.loads(request.content) == {"messages": [{"role": "user", "content": "公开材料"}]}
        return httpx.Response(200, json=reply)

    transport(monkeypatch, handler)
    assert bool(guards.extra_denial("公开材料", "external_model")) is not allowed
    assert len(requests) == 1
    assert not guards.extra_denial("仅供本机预检的材料", "egress_tool_public", local_only=True)
    assert not guards.extra_denial("获准恢复的姓名", "viewer_teacher")
    assert len(requests) == 1
    settings(lakera={"enabled": True})
    assert guards.extra_denial("公开材料", "external_model")
    assert len(requests) == 1


def test_local_payload_denial_never_calls_commercial_screen(settings, monkeypatch):
    from llm_shield.m7_egress import gateway

    monkeypatch.setattr(gateway, "inspect_payload", lambda *a, **k: {
        "leaked": True, "leaked_categories": ["PHONE"], "n_hits": 1})
    monkeypatch.setattr(gateway, "extra_denial", lambda *a, **k: pytest.fail("Local check must run first"))
    assert not gateway.EgressGateway().precheck("external_model", "student_leader", "test",
                                               task_key="meeting_minutes")["allowed"]


def test_litellm_only_uses_approved_alias_and_endpoint(settings, monkeypatch):
    settings(litellm={"enabled": True, "approved_models": ["approved"]})
    value = {"mode": "real", "provider": "litellm", "api_key": "virtual-key",
             "base_url": "http://127.0.0.1:4000/v1", "model": "approved", "timeout": 5}
    monkeypatch.setattr(llm_client, "llm_settings", lambda: value)
    assert llm_client.get_llm_client().model == "approved"
    value["model"] = "other-vendor"
    with pytest.raises(llm_client.ConfigurationError):
        llm_client.get_llm_client()


def test_dify_returns_only_processed_content_and_rechecks_sources(settings, monkeypatch, tmp_path):
    monkeypatch.setattr(loader, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(file_loader, "UPLOAD_DIR", tmp_path)
    material = file_loader.parse_uploads("私密姓名\n公开活动纪要".encode(), "private-name.txt",
                                        allowed_purposes=["meeting_minutes"])[0]
    binding = {"identity": "student_leader", "task": "meeting_minutes",
               "token_env": "TEST_DIFY_TOKEN", "doc_ids": [material.doc_id]}
    settings(knowledge={"kb": binding})
    monkeypatch.setenv("TEST_DIFY_TOKEN", "x" * 40)

    def analysis(*args, **kwargs):
        text = "私密姓名\n公开活动纪要"
        span = Span(0, 4, "私密姓名", "PERSON_NAME")
        segments = [Segment("a", "私密姓名\n", 0, 5, [span]),
                    Segment("b", "公开活动纪要", 5, len(text))]
        return Analysis(text, [span], segments,
                        [Decision("a", Action.DELETE, ["PERSON_NAME"]),
                         Decision("b", Action.RETAIN, [])], {})

    monkeypatch.setattr(api, "analyze", analysis)
    monkeypatch.setattr(api.EgressGateway, "precheck", lambda *a, **k: {"allowed": True})
    client = local_client()
    body = {"knowledge_id": "kb", "query": "活动纪要",
            "retrieval_setting": {"top_k": 3, "score_threshold": 0}}
    endpoint = "/api/integrations/dify/retrieval"
    assert client.post(endpoint, json=body).status_code == 401
    headers = {"Authorization": "Bearer " + "x" * 40}
    with monkeypatch.context() as patch:
        patch.setenv("SHIELD_DETECTOR_MODE", "dictionary_test")
        assert client.post(endpoint, json=body, headers=headers).status_code == 409
    reply = client.post(endpoint, json=body, headers=headers)
    assert reply.status_code == 200, reply.text
    assert reply.headers["cache-control"] == "no-store"
    record, = reply.json()["records"]
    assert "公开活动纪要" in record["content"]
    assert "私密姓名" not in reply.text and "private-name" not in reply.text
    assert client.post(endpoint, json={**body, "identity": "other"}, headers=headers).status_code == 422
    assert client.post(endpoint, json={**body, "metadata_condition": {"conditions": [1]}},
                       headers=headers).status_code == 422
    assert file_loader.delete_upload(material.doc_id)
    assert client.post(endpoint, json=body, headers=headers).status_code == 410


def test_dify_checks_only_selected_chunks_with_their_original_context(settings, monkeypatch):
    settings(knowledge={"kb": {"identity": "student_leader", "task": "meeting_minutes",
                               "token_env": "TEST_DIFY_TOKEN", "doc_ids": ["one", "two"]}})
    monkeypatch.setenv("TEST_DIFY_TOKEN", "x" * 40)
    monkeypatch.setattr(api, "load_material", lambda key: Material(key, "uploaded", "", key))
    original = Span(0, 2, "张明", "PERSON_NAME")
    monkeypatch.setattr(api, "_approved_content", lambda material, binding: (
        "拟招聘工作方案，人员甲负责" if material.doc_id == "one" else "公开招聘公告",
        {"人员甲"} if material.doc_id == "one" else set(), [original], set()))
    checked = []

    def precheck(self, recipient, identity, content, spans, allowed, **kwargs):
        checked.append(content)
        assert self.generated_pseudonyms == {"人员甲"}
        assert spans == [original]
        return {"allowed": True}

    monkeypatch.setattr(api.EgressGateway, "precheck", precheck)
    reply = local_client().post("/api/integrations/dify/retrieval", json={
        "knowledge_id": "kb", "query": "招聘工作", "retrieval_setting": {"top_k": 1, "score_threshold": 0}},
        headers={"Authorization": "Bearer " + "x" * 40})
    assert reply.status_code == 200, reply.text
    assert [record["content"] for record in reply.json()["records"]] == checked == ["拟招聘工作方案，人员甲负责"]


def test_confirmed_tool_call_is_not_repeated(settings, monkeypatch, tmp_path):
    monkeypatch.setenv("SHIELD_WORKFLOW_ADMIN_TOKEN", "owner" * 10)
    monkeypatch.setenv("TEST_TOOL_TOKEN", "receiver" * 5)
    monkeypatch.setattr(tools, "DATABASE", tmp_path / "events.sqlite3")
    settings(tools={"send": {"endpoint": "https://example.invalid/receive", "token_env": "TEST_TOOL_TOKEN",
                            "identity": "student_leader", "task": "meeting_minutes",
                            "recipient": "egress_tool_public"}})
    checks = []

    def check(self, recipient, identity, text, **kwargs):
        checks.append(text)
        return {"allowed": text != "SECRET", "reason": "blocked"}

    monkeypatch.setattr(tools.EgressGateway, "precheck", check)
    client = local_client()
    headers = {"Authorization": "Bearer " + "owner" * 10}
    body = {"tool_id": "send", "text": "公开交付稿", "event_id": str(uuid4())}
    endpoint = "/api/integrations/tools"
    preview = client.post(endpoint + "/preview", json=body, headers=headers)
    assert preview.status_code == 200, preview.text
    approval = preview.json()
    execution = {**body, "approval": approval["approval"], "expires_at": approval["expires_at"]}
    sends = []

    def handler(request):
        sends.append(request)
        assert request.headers["idempotency-key"] == body["event_id"]
        assert json.loads(request.content)["text"] == body["text"]
        return httpx.Response(200, text="已收到")

    with monkeypatch.context() as patch:
        transport(patch, handler)
        with monkeypatch.context() as dictionary:
            dictionary.setenv("SHIELD_DETECTOR_MODE", "dictionary_test")
            assert client.post(endpoint + "/execute", json=execution, headers=headers).status_code == 409
            assert not sends
        assert client.post(endpoint + "/execute", json={**execution, "text": "modified"},
                           headers=headers).status_code == 409
        assert client.post(endpoint + "/execute", json=execution, headers=headers).json()["completed"]
        assert client.post(endpoint + "/execute", json=execution, headers=headers).json()["replayed"]
    assert len(sends) == 1 and "已收到" in checks
    assert "公开交付稿" not in (tmp_path / "events.sqlite3").read_bytes().decode(errors="ignore")


def test_uncertain_tool_result_blocks_retry(settings, monkeypatch, tmp_path):
    monkeypatch.setenv("SHIELD_WORKFLOW_ADMIN_TOKEN", "owner" * 10)
    monkeypatch.setenv("TEST_TOOL_TOKEN", "receiver" * 5)
    monkeypatch.setattr(tools, "DATABASE", tmp_path / "events.sqlite3")
    settings(tools={"send": {"endpoint": "https://example.invalid/receive", "token_env": "TEST_TOOL_TOKEN",
                            "identity": "student_leader", "task": "meeting_minutes",
                            "recipient": "egress_tool_public"}})
    monkeypatch.setattr(tools, "_check", lambda *a: None)
    client = local_client()
    headers = {"Authorization": "Bearer " + "owner" * 10}
    body = {"tool_id": "send", "text": "公开交付稿", "event_id": str(uuid4())}
    approval = client.post("/api/integrations/tools/preview", json=body, headers=headers).json()
    body["approval"] = approval["approval"]
    body["expires_at"] = approval["expires_at"]
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("upstream-body-secret")

    transport(monkeypatch, handler)
    for _ in range(2):
        response = client.post("/api/integrations/tools/execute", json=body, headers=headers)
        assert response.status_code == 409
        assert "upstream-body-secret" not in response.text
    assert len(calls) == 1
