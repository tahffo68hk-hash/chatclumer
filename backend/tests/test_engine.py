import asyncio

import pytest

from app.db import Database
from app.engine import RoomEngine, input_token_estimate
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
    assert tokens.calls == 0
    assert session["run_tokens"] == 0
    assert session["end_reason"] == "limit_tokens"


@pytest.mark.asyncio
async def test_token_cap_reserves_input_before_parallel_calls(tmp_path, monkeypatch):
    monkeypatch.setattr("app.engine.input_token_estimate", lambda _req: 40)
    provider = EchoProvider(delay=0.15)
    db, engine, room = make(
        tmp_path, provider, mode="free_chat", max_rounds=1, max_ai_messages=10, max_tokens=50, max_seconds=30
    )
    for name in ("甲", "乙", "丙"):
        add_member(db, room["id"], name)
    await engine.ingest_message(room["id"], "并发输入")
    session = await finish(engine, room["id"], timeout=3)
    assert provider.calls == 1
    assert session["end_reason"] == "limit_tokens"
    assert session["run_tokens"] >= 40
    await asyncio.sleep(0.3)
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_cross_talk_is_not_a_full_fixed_rotation(tmp_path):
    provider = EchoProvider(delay=0.01)
    db, engine, room = make(tmp_path, provider, mode="free_chat", max_rounds=3, max_ai_messages=10, max_seconds=30)
    for name, role in (("甲", "质疑者"), ("乙", "工程师"), ("丙", "产品")):
        add_member(db, room["id"], name, role)
    await engine.ingest_message(room["id"], "一起看公开记录")
    await finish(engine, room["id"])
    cross = [m for m in complete_ai(db, room["id"]) if m["phase"] == "cross"]
    by_round: dict[int, list] = {}
    for message in cross:
        by_round.setdefault(message["round_number"], []).append(message)
    assert by_round
    assert all(len(items) == 1 for items in by_round.values())
    assert len({m["nickname"] for m in cross}) <= 2
    assert any("公开记录" in prompt or "公开发言" in prompt or "我读了" in prompt for prompt in provider.prompts)
    assert input_token_estimate(type("R", (), {"prompt": "abc"})()) == 3


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


SIX = ("主要结论", "共识", "分歧", "未验证事实", "最推荐建议", "下一步行动")


class SynthesisProvider:
    def __init__(self):
        self.calls = []

    def preflight(self, req):
        return None

    async def stream(self, req, cancel, stale):
        self.calls.append(req.phase)
        if cancel.is_set() or stale.is_set():
            return
        if req.phase == "summary":
            yield "\n".join(
                [
                    "## 主要结论",
                    "综合后的结论。",
                    "## 共识",
                    "双方都接受先做小范围验证。",
                    "## 分歧",
                    "对是否立刻推广仍有分歧。",
                    "## 未验证事实",
                    "还没有外部数据。",
                    "## 最推荐建议",
                    "先做可观察的小实验。",
                    "## 下一步行动",
                    "由用户决定是否采纳。",
                ]
            )
        else:
            yield f"公开看法 {req.member_nickname}"


@pytest.mark.asyncio
async def test_provider_summary_is_one_six_part_synthesis(tmp_path):
    provider = SynthesisProvider()
    db, engine, room = make(
        tmp_path,
        provider,
        mode="independent",
        max_rounds=1,
        max_ai_messages=4,
        max_seconds=30,
        summary_mode="provider",
        summary_provider="openai",
        summary_model_id="gpt-4o-mini",
    )
    add_member(db, room["id"], "甲")
    add_member(db, room["id"], "乙", "工程师")
    await engine.ingest_message(room["id"], "请综合")
    session = await finish(engine, room["id"])
    reports = summaries(db, room["id"])
    assert provider.calls.count("summary") == 1
    assert session["ai_message_count"] <= 4
    assert len(reports) == 1
    report = reports[0]
    assert report["provider"] == "openai"
    assert report["model_id"] == "gpt-4o-mini"
    assert report["is_demo"] is False
    assert "【本地回顾" not in report["content"]
    assert "【演示" not in report["content"]
    for heading in SIX:
        assert heading in report["content"]
    await asyncio.sleep(0.2)
    assert provider.calls.count("summary") == 1
    assert len(summaries(db, room["id"])) == 1


