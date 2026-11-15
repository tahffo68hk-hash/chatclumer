"""Phone / LAN access: backend + bridge stay loopback-only; the frontend gate has its own node tests."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app, is_local_client

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
@pytest.mark.parametrize("client_ip", ["192.168.1.23", "100.101.2.3", "10.0.0.8", "172.30.0.9"])
async def test_backend_and_bridge_refuse_non_loopback_clients(tmp_path, client_ip):
    app = create_app(str(tmp_path / "chat.db"), str(tmp_path / "secrets.json"))
    transport = ASGITransport(app=app, client=(client_ip, 5555))
    async with AsyncClient(transport=transport, base_url="http://x") as client:
        for path in ("/api/health", "/api/sessions", "/api/ext/code", "/api/ext/poll"):
            res = await client.get(path)
            assert res.status_code == 403, path
            assert res.json()["detail"] == "backend is loopback-only"
        # 伪造 X-Forwarded-For 也没用
        res = await client.get("/api/health", headers={"X-Forwarded-For": "127.0.0.1"})
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_backend_still_serves_loopback(tmp_path):
    app = create_app(str(tmp_path / "chat.db"), str(tmp_path / "secrets.json"))
    for ip in ("127.0.0.1", "::1"):
        transport = ASGITransport(app=app, client=(ip, 5555))
        async with AsyncClient(transport=transport, base_url="http://x") as client:
            res = await client.get("/api/health")
            assert res.status_code == 200


def test_is_local_client():
    assert is_local_client("127.0.0.1") and is_local_client("::1") and is_local_client("::ffff:127.0.0.1")
    assert not is_local_client("192.168.1.2") and not is_local_client(None) and not is_local_client("0.0.0.0")


def test_start_scripts_keep_backend_on_loopback_even_in_lan_mode():
    sh = (ROOT / "scripts" / "start.sh").read_text(encoding="utf-8")
    ps = (ROOT / "scripts" / "start.ps1").read_text(encoding="utf-8")
    assert re.search(r"uvicorn\" app\.main:app --app-dir backend --host 127\.0\.0\.1 --port \"\$BACK_PORT\"", sh)
    assert '"--host","127.0.0.1","--port","43124"' in ps
    assert "0.0.0.0" not in re.search(r"uvicorn.*", sh).group(0)
    # 前端经由带认证的自定义服务器启动，而不是裸的 next dev
    assert "frontend/server/index.mjs" in sh and "next\" dev" not in sh
    assert "server\\index.mjs" in ps
    pkg = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert all("server/index.mjs" in pkg["scripts"][k] for k in ("dev", "start"))
    assert "127.0.0.1" in pkg["scripts"]["dev"]


def test_token_file_is_gitignored():
    assert "backend/data/mobile_token.json" in (ROOT / ".gitignore").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_frontend_mobile_gate_node_suite():
    out = subprocess.run(
        ["node", "--test", "server/mobile-auth.test.mjs"],
        cwd=ROOT / "frontend", capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stdout[-3000:] + out.stderr[-2000:]
    assert re.search(r"# fail 0", out.stdout)
