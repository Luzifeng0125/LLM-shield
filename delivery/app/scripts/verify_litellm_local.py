"""Exercise an installed LiteLLM proxy against a synthetic loopback-only upstream."""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import yaml


def stop(process):
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            process.terminate()
        process.wait(timeout=10)


def main():
    requests = []

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            answer = {"id": "synthetic", "object": "chat.completion", "created": 1,
                      "model": "synthetic", "choices": [{"index": 0, "finish_reason": "stop",
                      "message": {"role": "assistant", "content": "公开连接测试通过"}}],
                      "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7}}
            data = json.dumps(answer).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    token = "sk-" + secrets.token_urlsafe(32)
    env = {**os.environ, "LITELLM_LOCAL_MODEL_COST_MAP": "True", "LITELLM_TELEMETRY": "False",
           "DO_NOT_TRACK": "1", "LITELLM_MASTER_KEY": token}
    process = None
    try:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            settings = {"model_list": [{"model_name": "shield-primary", "litellm_params": {
                "model": "openai/synthetic", "api_base": f"http://127.0.0.1:{server.server_port}/v1",
                "api_key": "synthetic-local-only"}}],
                "litellm_settings": {"num_retries": 0, "turn_off_message_logging": True},
                "general_settings": {"master_key": "os.environ/LITELLM_MASTER_KEY"}}
            config = directory / "proxy.yaml"
            config.write_text(yaml.safe_dump(settings), encoding="utf-8")
            with (directory / "proxy.log").open("wb") as log, ExitStack() as cleanup:
                process = subprocess.Popen([sys.executable, "-c",
                                            "from litellm_cli.main import proxy_server; proxy_server()",
                                            "--host", "127.0.0.1", "--port", str(port),
                                            "--config", str(config)], stdout=log, stderr=log,
                                           env=env, cwd=temp)
                cleanup.callback(stop, process)
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=10) as client:
                    for _ in range(90):
                        if process.poll() is not None:
                            raise RuntimeError("LiteLLM exited before becoming ready")
                        try:
                            if client.get("/health/liveliness").is_success:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.5)
                    else:
                        raise RuntimeError("LiteLLM startup timed out")
                    messages = [{"role": "user", "content": "固定公开连接测试"}]
                    response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer " + token},
                                           json={"model": "shield-primary", "messages": messages})
                    response.raise_for_status()
                    assert response.json()["choices"][0]["message"]["content"] == "公开连接测试通过"
                    assert len(requests) == 1, "Expected one upstream call"
                    assert requests[0]["messages"] == messages, repr(requests[0]["messages"])
                stop(process)
                process = None
        print("Actual LiteLLM proxy and synthetic loopback upstream verified. No paid model call.")
    finally:
        if process is not None:
            stop(process)
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
