"""Eval harness: single model vs group discussion on a fixed question set.

    cd backend && .venv/bin/python -m eval.run_eval --mock --out eval/results/mock
    cd backend && .venv/bin/python -m eval.run_eval --members members.json --out eval/results/mine

members.json is a list like
    [{"nickname": "甲1", "provider": "ollama", "model_id": "qwen2.5:7b"},
     {"nickname": "乙2", "provider": "openai_compatible", "model_id": "x", "api_base": "http://127.0.0.1:1234/v1"}]
API members use the same server-side keys (backend/data/secrets.json or env) and the same paid-call guard
as the app: nothing that may cost money runs unless "允许可能计费的调用" is on. Web members are not
supported here (they need the browser extension and a person at the page).

The single-model answer is the first member answering alone (independent mode, one round). The group
answer is the room's local retrospective after a free discussion (default 3 rounds). Scores:
  - reasoning/factual: correct if the answer contains an accepted answer and none of the known wrong ones
  - opinion: share of the listed points that the answer mentions
An optional LLM judge (--judge-member) scores each answer 1-5; it is off by default.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from app.db import Database  # noqa: E402
from app.engine import RoomEngine  # noqa: E402

QUESTIONS = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))["questions"]


def score(question: dict, answer: str) -> dict:
    text = answer or ""
    if question["kind"] in {"reasoning", "factual"}:
        hit = any(a in text for a in question["accept"])
        wrong = [r for r in question.get("reject", []) if r in text]
        return {"correct": bool(hit and not wrong), "accepted_hit": hit, "wrong_hits": wrong}
    points = question.get("points", [])
    found = [p for p in points if p in text]
    return {"coverage": round(len(found) / len(points), 2) if points else 0.0, "points_found": found}


async def run_room(db: Database, engine: RoomEngine, members: list[dict], question: str, mode: str, rounds: int, timeout: float) -> dict:
    room = db.create_session(title=f"eval:{mode}", mode=mode, max_rounds=rounds, max_ai_messages=max(4, rounds * len(members) + 2), max_seconds=timeout, cross_delay_ms=0, stop_on_no_new_point=False)
    for m in members:
        db.create_member(
            session_id=room["id"], nickname=m["nickname"], role_name=m.get("role_name") or "成员", persona=m.get("persona") or "",
            provider=m["provider"], model_id=m["model_id"], api_base=m.get("api_base"), api_key_env=m.get("api_key_env"), enabled=True,
        )
    started = time.monotonic()
    await engine.ingest_message(room["id"], question)
    task = engine.tasks.get(room["id"])
    if task:
        await asyncio.wait_for(task, timeout + 5)
    elapsed = round(time.monotonic() - started, 2)
    rows = db.list_messages(room["id"])
    ai = [r for r in rows if r["author_type"] == "ai" and r["status"] == "complete" and not r["is_summary"]]
    summary = [r for r in rows if r["is_summary"] and r["status"] == "complete"]
    session = db.get_session(room["id"])
    return {"ai": ai, "summary": summary[-1]["content"] if summary else "", "elapsed_s": elapsed, "end_reason": session.get("end_reason"), "ai_messages": len(ai)}


async def judge(judge_provider, judge_member: dict, question: str, answer: str) -> int | None:
    """Ask a configured API member for a 1-5 score. Returns None when it cannot score."""
    from app.providers import GenRequest

    prompt = f"请给下面的回答打分，1 到 5 的整数，只输出数字。\n问题：{question}\n回答：{answer[:3000]}"
    req = GenRequest(
        member_id="judge", member_nickname=judge_member.get("nickname", "评委"), role_name="评委", persona="",
        provider=judge_member["provider"], model_id=judge_member["model_id"], api_base=judge_member.get("api_base"),
        api_key_env=judge_member.get("api_key_env"), round_number=1, phase="summary", mode="summary", transcript=[],
        user_latest=question, reply_to=None, suggest_next_nickname=None, room_rule="", prompt=prompt,
    )
    if getattr(judge_provider, "preflight", None) and judge_provider.preflight(req):
        return None
    text = ""
    async for chunk in judge_provider.stream(req, asyncio.Event(), asyncio.Event()):
        text += chunk
    digits = [c for c in text if c in "12345"]
    return int(digits[0]) if digits else None


async def evaluate(members: list[dict], provider, label: str, rounds: int = 3, timeout: float = 120, judge_member: dict | None = None, judge_provider=None, limit: int | None = None) -> dict:
    tmp = tempfile.mkdtemp()
    db = None
    try:
        db = Database(str(Path(tmp) / "eval.db"))
        engine = RoomEngine(db, provider)
        items = []
        for q in QUESTIONS[:limit] if limit else QUESTIONS:
            single = await run_room(db, engine, members[:1], q["question"], "independent", 1, timeout)
            group = await run_room(db, engine, members, q["question"], "free_chat", rounds, timeout)
            single_answer = single["ai"][-1]["content"] if single["ai"] else ""
            group_answer = group["summary"] or "\n".join(m["content"] for m in group["ai"])
            item = {
                "id": q["id"], "kind": q["kind"], "question": q["question"],
                "single": {"answer": single_answer, "score": score(q, single_answer), "elapsed_s": single["elapsed_s"], "ai_messages": single["ai_messages"]},
                "group": {"answer": group_answer, "score": score(q, group_answer), "elapsed_s": group["elapsed_s"], "ai_messages": group["ai_messages"], "end_reason": group["end_reason"]},
            }
            if judge_member and judge_provider:
                item["single"]["judge"] = await judge(judge_provider, judge_member, q["question"], single_answer)
                item["group"]["judge"] = await judge(judge_provider, judge_member, q["question"], group_answer)
            items.append(item)
        return {"label": label, "created_at": datetime.now(timezone.utc).isoformat(), "members": [{k: m.get(k) for k in ("nickname", "provider", "model_id")} for m in members], "rounds": rounds, "items": items, "totals": totals(items)}
    finally:
        if db is not None:
            db.close()
        shutil.rmtree(tmp)


def totals(items: list[dict]) -> dict:
    def agg(side: str) -> dict:
        closed = [i for i in items if i["kind"] in {"reasoning", "factual"}]
        opinion = [i for i in items if i["kind"] == "opinion"]
        judged = [i[side]["judge"] for i in items if isinstance(i[side].get("judge"), int)]
        return {
            "correct": sum(1 for i in closed if i[side]["score"]["correct"]),
            "closed_total": len(closed),
            "opinion_coverage": round(sum(i[side]["score"]["coverage"] for i in opinion) / len(opinion), 2) if opinion else None,
            "ai_messages": sum(i[side]["ai_messages"] for i in items),
            "elapsed_s": round(sum(i[side]["elapsed_s"] for i in items), 2),
            "judge_mean": round(sum(judged) / len(judged), 2) if judged else None,
        }

    return {"single": agg("single"), "group": agg("group")}


def markdown(report: dict, mock: bool) -> str:
    t = report["totals"]
    lines = []
    if mock:
        lines += ["> **模拟运行（MOCK）**：成员是 `eval/mock.py` 里写死的假回答，不是任何真实模型。", "> 这份结果只证明评测流程能跑通，不能用来比较模型或说明群聊更好。", ""]
    lines += [f"# 评测报告：{report['label']}", "", f"- 时间：{report['created_at']}", f"- 成员：{', '.join(f'{m['nickname']}（{m['provider']} / {m['model_id']}）' for m in report['members'])}", f"- 群聊轮数：{report['rounds']}；单模型 = 第一个成员独立回答一轮", ""]
    lines += ["| 指标 | 单模型 | 群聊 |", "| --- | --- | --- |"]
    lines.append(f"| 推理/事实题答对 | {t['single']['correct']}/{t['single']['closed_total']} | {t['group']['correct']}/{t['group']['closed_total']} |")
    lines.append(f"| 观点题要点覆盖 | {t['single']['opinion_coverage']} | {t['group']['opinion_coverage']} |")
    lines.append(f"| AI 消息数 | {t['single']['ai_messages']} | {t['group']['ai_messages']} |")
    lines.append(f"| 用时（秒） | {t['single']['elapsed_s']} | {t['group']['elapsed_s']} |")
    lines.append(f"| 评委均分（1–5） | {t['single']['judge_mean'] if t['single']['judge_mean'] is not None else '未启用'} | {t['group']['judge_mean'] if t['group']['judge_mean'] is not None else '未启用'} |")
    lines += ["", "评分规则：推理/事实题要含参考答案、且不含已知错误答案才算对；观点题按列出的要点被提到的比例计。群聊答案取房间结束时的本地回顾。", "", "## 逐题", ""]
    for item in report["items"]:
        s, g = item["single"]["score"], item["group"]["score"]
        fmt = (lambda sc: "对" if sc.get("correct") else "错") if item["kind"] != "opinion" else (lambda sc: f"覆盖 {sc['coverage']}")
        lines.append(f"- **{item['id']}**（{item['kind']}）{item['question']} — 单模型：{fmt(s)}；群聊：{fmt(g)}")
    return "\n".join(lines) + "\n"


def write(report: dict, out: Path, mock: bool) -> None:
    out.mkdir(parents=True, exist_ok=True)
    report = {**report, "mock": mock}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "report.md").write_text(markdown(report, mock), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mock", action="store_true", help="用写死的模拟成员（不调用任何模型）")
    parser.add_argument("--members", help="成员 JSON 文件")
    parser.add_argument("--judge-member", help="评委成员 JSON（单个对象，必须是 API 成员），可选")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--out", default=str(HERE / "results" / "latest"))
    args = parser.parse_args()
    judge_member = json.loads(Path(args.judge_member).read_text(encoding="utf-8")) if args.judge_member else None
    if args.mock:
        from eval.mock import MockEvalProvider

        provider = MockEvalProvider()
        members = [{"nickname": "模拟甲1", "provider": "mock", "model_id": "mock-eval"}, {"nickname": "模拟乙2", "provider": "mock", "model_id": "mock-eval"}, {"nickname": "模拟丙3", "provider": "mock", "model_id": "mock-eval"}]
        label = "mock（模拟成员）"
    else:
        if not args.members:
            parser.error("需要 --members 或 --mock")
        from app.providers import RoutedProvider
        from app.secrets import SecretStore

        provider = RoutedProvider(SecretStore(str(HERE.parent / "data" / "secrets.json")))
        members = json.loads(Path(args.members).read_text(encoding="utf-8"))
        if any(m.get("provider") == "web" for m in members):
            parser.error("评测不支持网页成员")
        label = ", ".join(m["model_id"] for m in members)
    judge_provider = provider if judge_member else None
    report = asyncio.run(evaluate(members, provider, label, args.rounds, args.timeout, judge_member, judge_provider, args.limit))
    write(report, Path(args.out), args.mock)
    print(f"wrote {args.out}/report.md")


if __name__ == "__main__":
    main()
