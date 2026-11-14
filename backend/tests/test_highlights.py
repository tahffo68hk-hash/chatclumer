from fastapi.testclient import TestClient

from app.main import create_app
from app.opinions import discussion_splits


def test_highlight_keeps_the_wording_and_disagreement_stays_empty_without_a_reply(tmp_path):
    app = create_app(str(tmp_path / "room.db"), str(tmp_path / "secrets.json"))
    client = TestClient(app)
    created = client.post("/api/sessions", json={"title": "收藏", "max_rounds": 1, "max_ai_messages": 2, "max_seconds": 20}).json()
    sent = client.post(f"/api/sessions/{created['id']}/messages", json={"content": "先记下这句，不要当成定论。"})
    assert sent.status_code == 200
    message_id = sent.json()["message"]["id"]
    saved = client.put(
        f"/api/sessions/{created['id']}/highlights",
        json={"message_id": message_id, "title": "待查的一句", "note": "只是备注"},
    )
    assert saved.status_code == 200
    assert "不是已核实事实" in saved.json()["disclaimer"]
    cards = client.get(f"/api/sessions/{created['id']}/highlights").json()["cards"]
    assert cards[0]["excerpt"].startswith("先记下这句")
    assert cards[0]["title"] == "待查的一句"
    again = client.get(f"/api/sessions/{created['id']}/highlights").json()
    assert again["cards"][0]["id"] == cards[0]["id"]
    empty = client.get(f"/api/sessions/{created['id']}/disagreements").json()
    assert empty["items"] == []
    assert empty["consensus"] == []
    assert "不编共识" in empty["notice"]
    too_long = client.put(
        f"/api/sessions/{created['id']}/highlights",
        json={"message_id": message_id, "title": "超" * 41, "note": ""},
    )
    assert too_long.status_code == 400


def test_only_an_explicit_reply_becomes_a_disagreement():
    plain = discussion_splits(
        [
            {"id": "a", "status": "complete", "content": "先这样读", "nickname": "甲", "role_name": "读者", "member_id": "m1"},
            {"id": "b", "status": "complete", "reply_to_id": "a", "content": "我补充一个例子。", "nickname": "乙", "role_name": "工程师", "member_id": "m2"},
        ]
    )
    assert plain["items"] == []
    assert plain["consensus"] == []
    voiced = discussion_splits(
        [
            {"id": "a", "status": "complete", "content": "这已经可以当结论。", "nickname": "甲", "role_name": "读者", "member_id": "m1"},
            {"id": "b", "status": "complete", "reply_to_id": "a", "content": "我质疑这句还没有证据。", "nickname": "乙", "role_name": "记录", "member_id": "m2"},
        ]
    )
    assert len(voiced["items"]) == 1
    assert voiced["items"][0]["label"] == "讨论观点"
    assert voiced["items"][0]["source_message_id"] == "a"
    assert voiced["consensus"] == []
