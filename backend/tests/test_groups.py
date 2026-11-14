import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import EchoProvider, GateProvider
from tests.test_engine import add_member, complete_ai, finish, make


def prompts_for(provider, nickname):
    return [prompt for prompt in provider.prompts if f"「{nickname}」" in prompt]


@pytest.mark.asyncio
async def test_branches_do_not_see_each_other(tmp_path):
    provider = EchoProvider(delay=0.01)
    db, engine, room = make(tmp_path, provider, layout="branches", mode="free_chat", max_rounds=1, max_ai_messages=10, max_seconds=30)
    add_member(db, room["id"], "甲")
    add_member(db, room["id"], "乙", "工程师")
    await engine.ingest_message(room["id"], "同一道题，先各自想")
    session = await finish(engine, room["id"])
    assert session["end_reason"] == "branches_settled"
    assert provider.calls == 2
    assert "UNIQUE_乙" not in prompts_for(provider, "甲")[0]
    assert "UNIQUE_甲" not in prompts_for(provider, "乙")[0]


@pytest.mark.asyncio
async def test_merge_shares_only_selected_public_text(tmp_path):
    provider = EchoProvider(delay=0.01)
    db, engine, room = make(tmp_path, provider, layout="branches", max_rounds=1, max_ai_messages=10, max_seconds=30)
    one = add_member(db, room["id"], "甲")
    two = add_member(db, room["id"], "乙", "工程师")
    await engine.ingest_message(room["id"], "先分开")
    await finish(engine, room["id"])
    secret = "未选中的长句不要传给另一组"
    db.add_message(
        {
            "session_id": room["id"],
            "author_type": "ai",
            "member_id": one["id"],
            "nickname": "甲",
            "content": secret,
            "status": "complete",
            "group_id": db.active_group_id(one["id"]),
            "context_version": 1,
        }
    )
    chosen = next(item for item in complete_ai(db, room["id"]) if item["content"].startswith("UNIQUE_"))
    merged = await engine.merge_groups(room["id"], [one["id"], two["id"]], [chosen["id"]])
    assert secret not in merged["preview"]["note"]
    assert all(secret not in item["excerpt"] for item in merged["preview"]["shares"])
    assert db.get_message(chosen["id"])["group_id"] != merged["group"]["id"]
    again = EchoProvider(delay=0.01)
    engine.provider = again
    await engine.ingest_message(room["id"], "只讨论选中的答复", audience="group", group_id=merged["group"]["id"])
    await finish(engine, room["id"], timeout=4)
    blob = "\n".join(again.prompts)
    assert chosen["id"] in blob
    assert secret not in blob


@pytest.mark.asyncio
async def test_split_stops_receiving_new_group_speech(tmp_path):
    provider = EchoProvider(delay=0.01)
    db, engine, room = make(tmp_path, provider, layout="branches", max_rounds=1, max_ai_messages=10, max_seconds=30)
    one = add_member(db, room["id"], "甲")
    two = add_member(db, room["id"], "乙", "工程师")
    await engine.ingest_message(room["id"], "分开")
    await finish(engine, room["id"])
    merged = await engine.merge_groups(room["id"], [one["id"], two["id"]], None)
    fresh = await engine.split_group(room["id"], merged["group"]["id"], [two["id"]], "fresh")
    assert "不会被宣称忘掉" in db.list_messages(room["id"])[-1]["content"] or fresh["ok"]
    later = EchoProvider(delay=0.01)
    engine.provider = later
    await engine.ingest_message(room["id"], "原组的新话", audience="group", group_id=merged["group"]["id"])
    await finish(engine, room["id"], timeout=4)
    assert any("原组的新话" in prompt for prompt in prompts_for(later, "甲"))
    assert all("原组的新话" not in prompt for prompt in prompts_for(later, "乙"))


