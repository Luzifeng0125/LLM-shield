import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from llm_shield import api_check
from llm_shield.integrations import ModelGateway
from llm_shield.m7_egress import llm_client, native_gateway
from llm_shield.server import app


@pytest.fixture
def gateway(monkeypatch, tmp_path):
    path = tmp_path / "settings.yaml"
    monkeypatch.setenv("SHIELD_INTEGRATIONS_CONFIG", str(path))
    monkeypatch.setenv("TEST_MODEL_KEY", "synthetic-key")
    monkeypatch.setenv("SHIELD_MODEL_ROUTE", "primary")
    monkeypatch.setattr(native_gateway, "DATABASE", tmp_path / "usage.sqlite3")
    target = {"base_url": "https://first.invalid/v1", "model": "synthetic",
              "key_env": "TEST_MODEL_KEY", "disclosure_scope": "approved",
              "input_price": 1000000, "output_price": 2000000}
    config = {"enabled": True, "monthly_budget": 100000, "requests_per_minute": 30,
              "targets": {"first": target, "second": {**target, "base_url": "https://second.invalid/v1"}},
              "routes": {"primary": {"targets": ["first", "second"], "disclosure_scope": "approved"}}}
    settings = {"mode": "real", "provider": "shield", "route": "primary"}
    monkeypatch.setattr(llm_client, "llm_settings", lambda: settings)

    def save():
        path.write_text(yaml.safe_dump({"model_gateway": config}), encoding="utf-8")

    save()
    return config, save, settings


def mock_http(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))


def answer(usage=True):
    data = {"choices": [{"message": {"content": "公开回答"}}]}
    if usage:
        data["usage"] = {"prompt_tokens": 10, "completion_tokens": 5}
    return httpx.Response(200, json=data)


def test_native_gateway_normal_entry_falls_back_and_accounts(monkeypatch, gateway):
    calls = []
    messages = [{"role": "user", "content": "公开材料"}]

    def handler(request):
        calls.append(request)
        assert json.loads(request.content)["messages"] == messages
        return httpx.Response(503) if request.url.host == "first.invalid" else answer()

    mock_http(monkeypatch, handler)
    assert llm_client.configuration_status(gateway[2]) == "configuration_only"
    assert llm_client.chat_messages_with_fallback(messages) == {
        "text": "公开回答", "engine": "real", "error": ""}
    assert len(calls) == 2
    report = native_gateway.usage_summary()
    assert {row["state"] for row in report["attempts"]} == {"unconfirmed", "reported"}
    assert next(row["amount"] for row in report["attempts"] if row["state"] == "reported") == 20
    assert "公开材料" not in native_gateway.DATABASE.read_bytes().decode(errors="ignore")
    assert "synthetic-key" not in str(report)


def test_scope_and_credentials_fail_before_network(monkeypatch, gateway):
    config, save, _ = gateway
    config["targets"]["second"]["disclosure_scope"] = "unapproved"
    with pytest.raises(ValueError):
        ModelGateway.model_validate(config)
    save()
    mock_http(monkeypatch, lambda request: pytest.fail("No network"))
    assert llm_client.chat_messages_with_fallback([{"role": "user", "content": "公开"}])["engine"] == "error"


def test_budget_is_reserved_atomically(gateway):
    config, save, _ = gateway
    config["monthly_budget"] = 10
    save()
    settings, _, revision = native_gateway.configured_route("primary")

    def reserve():
        try:
            native_gateway.reserve(settings, revision, "primary", "first", 10)
            return True
        except llm_client.ConfigurationError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: reserve(), range(2))) == [False, True]


def test_rate_limit_and_missing_usage_hold_budget(monkeypatch, gateway):
    config, save, _ = gateway
    config["requests_per_minute"] = 1
    save()
    calls = []

    def handler(request):
        calls.append(request)
        return answer(usage=False)

    mock_http(monkeypatch, handler)
    messages = [{"role": "user", "content": "公开"}]
    assert llm_client.chat_messages_with_fallback(messages)["engine"] == "real"
    assert llm_client.chat_messages_with_fallback(messages)["engine"] == "error"
    assert len(calls) == 1
    assert native_gateway.usage_summary()["attempts"][0]["state"] == "unconfirmed"


def test_timeout_reservations_survive_a_new_client(monkeypatch, gateway):
    config, save, _ = gateway
    config["monthly_budget"] = 4300
    config["routes"]["primary"]["targets"] = ["first"]
    save()
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("private-response")

    mock_http(monkeypatch, handler)
    messages = [{"role": "user", "content": "公开"}]
    assert llm_client.chat_messages_with_fallback(messages)["engine"] == "error"
    second = llm_client.chat_messages_with_fallback(messages)
    assert second["engine"] == "error" and "预算" in second["error"]
    assert len(calls) == 1
    assert native_gateway.usage_summary()["attempts"][0]["state"] == "unconfirmed"


def test_auth_failure_does_not_try_another_target(monkeypatch, gateway):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, text="private vendor message")

    mock_http(monkeypatch, handler)
    result = llm_client.chat_messages_with_fallback([{"role": "user", "content": "公开"}])
    assert result["engine"] == "error" and "private" not in result["error"]
    assert len(calls) == 1


def test_usage_api_requires_admin_and_diagnostic_uses_native_path(monkeypatch, gateway):
    monkeypatch.setenv("SHIELD_WORKFLOW_ADMIN_TOKEN", "owner" * 10)
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1000))
    assert client.get("/api/models/usage").status_code == 401
    assert client.get("/api/models/usage", headers={"Authorization": "Bearer " + "owner" * 10}).status_code == 200
    mock_http(monkeypatch, lambda request: answer())
    assert api_check.check_connection(gateway[2], connect=True)["connected"]


def test_native_route_with_real_loopback_http(gateway):
    config, save, _ = gateway
    received = []

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            payload = json.dumps({"choices": [{"message": {"content": "本机链路通过"}}],
                                  "usage": {"prompt_tokens": 4, "completion_tokens": 3}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config["routes"]["primary"]["targets"] = ["first"]
        config["targets"]["first"]["base_url"] = f"http://127.0.0.1:{server.server_port}/v1"
        save()
        result = llm_client.chat_messages_with_fallback([{"role": "user", "content": "合成连接检查"}])
        assert result["text"] == "本机链路通过" and result["engine"] == "real"
        assert len(received) == 1
        assert native_gateway.usage_summary()["attempts"][0]["amount"] == 10
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
