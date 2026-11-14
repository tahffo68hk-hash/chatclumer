import asyncio

import pytest

from app.db import Database
from app.engine import RoomEngine
from app.providers import DemoProvider, ProviderError, RoutedProvider
from app.secrets import SecretStore
from app.summary import build_summary
from tests.fakes import CostProvider, EchoProvider, FlakyProvider, GateProvider, SlowProvider, ViewpointProvider


def make(tmp_path, provider, **session):
    db = Database(str(tmp_path / "room.db"))
    engine = RoomEngine(db, provider)
    room = db.create_session(cross_delay_ms=0, **session)
    return db, engine, room


def add_member(db, sid, nickname, role="质疑者", provider="demo", model="demo-synthesizer-v1"):
    return db.create_member(
        session_id=sid,
        nickname=nickname,
        role_name=role,
        persona="测试角色",
        provider=provider,
        model_id=model,
        enabled=True,
    )


async def slot(provider, index, timeout=2):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if len(provider.order) > index:
            await asyncio.wait_for(provider.order[index]["started"].wait(), timeout)
            return provider.order[index]
        await asyncio.sleep(0.01)
    raise TimeoutError(f"only {len(provider.order)} calls")


async def finish(engine, sid, timeout=3):
    task = engine.tasks[sid]
    await asyncio.wait_for(task, timeout)
    return engine.db.get_session(sid)


def summaries(db, sid):
    return [m for m in db.list_messages(sid) if m["is_summary"] and m["status"] == "complete"]


def complete_ai(db, sid):
    return [
        m
        for m in db.list_messages(sid)
        if m["author_type"] == "ai" and m["status"] == "complete" and not m["is_summary"]
    ]


@pytest.mark.asyncio
async def test_parallel_snapshot_and_overlap(tmp_path):
    provider = EchoProvider(delay=0.12)
    db, engine, room = make(tmp_path, provider, mode="independent", max_rounds=1, max_ai_messages=10, max_seconds=30)
    add_member(db, room["id"], "甲", "工程师")
    add_member(db, room["id"], "乙", "产品")
    await engine.ingest_message(room["id"], "要不要做群聊？")
    session = await finish(engine, room["id"])
    assert session["status"] == "finished"
    assert provider.calls == 2
    assert max(provider.starts) < min(provider.ends)
    assert all("UNIQUE_" not in prompt for prompt in provider.prompts)
    assert {m["content"] for m in complete_ai(db, room["id"])} == {"UNIQUE_甲", "UNIQUE_乙"}
    assert len(summaries(db, room["id"])) == 1


@pytest.mark.asyncio
async def test_message_cap_does_not_overshoot(tmp_path):
    provider = EchoProvider(delay=0.05)
    db, engine, room = make(tmp_path, provider, mode="independent", max_rounds=3, max_ai_messages=2, max_seconds=30)
    for name in ("甲", "乙", "丙"):
        add_member(db, room["id"], name)
    await engine.ingest_message(room["id"], "限额测试")
    session = await finish(engine, room["id"])
    assert provider.calls == 2
    assert session["ai_message_count"] == 2
    assert session["end_reason"] == "limit_messages"
    assert session["status"] == "finished"
    assert len(summaries(db, room["id"])) == 1


@pytest.mark.asyncio
async def test_round_cap_skips_cross_talk(tmp_path):
    provider = EchoProvider(delay=0.01)
    db, engine, room = make(tmp_path, provider, mode="free_chat", max_rounds=1, max_ai_messages=10, max_seconds=30)
    add_member(db, room["id"], "甲")
    add_member(db, room["id"], "乙", "工程师")
    await engine.ingest_message(room["id"], "只独立回答")
    session = await finish(engine, room["id"])
    assert session["end_reason"] == "limit_rounds"
    assert all(m["round_number"] == 1 for m in complete_ai(db, room["id"]))
    assert all(m["phase"] == "independent" for m in complete_ai(db, room["id"]))


@pytest.mark.asyncio
async def test_cost_and_token_caps_stop_before_next_request(tmp_path):
    cost = CostProvider(cost=0.5, tokens=8)
    db, engine, room = make(tmp_path, cost, mode="independent", max_rounds=1, max_ai_messages=10, max_cost_usd=0.4, max_seconds=30)
    add_member(db, room["id"], "甲")
    add_member(db, room["id"], "乙", "工程师")
    await engine.ingest_message(room["id"], "费用")
    session = await finish(engine, room["id"])
    assert cost.calls == 1
    assert session["end_reason"] == "limit_cost"

    tokens = CostProvider(cost=0, tokens=8)
    db, engine, room = make(tmp_path, tokens, mode="independent", max_rounds=1, max_ai_messages=10, max_tokens=10, max_seconds=30)
    add_member(db, room["id"], "甲")
    add_member(db, room["id"], "乙", "工程师")
    await engine.ingest_message(room["id"], "token")
    session = await finish(engine, room["id"])
    assert tokens.calls == 1
    assert session["end_reason"] == "limit_tokens"