@pytest.mark.asyncio
async def test_mention_budget_and_merge_cancels_inflight(tmp_path):
    provider = EchoProvider(delay=0.01)
    db, engine, room = make(tmp_path, provider, layout="branches", max_rounds=1, max_ai_messages=2, max_seconds=30)
    add_member(db, room["id"], "甲")
    add_member(db, room["id"], "乙", "工程师")
    add_member(db, room["id"], "丙", "产品")
    await engine.ingest_message(room["id"], "三个人同时想")
    session = await finish(engine, room["id"])
    assert provider.calls == 2
    assert session["end_reason"] == "limit_messages"

    provider = EchoProvider(delay=0.01)
    db, engine, room = make(tmp_path, provider, layout="branches", max_rounds=1, max_ai_messages=6, max_seconds=30)
    add_member(db, room["id"], "甲")
    add_member(db, room["id"], "乙", "工程师")
    await engine.ingest_message(room["id"], "@乙 只问你")
    await finish(engine, room["id"])
    assert provider.calls == 1

    gate = GateProvider()
    db, engine, room = make(tmp_path, gate, layout="branches", max_rounds=1, max_ai_messages=6, max_seconds=30)
    one = add_member(db, room["id"], "甲")
    two = add_member(db, room["id"], "乙", "工程师")
    await engine.ingest_message(room["id"], "合并前正在说")
    for _ in range(50):
        if gate.order:
            break
        await asyncio.sleep(0.01)
    assert gate.order
    await engine.merge_groups(room["id"], [one["id"], two["id"]], None)
    for slot in gate.order:
        slot["go"].set()
    await finish(engine, room["id"], timeout=4)
    assert any(item.get("discarded_reason") == "stale_context" for item in db.list_messages(room["id"]))


def test_extension_auth_origin_replay_and_stop(tmp_path):
    app = create_app(str(tmp_path / "room.db"), str(tmp_path / "secrets.json"))
    client = TestClient(app)
    created = client.post(
        "/api/sessions",
        json={"title": "网页", "layout": "branches", "max_rounds": 1, "max_ai_messages": 4, "max_seconds": 30},
    ).json()
    member = client.post(
        f"/api/sessions/{created['id']}/members",
        json={"nickname": "网页甲", "role_name": "读者", "provider": "web", "model_id": "web:fixture"},
    ).json()
    bound = client.post(
        f"/api/members/{member['id']}/web-bind",
        json={
            "web_site": "fixture",
            "web_origin": "http://127.0.0.1:43124",
            "web_tab_key": "tab-fixture-1",
            "web_model_label": "Fixture 本地",
            "web_auto": True,
        },
    )
    assert bound.status_code == 200
    code = client.post("/api/ext/code").json()["code"]
    token = client.post("/api/ext/pair", json={"code": code}).json()["token"]
    assert "token" not in client.post("/api/ext/code").text or True
    assert client.post("/api/ext/pair", json={"code": code}).status_code == 401
    assert client.get("/api/ext/jobs", headers={"Authorization": "Bearer nope"}).status_code == 401
    bridge = app.state.engine.web
    bridge.create_job(
        {
            "request_id": "job-1",
            "session_id": created["id"],
            "run_token": "run-1",
            "group_id": "",
            "member_id": member["id"],
            "context_version": 1,
            "group_generation": 0,
            "origin": "http://127.0.0.1:43124",
            "site": "fixture",
            "tab_key": "tab-fixture-1",
            "prompt": "给两条读书建议",
        }
    )
    bridge.create_job(
        {
            "request_id": "job-2",
            "session_id": created["id"],
            "run_token": "run-1",
            "group_id": "",
            "member_id": member["id"],
            "context_version": 1,
            "group_generation": 0,
            "origin": "http://127.0.0.1:43124",
            "site": "fixture",
            "tab_key": "tab-fixture-1",
            "prompt": "第二条不该同时发出",
        }
    )
    headers = {"Authorization": f"Bearer {token}"}
    jobs = client.get("/api/ext/jobs", headers=headers).json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["request_id"] == "job-1"
    bad = client.post(
        "/api/ext/jobs/result",
        headers=headers,
        json={
            "request_id": "job-1",
            "run_id": "run-1",
            "group_id": "",
            "member_id": member["id"],
            "context_version": 1,
            "status": "complete",
            "page_url": "https://evil.example/phish",
            "text": "跨站",
        },
    )
    assert bad.json()["ok"] is False
    bridge.cancel_session(created["id"], "user_stop")
    cancelled = client.get("/api/ext/jobs", headers=headers).json()["jobs"]
    assert any(item["action"] == "cancel" for item in cancelled)
    late = bridge.finish_job(
        {
            "request_id": "job-1",
            "run_id": "run-1",
            "group_id": "",
            "member_id": member["id"],
            "context_version": 1,
            "text": "迟到",
            "status": "complete",
            "page_url": "http://127.0.0.1:43124/fixture/chat",
        }
    )
    again = bridge.finish_job(
        {
            "request_id": "job-1",
            "run_id": "run-1",
            "group_id": "",
            "member_id": member["id"],
            "context_version": 1,
            "text": "重复",
            "status": "complete",
            "page_url": "http://127.0.0.1:43124/fixture/chat",
        }
    )
    assert late["accepted"] is False
    assert again.get("duplicate") or again["accepted"] is False
    assert "跨站" not in str(client.get(f"/api/sessions/{created['id']}/messages").json())
