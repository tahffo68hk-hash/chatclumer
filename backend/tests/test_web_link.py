from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import create_app


def _web_body(nickname="网页甲", origin="http://127.0.0.1:43124/fixture/chat", key="fixture-key"):
    return {
        "nickname": nickname,
        "role_name": "读者",
        "persona": "",
        "provider": "web",
        "model_id": "web:fixture",
        "web_site": "fixture",
        "web_origin": origin,
        "web_tab_key": key,
        "web_auto": True,
    }


def test_new_web_member_waits_for_the_extension_and_rolls_back_nothing(tmp_path):
    app = create_app(str(tmp_path / "room.db"), str(tmp_path / "secrets.json"))
    client = TestClient(app)
    created = client.post("/api/sessions", json={"title": "绑定", "max_rounds": 1, "max_seconds": 30}).json()
    saved = client.post(f"/api/sessions/{created['id']}/members/web", json=_web_body())
    assert saved.status_code == 200
    assert saved.json()["web_link"] == "已配置，等待扩展绑定"
    duplicate = client.post(f"/api/sessions/{created['id']}/members/web", json=_web_body())
    assert duplicate.status_code == 409
    mismatch = client.post(
        f"/api/sessions/{created['id']}/members/web",
        json=_web_body(nickname="网页乙", origin="https://evil.example/chat", key="other-key"),
    )
    assert mismatch.status_code == 400
    members = client.get(f"/api/sessions/{created['id']}").json()["members"]
    assert [item["nickname"] for item in members] == ["网页甲"]
    code = client.post("/api/ext/code").json()["code"]
    token = client.post("/api/ext/pair", json={"code": code}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    beat = client.post(
        "/api/ext/tabs",
        headers=headers,
        json={"tabs": [{"tab_key": "fixture-key", "origin": "http://127.0.0.1:43124", "alive": True}]},
    )
    assert beat.status_code == 200
    linked = client.get(f"/api/sessions/{created['id']}").json()["members"][0]
    assert linked["web_link"] == "已绑定标签页"
    stale = (datetime.now(timezone.utc) - timedelta(seconds=40)).isoformat()
    app.state.db.conn.execute("UPDATE members SET web_seen_at=? WHERE id=?", (stale, linked["id"]))
    app.state.db.conn.commit()
    dropped = client.get(f"/api/sessions/{created['id']}").json()["members"][0]
    assert dropped["web_link"] == "掉线"


def test_extension_tab_heartbeat_rejects_another_site(tmp_path):
    app = create_app(str(tmp_path / "room.db"), str(tmp_path / "secrets.json"))
    client = TestClient(app)
    code = client.post("/api/ext/code").json()["code"]
    token = client.post("/api/ext/pair", json={"code": code}).json()["token"]
    denied = client.post(
        "/api/ext/tabs",
        headers={"Authorization": f"Bearer {token}", "Origin": "https://yuanbao.tencent.com"},
        json={"tabs": []},
    )
    assert denied.status_code == 403


def test_unbound_tab_does_not_send_and_progress_replaces_the_waiting_line(tmp_path):
    app = create_app(str(tmp_path / "room.db"), str(tmp_path / "secrets.json"))
    client = TestClient(app)
    created = client.post("/api/sessions", json={"title": "进度", "max_rounds": 1, "max_seconds": 30}).json()
    saved = client.post(f"/api/sessions/{created['id']}/members/web", json=_web_body()).json()
    sent = client.post(f"/api/sessions/{created['id']}/messages", json={"content": "读书", "audience": "all"})
    assert sent.status_code == 200
    import time
    time.sleep(0.4)
    body = str(client.get(f"/api/sessions/{created['id']}/messages").json())
    assert "扩展还没有确认这个标签页仍打开" in body
    count = app.state.engine.web.db.conn.execute("SELECT COUNT(*) AS n FROM ext_jobs").fetchone()[0]
    assert count == 0
    client.post(f"/api/sessions/{created['id']}/stop")
    message = app.state.db.add_message(
        {
            "session_id": created["id"],
            "member_id": saved["id"],
            "nickname": "网页甲",
            "role_name": "读者",
            "provider": "web",
            "model_id": "web:fixture",
            "author_type": "ai",
            "content": "等待回复",
            "status": "streaming",
        }
    )
    app.state.engine.web.create_job(
        {
            "request_id": "job-progress",
            "session_id": created["id"],
            "member_id": saved["id"],
            "context_version": 1,
            "origin": "http://127.0.0.1:43124",
            "site": "fixture",
            "tab_key": "fixture-key",
            "prompt": "读书",
        }
    )
    code = client.post("/api/ext/code").json()["code"]
    token = client.post("/api/ext/pair", json={"code": code}).json()["token"]
    progress = client.post(
        "/api/ext/jobs/progress",
        headers={"Authorization": f"Bearer {token}"},
        json={"request_id": "job-progress", "phase": "unsent"},
    )
    assert progress.status_code == 200
    updated = app.state.db.get_message(message["id"])
    assert updated["content"] == "已填入，未发送"
    assert updated["status"] == "streaming"
