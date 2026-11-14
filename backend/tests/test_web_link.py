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