@pytest.mark.asyncio
async def test_summary_stays_local_when_stopped_or_unbudgeted_or_unkeyed(tmp_path):
    provider = GateProvider()
    db, engine, room = make(
        tmp_path,
        provider,
        mode="free_chat",
        max_rounds=3,
        max_ai_messages=6,
        max_seconds=30,
        summary_mode="provider",
        summary_provider="openai",
        summary_model_id="gpt-4o-mini",
    )
    add_member(db, room["id"], "甲")
    await engine.ingest_message(room["id"], "停")
    await slot(provider, 0)
    await engine.stop(room["id"])
    session = await finish(engine, room["id"])
    assert session["status"] == "stopped"
    assert all(phase != "summary" for phase in [item["req"].phase for item in provider.order])
    report = summaries(db, room["id"])[0]
    assert report["provider"] == "local"
    assert "本地回顾" in report["content"]
    assert "未再请求总结模型" in report["content"]

    cheap = SynthesisProvider()
    db, engine, room = make(
        tmp_path,
        cheap,
        mode="independent",
        max_rounds=1,
        max_ai_messages=2,
        max_tokens=1,
        max_seconds=30,
        summary_mode="provider",
        summary_provider="openai",
        summary_model_id="gpt-4o-mini",
    )
    add_member(db, room["id"], "甲")
    add_member(db, room["id"], "乙", "工程师")
    await engine.ingest_message(room["id"], "预算")
    session = await finish(engine, room["id"])
    assert cheap.calls == []
    assert session["ai_message_count"] == 0
    assert session["end_reason"] == "limit_tokens"
    local = summaries(db, room["id"])
    assert len(local) == 1
    assert local[0]["model_id"] == "local-retrospective"
    assert "未再请求总结模型" in local[0]["content"]

    secrets = SecretStore(str(tmp_path / "empty-secrets.json"))
    def refuse_network():
        raise AssertionError("should not dial")

    routed = RoutedProvider(secrets, client_factory=refuse_network)
    db, engine, room = make(
        tmp_path,
        routed,
        mode="independent",
        max_rounds=1,
        max_ai_messages=4,
        max_seconds=30,
        summary_mode="provider",
        summary_provider="anthropic",
        summary_model_id="claude-sonnet-4-5",
    )
    add_member(db, room["id"], "甲")
    await engine.ingest_message(room["id"], "无密钥")
    session = await finish(engine, room["id"])
    assert routed.network_calls == 0
    assert session["status"] == "finished"
    report = summaries(db, room["id"])[0]
    assert report["provider"] == "local"
    assert report["model_id"] == "local-retrospective"
    assert "本地回顾" in report["content"]
    assert "未调用" in report["content"]
    assert "伪装" in report["content"]


def test_summary_without_replies_does_not_invent_a_discussion():
    text = build_summary(
        [{"author_type": "user", "content": "这句不该引出假回复", "status": "complete"}],
        "no_members",
    )
    assert "各成员回应了" not in text
    assert "可观察的小实验" not in text
    assert "没有可回顾的成员公开发言" in text
    assert "没有可发言的成员" in text


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


class _CountingProvider:
    def __init__(self):
        self.calls = 0

    async def stream(self, req, cancel, stale):
        self.calls += 1
        yield f"RUNMARK{self.calls} 建议先做第{self.calls}件事。"


@pytest.mark.asyncio
async def test_local_summary_only_uses_the_current_run(tmp_path):
    # 同一房间第二次发起时，本地回顾的「主要结论」不能引用上一次运行的答复。
    provider = _CountingProvider()
    db, engine, room = make(tmp_path, provider, mode="independent", max_rounds=1, max_ai_messages=10, max_seconds=30)
    a = add_member(db, room["id"], "甲")
    b = add_member(db, room["id"], "乙", "工程师")
    await engine.ingest_message(room["id"], "第一个问题")
    first = await finish(engine, room["id"])
    # 第二次换了一批成员（实页上是先 Qwen/Z.ai/DeepSeek，后文心/智谱）。
    db.update_member(a["id"], {"enabled": False})
    db.update_member(b["id"], {"enabled": False})
    add_member(db, room["id"], "丙")
    add_member(db, room["id"], "丁", "工程师")
    await engine.ingest_message(room["id"], "第二个问题")
    second = await finish(engine, room["id"])
    assert first["run_token"] != second["run_token"]
    assert provider.calls == 4
    rows = summaries(db, room["id"])
    assert len(rows) == 2
    old, new = rows[0]["content"], rows[1]["content"]
    assert "RUNMARK1" in old and "RUNMARK2" in old
    assert "RUNMARK3" in new and "RUNMARK4" in new
    assert "RUNMARK1" not in new and "RUNMARK2" not in new
    assert "甲" not in new and "乙" not in new
    assert "第二个问题" in new and "第一个问题" not in new
