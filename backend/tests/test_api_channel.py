"""API channel (0.5.0): an OpenAI-compatible member streams from a local mock server, in the same room as a
web member. Only a loopback mock is called; no real or paid API. The key goes in the header and nowhere else."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers import CATALOG, ollama_models

SECRET = "sk-local-test-7f3a9c"


class MockOpenAI(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *args):  # 安静
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        MockOpenAI.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in ("本地", "模型", "答复。"):
            chunk = {"choices": [{"delta": {"content": piece}}]}
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.02)
        usage = {"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 3}}
        self.wfile.write(f"data: {json.dumps(usage)}\n\ndata: [DONE]\n\n".encode())

    def do_GET(self):  # noqa: N802 - 假的 Ollama /api/tags
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"models": [{"name": "qwen2.5:0.5b"}]}).encode())


@pytest.fixture()
def mock_server():
    MockOpenAI.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockOpenAI)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_presets_cover_common_openai_compatible_services():
    by = {item["provider"]: item for item in CATALOG}
    for provider in ("openai", "deepseek", "qwen", "siliconflow", "openrouter", "ollama", "openai_compatible"):
        assert provider in by
    assert by["siliconflow"]["base_url"] == "https://api.siliconflow.cn/v1"
    assert by["qwen"]["base_url"].endswith("/compatible-mode/v1")
    assert by["siliconflow"]["paid"] is True


@pytest.mark.asyncio
async def test_ollama_discovery_is_loopback_only(mock_server):
    found = await ollama_models(mock_server)
    assert found["ok"] is True and found["models"] == ["qwen2.5:0.5b"]
    remote = await ollama_models("https://example.com")
    assert remote["ok"] is False and "本机" in remote["detail"]


def test_api_member_streams_next_to_a_web_member_and_key_stays_local(tmp_path, mock_server, caplog):
    caplog.set_level("DEBUG")
    app = create_app(str(tmp_path / "room.db"), str(tmp_path / "secrets.json"))
    with TestClient(app) as client:
        _mixed_room(client, tmp_path, mock_server, caplog)


def _mixed_room(client, tmp_path, mock_server, caplog):
    assert client.put("/api/secrets", json={"name": "OPENAI_COMPATIBLE_API_KEY", "value": SECRET}).status_code == 200
    room = client.post("/api/sessions", json={"title": "混合", "mode": "independent", "max_rounds": 1, "max_seconds": 30}).json()
    api_member = client.post(
        f"/api/sessions/{room['id']}/members",
        json={"nickname": "本地接口", "role_name": "工程师", "persona": "", "provider": "openai_compatible",
              "model_id": "mock-model", "api_base": f"{mock_server}/v1", "api_key_env": "OPENAI_COMPATIBLE_API_KEY"},
    )
    assert api_member.status_code == 200, api_member.text
    web = client.post(
        f"/api/sessions/{room['id']}/members/web",
        json={"nickname": "网页甲", "role_name": "读者", "persona": "", "provider": "web", "model_id": "web:fixture",
              "web_site": "fixture", "web_origin": "http://127.0.0.1:43124/fixture/chat", "web_tab_key": "mix-tab", "web_auto": True},
    )
    assert web.status_code == 200, web.text
    code = client.post("/api/ext/code").json()["code"]
    token = client.post("/api/ext/pair", json={"code": code}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/ext/tabs", headers=headers, json={"tabs": [{"tab_key": "mix-tab", "origin": "http://127.0.0.1:43124", "alive": True}]})

    assert client.post(f"/api/sessions/{room['id']}/messages", json={"content": "各用一句话介绍自己"}).status_code == 200
    job = None
    for _ in range(100):
        client.post("/api/ext/tabs", headers=headers, json={"tabs": [{"tab_key": "mix-tab", "origin": "http://127.0.0.1:43124", "alive": True}]})
        jobs = client.get("/api/ext/jobs", headers=headers).json()["jobs"]
        if jobs:
            job = jobs[0]
            break
        time.sleep(0.05)
    assert job is not None, "web member never got a job"
    result = client.post("/api/ext/jobs/result", headers=headers, json={
        "request_id": job["request_id"], "run_id": job.get("run_id") or job.get("run_token") or "", "group_id": job.get("group_id") or "",
        "member_id": job["member_id"], "context_version": job["context_version"], "status": "complete",
        "page_url": "http://127.0.0.1:43124/fixture/chat", "text": "网页成员的答复。",
    })
    assert result.status_code == 200
    for _ in range(100):
        session = client.get(f"/api/sessions/{room['id']}").json()["session"]
        if session["status"] not in {"running", "paused"}:
            break
        time.sleep(0.05)
    messages = client.get(f"/api/sessions/{room['id']}/messages").json()
    rows = messages if isinstance(messages, list) else messages.get("messages", [])
    ai = {m["nickname"]: m for m in rows if m["author_type"] == "ai" and not m.get("is_summary")}
    assert ai["本地接口"]["content"] == "本地模型答复。"
    assert ai["本地接口"]["status"] == "complete"
    assert ai["网页甲"]["content"] == "网页成员的答复。"
    # 走的是本机模拟服务：流式、带密钥头，且只调用了一次。
    assert len(MockOpenAI.seen) == 1
    call = MockOpenAI.seen[0]
    assert call["path"] == "/v1/chat/completions" and call["body"]["stream"] is True and call["body"]["model"] == "mock-model"
    assert call["auth"] == f"Bearer {SECRET}"
    # 密钥不出现在前端接口、数据库、日志里。
    assert SECRET not in client.get("/api/secrets").text
    assert SECRET not in json.dumps(rows, ensure_ascii=False)
    assert SECRET.encode() not in (tmp_path / "room.db").read_bytes()
    assert SECRET not in caplog.text
