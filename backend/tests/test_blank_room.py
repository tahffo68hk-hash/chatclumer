"""默认房间不预置成员。扩展只能在配对后按名字拿到网页成员。"""

from fastapi.testclient import TestClient
from app.main import create_app

def test_blank_session_has_no_members_and_keeps_existing_demo(tmp_path):
    app = create_app(str(tmp_path / "room.db"), str(tmp_path / "secrets.json"))
    client = TestClient(app)
    demo = client.post("/api/sessions", json={"title": "旧演示", "template": "demo"}).json()
    blank = client.post("/api/sessions", json={"title": "空白房间"}).json()
    demo_members = client.get(f"/api/sessions/{demo['id']}").json()["members"]
    blank_members = client.get(f"/api/sessions/{blank['id']}").json()["members"]
    assert {item["nickname"] for item in demo_members} == {"林知秋", "周衡", "苏晚"}
    assert blank_members == []
    again = client.get(f"/api/sessions/{demo['id']}").json()["members"]
    assert len(again) == 3

def test_extension_lists_web_members_only_after_pairing(tmp_path):
    app = create_app(str(tmp_path / "room.db"), str(tmp_path / "secrets.json"))
    client = TestClient(app)
    created = client.post("/api/sessions", json={"title": "真实房间"}).json()
    client.post(f"/api/sessions/{created['id']}/members", json={"nickname": "假的", "role_name": "演示", "provider": "demo", "model_id": "demo-synthesizer-v1"})
    saved = client.post(f"/api/sessions/{created['id']}/members/web", json={"nickname": "元宝网页", "role_name": "读者", "provider": "web", "model_id": "web:yuanbao", "web_site": "yuanbao", "web_origin": "https://yuanbao.tencent.com/chat/", "web_tab_key": "yuanbao-roomkey", "web_auto": False})
    assert saved.status_code == 200
    denied = client.get("/api/ext/members")
    assert denied.status_code == 401
    code = client.post("/api/ext/code").json()["code"]
    token = client.post("/api/ext/pair", json={"code": code}).json()["token"]
    listed = client.get("/api/ext/members", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    body = listed.json()
    assert [item["nickname"] for item in body["members"]] == ["元宝网页"]
    assert body["members"][0]["web_tab_key"] == "yuanbao-roomkey"
    assert "token" not in body
    assert "sk-" not in listed.text