@pytest.mark.asyncio
async def test_watchdog_cancels_blocked_model_call(tmp_path):
    provider = SlowProvider()
    db, engine, room = make(tmp_path, provider, mode="independent", max_rounds=2, max_ai_messages=10, max_seconds=0.4)
    add_member(db, room["id"], "甲")
    await engine.ingest_message(room["id"], "超时")
    session = await finish(engine, room["id"], timeout=2)
    assert session["status"] == "stopped"
    assert session["end_reason"] == "limit_time"
    assert provider.calls == 1
    assert all("LATE" not in m["content"] for m in db.list_messages(room["id"]))
    await asyncio.sleep(0.3)
    assert provider.calls == 1
    assert len(summaries(db, room["id"])) == 1


@pytest.mark.asyncio
async def test_user_stop_and_no_self_trigger(tmp_path):
    provider = GateProvider()
    db, engine, room = make(tmp_path, provider, mode="free_chat", max_rounds=3, max_ai_messages=10, max_seconds=30)
    add_member(db, room["id"], "甲")
    blocked = await engine.ingest_message(room["id"], "先说", author_type="ai")
    assert blocked["error"] == "model_output_cannot_trigger"
    assert db.count_runs(room["id"]) == 0
    await engine.ingest_message(room["id"], "开始")
    await slot(provider, 0)
    again = await engine.start(room["id"])
    assert again["already"] is True
    assert db.count_runs(room["id"]) == 1
    await engine.stop(room["id"])
    session = await finish(engine, room["id"])
    assert session["status"] == "stopped"
    assert session["end_reason"] == "user_stop"
    assert len(provider.order) == 1
    assert len(summaries(db, room["id"])) == 1
    await asyncio.sleep(0.2)
    assert db.count_runs(room["id"]) == 1
    assert len(provider.order) == 1


@pytest.mark.asyncio
async def test_interrupt_discards_stale_and_keeps_one_run(tmp_path):
    provider = GateProvider()
    db, engine, room = make(tmp_path, provider, mode="free_chat", max_rounds=2, max_ai_messages=6, max_seconds=30)
    add_member(db, room["id"], "林知秋")
    await engine.ingest_message(room["id"], "先做方案A")
    await slot(provider, 0)
    await engine.ingest_message(room["id"], "改成方案B")
    await slot(provider, 1)
    assert "方案B" in provider.order[1]["req"].prompt
    assert "方案B" not in provider.order[0]["req"].prompt
    provider.order[1]["go"].set()
    session = await finish(engine, room["id"])
    assert db.count_runs(room["id"]) == 1
    assert any(m["status"] == "discarded" and m["discarded_reason"] == "stale_context" for m in db.list_messages(room["id"]))
    assert any("方案B" in m["content"] for m in complete_ai(db, room["id"]))
    assert session["status"] in {"finished", "stopped"}
    assert len(summaries(db, room["id"])) == 1


@pytest.mark.asyncio
async def test_pause_does_not_start_next_speaker(tmp_path):
    provider = GateProvider()
    db, engine, room = make(tmp_path, provider, mode="free_chat", max_rounds=2, max_ai_messages=6, max_seconds=30)
    add_member(db, room["id"], "甲", "工程师")
    await engine.ingest_message(room["id"], "暂停测试")
    await slot(provider, 0)
    assert (await engine.pause(room["id"]))["ok"] is True
    provider.order[0]["go"].set()
    for _ in range(50):
        if complete_ai(db, room["id"]):
            break
        await asyncio.sleep(0.02)
    assert len(provider.order) == 1
    await asyncio.sleep(0.2)
    assert len(provider.order) == 1
    assert engine.db.get_session(room["id"])["status"] == "paused"
    assert (await engine.resume(room["id"]))["ok"] is True
    await slot(provider, 1)
    provider.order[1]["go"].set()
    session = await finish(engine, room["id"])
    assert len(provider.order) == 2
    assert session["status"] == "finished"


