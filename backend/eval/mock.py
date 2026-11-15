"""Deterministic mock members for the eval harness. NOT a model: it only checks the harness wiring.

The first member answers some reasoning questions wrongly on its own (the classic intuitive mistake)
and fixes them once it has read a correct peer answer in a later round. Other members answer correctly.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

QUESTIONS = {q["question"]: q for q in json.loads((Path(__file__).parent / "questions.json").read_text(encoding="utf-8"))["questions"]}

WRONG_FIRST = {"r1": "球是 0.10 元。", "r2": "要 100 分钟。", "r3": "要 24 天。"}
RIGHT = {
    "r1": "球是 0.05 元，也就是 5 分：设球 x，则 x + (x + 1) = 1.10。",
    "r2": "还是 5 分钟，每台机器 5 分钟做 1 个。",
    "r3": "47 天，因为第 48 天翻倍才盖满。",
    "r4": "小红现在 9 岁：(x + x + 3) + 10 = 31。",
    "f1": "100 摄氏度。",
    "f2": "曹雪芹。",
    "f3": "大约每秒 30 万公里（299792 公里）。",
}
OPINION = {
    "o1": ["先做网页版：成本低、迭代快。", "App 的分发和留存更好，但第一版用户还不确定。"],
    "o2": ["看目标：想求职先实习积累经验。", "兴趣明确、时间充足时自学也很值。"],
    "o3": ["新人去办公室沟通和学习更快。", "在家效率可能更高，但需要自律。"],
}


class MockEvalProvider:
    label = "mock-eval（模拟成员，不是真实模型）"

    def __init__(self):
        self.calls = 0

    def preflight(self, req):
        return None

    async def stream(self, req, cancel, stale):
        self.calls += 1
        await asyncio.sleep(0)
        q = QUESTIONS.get((req.user_latest or "").strip())
        qid = q["id"] if q else ""
        first = req.member_nickname.endswith("1")
        if qid in OPINION:
            parts = OPINION[qid]
            text = parts[0] if first else parts[-1]
        elif first and qid in WRONG_FIRST and req.phase == "independent":
            text = WRONG_FIRST[qid]
        elif first and qid in WRONG_FIRST:
            text = f"我看了其他成员的推理，改正：{RIGHT[qid]}"
        else:
            text = RIGHT.get(qid, "我不确定。")
        yield text
