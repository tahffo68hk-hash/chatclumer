import os
import subprocess

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.secrets import private_file_is_owner_only


async def wait_terminal(client, sid):
    status = None
    for _ in range(80):
        payload = (await client.get(f"/api/sessions/{sid}")).json()
        status = payload["session"]
        if status["status"] in {"finished", "stopped", "failed"}:
            return status
        await asyncio_sleep()
    raise AssertionError(status)


async def asyncio_sleep():
    import asyncio

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_demo_room_flow_masks_secrets_and_does_not_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_CHUNK_DELAY", "0")
    app = create_app(str(tmp_path / "chat.db"), str(tmp_path / "secrets.json"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = (
            await client.post(
                "/api/sessions",
                json={"title": "试用", "template": "demo", "cross_delay_ms": 0, "max_seconds": 30},
            )
        ).json()
        sid = created["id"]
        detail = (await client.get(f"/api/sessions/{sid}")).json()
        models = {item["model_id"] for item in detail["members"]}
        nicks = {item["nickname"] for item in detail["members"]}
        assert models == {"demo-synthesizer-v1"}
        assert nicks == {"林知秋", "周衡", "苏晚"}
        rejected = await client.post(
            f"/api/sessions/{sid}/members",
            json={"nickname": "伪装", "role_name": "假", "provider": "demo", "model_id": "gpt-4o"},
        )
        assert rejected.status_code == 400
        secret = await client.put("/api/secrets", json={"name": "OPENAI_API_KEY", "value": "sk-local-only-value"})
        assert secret.status_code == 200
        assert "sk-local-only-value" not in secret.text
        secrets_file = tmp_path / "secrets.json"
        detail = ""
        if os.name == "nt":
            from app.secrets import _current_user_sid, _windows_dacl_sddl

            listing = subprocess.run(["icacls", str(secrets_file)], capture_output=True, text=True, errors="replace").stdout
            detail = f"sddl={_windows_dacl_sddl(secrets_file)!r} sid={_current_user_sid()!r} icacls={listing!r}"
        assert private_file_is_owner_only(secrets_file), detail
        status = (await client.get("/api/secrets/status")).json()
        assert status["secrets"]
        assert "sk-local-only-value" not in json_text(status)
        posted = await client.post(
            f"/api/sessions/{sid}/messages",
            json={"content": "我们现在该不该把这件事做成群聊？", "mode": "free_chat"},
        )
        assert posted.status_code == 200
        final = await wait_terminal(client, sid)
        assert final["status"] == "finished"
        runs_before = app.state.db.count_runs(sid)
        messages = (await client.get(f"/api/sessions/{sid}/messages")).json()
        ai = [m for m in messages if m["author_type"] == "ai" and m["status"] == "complete" and not m["is_summary"]]
        assert len(ai) >= 4
        cross = [m for m in ai if m["phase"] == "cross"]
        assert cross
        assert cross[0]["reply_to_id"]
        assert "我读了 @" in cross[0]["content"]
        assert all(m["is_demo"] for m in ai)
        assert all("非真实模型" in m["content"] for m in ai)
        summaries = [m for m in messages if m["is_summary"]]
        assert len(summaries) == 1
        for heading in ("主要结论", "共识", "分歧", "未验证事实", "最推荐建议", "下一步行动"):
            assert heading in summaries[0]["content"]
        again = (await client.get(f"/api/sessions/{sid}")).json()["session"]
        assert again["status"] == "finished"
        assert again["run_token"] == final["run_token"]
        assert app.state.db.count_runs(sid) == runs_before
        qq = await client.post("/api/integrations/qq/simulate", json={"session_id": sid, "content": "/status"})
        body = qq.json()
        assert body["external_delivery"] == "BLOCKED_EXTERNAL"
        assert body["simulated"] is True
        wechat = await client.post("/api/integrations/wechat/simulate", json={"session_id": sid, "content": "hi"})
        assert wechat.json()["personal_wechat"] == "refused"


def json_text(payload) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)