@pytest.mark.asyncio
async def test_provider_failure_is_visible_and_redacted(tmp_path):
    provider = FlakyProvider({"坏成员"})
    db, engine, room = make(tmp_path, provider, mode="independent", max_rounds=1, max_ai_messages=10, max_seconds=30)
    add_member(db, room["id"], "坏成员")
    add_member(db, room["id"], "好成员", "工程师")
    await engine.ingest_message(room["id"], "失败隔离")
    session = await finish(engine, room["id"])
    assert session["status"] == "finished"
    texts = " ".join(m["content"] for m in db.list_messages(room["id"]))
    assert "sk-secretSHOULDNOTLEAK" not in texts
    assert any(m["status"] == "error" for m in db.list_messages(room["id"]))
    assert any(m["content"] == "正常公开回答" for m in complete_ai(db, room["id"]))

    provider = FlakyProvider({"甲", "乙"})
    db, engine, room = make(tmp_path, provider, mode="independent", max_rounds=1, max_ai_messages=10, max_seconds=30)
    add_member(db, room["id"], "甲")
    add_member(db, room["id"], "乙", "工程师")
    await engine.ingest_message(room["id"], "全部失败")
    session = await finish(engine, room["id"])
    assert session["status"] == "failed"
    assert session["end_reason"] == "provider_failed"
    assert len(summaries(db, room["id"])) == 1


@pytest.mark.asyncio
async def test_early_stop_and_summary_once(tmp_path):
    provider = ViewpointProvider()
    db, engine, room = make(tmp_path, provider, mode="free_chat", max_rounds=3, max_ai_messages=10, max_seconds=30)
    add_member(db, room["id"], "甲")
    await engine.ingest_message(room["id"], "还有新观点吗")
    session = await finish(engine, room["id"])
    assert provider.calls == 2
    assert session["end_reason"] == "no_new_viewpoints"
    assert session["current_round"] == 2
    assert len(summaries(db, room["id"])) == 1
    engine._write_local_summary(room["id"], session["run_token"], session["end_reason"], "")
    assert len(summaries(db, room["id"])) == 1
    text = summaries(db, room["id"])[0]["content"]
    for heading in ("主要结论", "共识", "分歧", "未验证事实", "最推荐建议", "下一步行动"):
        assert heading in text


@pytest.mark.asyncio
async def test_recover_does_not_restart_or_duplicate_summary(tmp_path):
    provider = SlowProvider()
    db, engine, room = make(tmp_path, provider, mode="free_chat", max_rounds=3, max_ai_messages=10, max_seconds=30)
    add_member(db, room["id"], "甲")
    await engine.ingest_message(room["id"], "恢复")
    await asyncio.wait_for(provider.entered.wait(), 2)
    await engine.recover()
    session = db.get_session(room["id"])
    assert session["status"] == "stopped"
    assert session["end_reason"] == "server_restart"
    assert len(summaries(db, room["id"])) == 1
    await engine.recover()
    assert len(summaries(db, room["id"])) == 1
    assert db.get_session(room["id"])["status"] == "stopped"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_paid_provider_without_permission_does_not_impersonate(tmp_path):
    def factory():
        raise AssertionError("network")

    secrets = SecretStore(str(tmp_path / "secrets.json"))
    secrets.set("OPENAI_API_KEY", "sk-test-not-real")
    provider = RoutedProvider(secrets, client_factory=factory)
    db, engine, room = make(tmp_path, provider, mode="independent", max_rounds=1, max_ai_messages=4, max_seconds=30)
    add_member(db, room["id"], "GPT", "工程师", provider="openai", model="gpt-4o-mini")
    await engine.ingest_message(room["id"], "不要伪装")
    session = await finish(engine, room["id"])
    assert provider.network_calls == 0
    blob = " ".join(m["content"] for m in db.list_messages(room["id"]))
    assert "sk-test-not-real" not in blob
    assert "演示回复" not in blob
    assert "计费" in blob or "拒绝" in blob
    assert session["status"] == "failed"
    demo = DemoProvider()
    text = demo.render(
        type("R", (), {
            "phase": "independent",
            "role_name": "质疑者",
            "user_latest": "问题",
            "reply_to": None,
            "suggest_next_nickname": None,
            "round_number": 1,
            "transcript": [],
            "end_reason": "",
        })()
    )
    assert text.startswith("【演示回复 · 非真实模型】")


def test_summary_mentions_disagreement():
    text = build_summary(
        [
            {"author_type": "user", "content": "做不做？", "status": "complete"},
            {
                "author_type": "ai",
                "nickname": "林知秋",
                "role_name": "质疑者",
                "provider": "demo",
                "model_id": "demo-synthesizer-v1",
                "member_id": "a",
                "content": "这个结论可能把未验证事实当成前提。我质疑它。",
                "status": "complete",
                "is_summary": False,
            },
        ],
        "limit_rounds",
    )
    assert "质疑" in text
    assert "可能" in text
    assert "【本地回顾 · 未额外请求模型】" in text
